import logging
from typing import Any

from django.http import HttpRequest
from jwt import decode
from jwt.exceptions import PyJWTError
from rest_framework.authentication import BaseAuthentication

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import Authenticator

logger = logging.getLogger("ansible_base.authentication.external_oauth_authentication")
EXTERNAL_OAUTH_AUTHENTICATOR_TYPE = "ansible_base.authentication.authenticator_plugins.external_oauth"


class ExternalOAuthAuthentication(BaseAuthentication):
    """Authenticate bearer tokens using configured external OAuth authenticators."""

    def authenticate(self, request: HttpRequest) -> tuple[Any, str] | None:
        """Select candidate authenticators from unverified routing claims, then validate the token."""
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
            # These claims only select a preconfigured authenticator; the
            # selected plugin validates them cryptographically before use.
            payload = decode(token, options={"verify_signature": False})
            issuer = payload.get("iss", None)
            audience = payload.get("aud", None)
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

        # The database filter avoids creating plugins or fetching JWKS data for
        # providers that cannot validate this issuer/audience combination.
        matching_authenticators = Authenticator.objects.filter(
            enabled=True,
            category="api_auth",
            type=EXTERNAL_OAUTH_AUTHENTICATOR_TYPE,
            configuration__ISSUER_URL=issuer,
            configuration__AUDIENCE__in=audiences,
        ).order_by("order")
        logger.debug(f"Number of matching authenticators: {len(matching_authenticators)}")

        if not matching_authenticators:
            logger.debug("No active external OAuth provider is configured for the token issuer and audience")
            return None
        for authenticator in matching_authenticators:
            try:
                # Each request gets a plugin bound to the current database row,
                # avoiding mutable process-local authenticator state.
                plugin = get_authenticator_class(authenticator.type)(database_instance=authenticator)
                user = plugin.authenticate(request, token=token)
            except Exception:
                logger.exception("External OAuth authenticator %s failed", authenticator.name)
                continue

            if user is not None:
                logger.debug(f"Authentication successful with authenticator: {authenticator.name}: {user.username}")
                return user, token

        logger.debug("No api_auth authenticators for the token issuer and audience could authenticate this token")
        return None
