import logging

from jwt import decode
from jwt.exceptions import PyJWTError
from rest_framework.authentication import BaseAuthentication

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import Authenticator

logger = logging.getLogger("ansible_base.authentication.external_oauth_authentication")


class ExternalOAuthAuthentication(BaseAuthentication):
    def authenticate(self, request):
        logger.debug("Authenticating with ExternalOAuthAuthentication")

        authorization = request.headers.get("Authorization")
        if not authorization:
            logger.debug("No Authorization header found")
            return None

        auth_type, _, token = authorization.partition(" ")
        token = token.strip()
        if auth_type != "Bearer" or not token:
            logger.debug("Authorization header is not a valid Bearer token")
            return None

        try:
            # These claims only identify a preconfigured authenticator. They
            # are trusted only after the signature and claims are verified.
            payload = decode(token, options={"verify_signature": False})
            issuer = payload.get("iss", None)
            logger.debug(f"Issuer: {issuer}")
            audience = payload.get("aud", None)
            logger.debug(f"Audience: {audience}")
        except (KeyError, PyJWTError, ValueError, TypeError) as e:
            logger.debug(f"External OAuth token could not be parsed: {e}")
            return None

        if not isinstance(issuer, str):
            logger.debug("External OAuth token issuer is not a string")
            return None
        if isinstance(audience, list):
            if not all(isinstance(value, str) for value in audience):
                logger.debug("External OAuth token audience contains a non-string value")
                return None
            audiences = tuple(sorted(set(audience)))
        elif isinstance(audience, str):
            audiences = (audience,)
        else:
            logger.debug("External OAuth token audience is not a string or list of strings")
            return None

        matching_authenticators = Authenticator.objects.filter(
            enabled=True,
            category="api_auth",
            configuration__ISSUER_URL=issuer,
            configuration__AUDIENCE__in=audiences,
        ).order_by("order")
        logger.debug(f"Number of matching authenticators: {len(matching_authenticators)}")

        if not matching_authenticators:
            logger.debug("No active external OAuth provider is configured for the token issuer and audience")
            return None
        for authenticator in matching_authenticators:
            try:
                plugin = get_authenticator_class(authenticator.type)(database_instance=authenticator)
            except ImportError as e:
                logger.error("Got an import error while getting the authenticator class: %s", e)
                continue

            logger.debug(f"Calling authenticate on authenticator: {authenticator.name}")
            user = plugin.authenticate(request, token=token)

            if user is not None:
                logger.debug(f"Authentication successful with authenticator: {authenticator.name}: {user.username}")
                return user, token

        logger.debug("No api_auth authenticators for the token issuer and audience could authenticate this token")
        return None
