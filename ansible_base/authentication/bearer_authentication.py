import logging
from collections import OrderedDict
from functools import lru_cache
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.http import HttpRequest
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.logging import log_auth_event, log_auth_exception

logger = logging.getLogger("ansible_base.authentication.bearer_authentication")
User = get_user_model()


@lru_cache(maxsize=1)
def get_api_authentication_backends(last_updated: Any) -> OrderedDict[int, Any]:
    """Return enabled API-authenticator plugins, cached until their configuration changes.

    ``last_updated`` is deliberately an argument only to invalidate this small
    process-local cache. Plugin instances retain their database configuration,
    so rebuilding them only when an API authenticator changes avoids a database
    query and repeated plugin construction for every bearer-token request.
    """
    authentication_backends = OrderedDict()

    for database_authenticator in Authenticator.objects.filter(enabled=True, category="api_auth").order_by("order"):
        try:
            plugin = get_authenticator_plugin(database_authenticator.type)
        except ImportError:
            continue

        # Plugins use this to bind the instance and refresh their configuration.
        plugin.update_if_needed(database_authenticator)
        authentication_backends[database_authenticator.id] = plugin

    return authentication_backends


class BearerAuthentication(BaseAuthentication):
    """Dispatch standard Bearer credentials to configured API authenticators and local OAuth2."""

    def authenticate(self, request: HttpRequest) -> tuple[User, Any] | None:
        """Authenticate a Bearer token or reject it after every Bearer handler declines it."""
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

        if auth_scheme == "bearer":
            # API authenticator plugins determine whether they own a token. The
            # dispatcher intentionally does not assume Bearer tokens are JWTs.
            for authenticator_id, authenticator in self._api_authentication_backends().items():
                try:
                    user = authenticator.authenticate(request, token=token)
                except Exception:
                    log_auth_exception(f'API authenticator with ID "{authenticator_id}" raised an exception')
                    continue

                if user is not None:
                    log_auth_event(f'User {user.username} authenticated with API authenticator with ID "{authenticator_id}"')
                    return user, token

        # ``Token`` is a documented compatibility form for local OAuth2
        # clients. Local OAuth2 is also the final standard-Bearer handler, so a
        # valid local token remains usable when external plugins decline it.
        local_oauth_result = self._authenticate_local_oauth(request)
        if local_oauth_result is not None:
            return local_oauth_result

        raise AuthenticationFailed("Invalid Bearer token.")

    def authenticate_header(self, request: HttpRequest) -> str:
        """Return the OAuth2-provided Bearer challenge for rejected Bearer credentials."""
        if not self._oauth2_provider_installed():
            return "Bearer"

        # Keep the OAuth2 import lazy: authentication-only applications do not
        # install the provider's models or dependencies.
        from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

        return LoggedOAuth2Authentication().authenticate_header(request)

    @staticmethod
    def _oauth2_provider_installed() -> bool:
        """Return whether the optional DAB OAuth2 provider is available for Bearer fallback."""
        return "ansible_base.oauth2_provider" in settings.INSTALLED_APPS

    def _authenticate_local_oauth(self, request: HttpRequest) -> tuple[User, Any] | None:
        """Delegate to local OAuth2 only when its optional application is installed."""
        if not self._oauth2_provider_installed():
            return None

        # Import lazily so BearerAuthentication works with authentication-only
        # deployments and API plugins that use non-OAuth Bearer credentials.
        from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

        return LoggedOAuth2Authentication().authenticate(request)

    def _api_authentication_backends(self) -> OrderedDict[int, Any]:
        """Load cached API authenticators using the newest API row as the cache version."""
        # Include disabled rows: enabling or disabling an authenticator must
        # evict a cache created while its prior state was in effect.
        last_modified_item = Authenticator.objects.filter(category="api_auth").values("modified").order_by("-modified").first()
        last_modified = None if last_modified_item is None else last_modified_item.get("modified")
        return get_api_authentication_backends(last_modified)
