import logging
from collections.abc import Iterable
from typing import Any

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from jwt import decode
from jwt.exceptions import PyJWTError
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_class
from ansible_base.authentication.models import Authenticator
from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication
from ansible_base.lib.logging import log_auth_event, log_auth_exception

logger = logging.getLogger("ansible_base.authentication.bearer_authentication")
User = get_user_model()
EXTERNAL_OAUTH_AUTHENTICATOR_TYPE = "ansible_base.authentication.authenticator_plugins.external_oauth"


class BearerAuthentication(BaseAuthentication):
    """Authenticate Authorization Bearer credentials using external and local OAuth2 providers."""

    def authenticate(self, request: HttpRequest) -> tuple[User, Any] | None:
        """Authenticate a Bearer token or reject it after every configured Bearer handler declines it."""
        logger.debug("Authenticating with BearerAuthentication")

        authorization = request.headers.get("Authorization")
        if not authorization:
            logger.debug("No Authorization header found")
            return None

        auth_type, _, token = authorization.partition(" ")
        token = token.strip()
        auth_scheme = auth_type.lower()
        if auth_scheme not in {"bearer", "token"}:
            logger.debug("Authorization header is not a Bearer credential")
            return None
        if not token:
            raise AuthenticationFailed("Invalid Bearer token.")

        # ``Token`` is a documented compatibility form for local OAuth2
        # clients. External providers accept only the standard Bearer scheme.
        external_authenticators = self._matching_external_authenticators(token) if auth_scheme == "bearer" else []
        for authenticator in external_authenticators:
            try:
                # Each request gets a plugin bound to the current database row,
                # avoiding mutable process-local authenticator state.
                plugin = get_authenticator_class(authenticator.type)(database_instance=authenticator)
                user = plugin.authenticate(request, token=token)
            except Exception:
                log_auth_exception(f"External OAuth authenticator {authenticator.name} failed")
                continue

            if user is not None:
                log_auth_event(f"User {user.username} authenticated with external OAuth authenticator {authenticator.name}")
                return user, token

        # Local OAuth2 access tokens use the same Authorization scheme as an
        # external JWT. They are the final Bearer handler so a configured
        # external provider cannot prevent a valid local token from working.
        local_oauth_result = LoggedOAuth2Authentication().authenticate(request)
        if local_oauth_result is not None:
            return local_oauth_result

        raise AuthenticationFailed("Invalid Bearer token.")

    def authenticate_header(self, request: HttpRequest) -> str:
        """Return the OAuth2-provided Bearer challenge for rejected Bearer credentials."""
        return LoggedOAuth2Authentication().authenticate_header(request)

    def _matching_external_authenticators(self, token: str) -> Iterable[Authenticator]:
        """Return external OAuth authenticators selected by unverified issuer and audience routing claims."""
        try:
            # These claims only select a preconfigured authenticator; the
            # selected plugin validates them cryptographically before use.
            payload = decode(token, options={"verify_signature": False})
            issuer = payload.get("iss", None)
            audience = payload.get("aud", None)
        except (KeyError, PyJWTError, ValueError, TypeError) as e:
            logger.debug(f"External OAuth token could not be parsed: {e}")
            return []

        if not isinstance(issuer, str):
            logger.debug("External OAuth token issuer is not a string")
            return []
        if isinstance(audience, list):
            if not all(isinstance(value, str) for value in audience):
                logger.debug("External OAuth token audience contains a non-string value")
                return []
            audiences = tuple(sorted(set(audience)))
        elif isinstance(audience, str):
            audiences = (audience,)
        else:
            logger.debug("External OAuth token audience is not a string or list of strings")
            return []

        # The database filter avoids creating plugins or fetching JWKS data for
        # providers that cannot validate this issuer/audience combination.
        matching_authenticators = Authenticator.objects.filter(
            enabled=True,
            category="api_auth",
            type=EXTERNAL_OAUTH_AUTHENTICATOR_TYPE,
            configuration__ISSUER_URL=issuer,
            configuration__AUDIENCE__in=audiences,
        ).order_by("order")
        if not matching_authenticators:
            logger.debug("No active external OAuth provider is configured for the token issuer and audience")
        return matching_authenticators
