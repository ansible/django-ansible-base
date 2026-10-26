import logging
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, NoReturn

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.logging import log_auth_event, log_auth_exception

logger = logging.getLogger("ansible_base.authentication.bearer_authentication")
_REQUEST_CHALLENGE_ATTRIBUTE = "_ansible_base_bearer_authentication_challenge"


@dataclass(frozen=True)
class ScopedBearerToken:
    """Verified non-local Bearer credential metadata exposed to DRF permissions."""

    scopes: frozenset[str]

    @property
    def scope(self) -> str:
        """Expose the same space-delimited scope shape as local OAuth2 tokens."""
        return " ".join(sorted(self.scopes))


@dataclass(frozen=True)
class BearerAuthenticationResult:
    """Allow API authenticators to return a user and safe request-auth metadata."""

    user: AbstractBaseUser
    auth: Any


class BearerTokenValidationError(Exception):
    """Describe an expected rejection from an API authenticator that owns a token.

    API authenticators return ``None`` when a credential is not theirs.  Once
    an authenticator recognizes a token, this exception retains a safe failure
    classification while allowing the dispatcher to try later authenticators.
    No token value or provider-supplied exception text is carried here.
    """

    _FAILURES = {
        "invalid": ("Invalid Bearer token.", None),
        "expired": ("Bearer token has expired.", "The access token expired"),
        "provider_unavailable": ("Authentication service unavailable.", "Authentication service unavailable"),
    }

    def __init__(self, reason: str = "invalid") -> None:
        """Initialize a safe, RFC 6750-compatible token rejection reason."""
        if reason not in self._FAILURES:
            reason = "invalid"
        self.reason = reason
        self.detail, self.error_description = self._FAILURES[reason]
        super().__init__(self.detail)


class BearerAuthenticationFailed(AuthenticationFailed):
    """Return an RFC 6750 Bearer challenge for the final dispatcher failure."""

    def __init__(self, failure: BearerTokenValidationError | None = None) -> None:
        """Build a client-safe response from the highest-priority plugin failure."""
        failure = failure or BearerTokenValidationError()
        super().__init__(failure.detail, code="invalid_token")

        challenge = ['Bearer realm="api"', 'error="invalid_token"']
        if failure.error_description:
            challenge.append(f'error_description="{failure.error_description}"')
        # DRF uses this attribute directly when constructing a 401 response.
        self.auth_header = ", ".join(challenge)


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

    def authenticate(self, request: Request) -> tuple[AbstractBaseUser, Any] | None:
        """Authenticate a Bearer token or reject it after every Bearer handler declines it."""
        logger.debug("Authenticating with BearerAuthentication")

        credential = self._get_bearer_credential(request)
        if credential is None:
            return None
        auth_scheme, token = credential

        first_failure = None
        if auth_scheme == "bearer":
            # API authenticator plugins determine whether they own a token. The
            # dispatcher intentionally does not assume Bearer tokens are JWTs.
            user, auth, first_failure = self._authenticate_api_plugins(request, token)
            if user is not None:
                return user, auth

        # ``Token`` is a documented compatibility form for local OAuth2
        # clients. Local OAuth2 is also the final standard-Bearer handler, so a
        # valid local token remains usable when external plugins decline it.
        local_oauth_result = self._authenticate_local_oauth(request)
        if local_oauth_result is not None:
            return local_oauth_result

        self._raise_failure(request, first_failure if auth_scheme == "bearer" else None)

    def _get_bearer_credential(self, request: Request) -> tuple[str, str] | None:
        """Return a supported authorization scheme and token, or decline another scheme."""
        authorization = request.headers.get("Authorization")
        if not authorization:
            logger.debug("No Authorization header found")
            return None

        auth_type, _, token = authorization.partition(" ")
        auth_scheme = auth_type.lower()
        if auth_scheme not in {"bearer", "token"}:
            logger.debug("Authorization header is not a Bearer credential")
            return None

        token = token.strip()
        if not token:
            self._raise_failure(request)
        return auth_scheme, token

    def _authenticate_api_plugins(self, request: Request, token: str) -> tuple[AbstractBaseUser | None, Any | None, BearerTokenValidationError | None]:
        """Try API plugins and preserve the first expected failure for a final 401."""
        first_failure = None
        for authenticator_id, authenticator in self._api_authentication_backends().items():
            try:
                result = authenticator.authenticate(request, token=token)
            except BearerTokenValidationError as exc:
                # An expected failure from a matching plugin does not stop later
                # providers from authenticating an overlapping token.
                if first_failure is None:
                    first_failure = exc
                logger.debug(f"API authenticator with ID {authenticator_id} rejected a token it owns: {exc.reason}")
                continue
            except Exception:
                log_auth_exception(f'API authenticator with ID "{authenticator_id}" raised an exception')
                continue

            if isinstance(result, BearerAuthenticationResult):
                user, auth = result.user, result.auth
            elif result is not None:
                # Existing plugins return only a user. Do not expose the raw
                # credential through request.auth, and give the compatibility
                # path no scopes until the plugin adopts the richer contract.
                user, auth = result, ScopedBearerToken(scopes=frozenset())
                logger.warning(f'API authenticator with ID "{authenticator_id}" returned a bare user; applying empty scopes')
            else:
                user, auth = None, None

            if user is not None:
                log_auth_event(f'User {user.username} authenticated with API authenticator with ID "{authenticator_id}"')
                return user, auth, first_failure

        return None, None, first_failure

    def authenticate_header(self, request: Request) -> str:
        """Return the OAuth2-provided Bearer challenge for rejected Bearer credentials."""
        # APIView.handle_exception obtains the response header from this method,
        # rather than from an AuthenticationFailed instance. Preserve a safe
        # per-request challenge recorded by ``_raise_failure`` above.
        challenge = getattr(request, _REQUEST_CHALLENGE_ATTRIBUTE, None)
        if challenge:
            return challenge

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

    def _authenticate_local_oauth(self, request: Request) -> tuple[AbstractBaseUser, Any] | None:
        """Delegate to local OAuth2 only when its optional application is installed."""
        if not self._oauth2_provider_installed():
            return None

        # Import lazily so BearerAuthentication works with authentication-only
        # deployments and API plugins that use non-OAuth Bearer credentials.
        from ansible_base.oauth2_provider.authentication import LoggedOAuth2Authentication

        return LoggedOAuth2Authentication().authenticate(request)

    @staticmethod
    def _raise_failure(request: Request, failure: BearerTokenValidationError | None = None) -> NoReturn:
        """Raise a final Bearer failure and retain its challenge for DRF response handling."""
        exception = BearerAuthenticationFailed(failure)
        setattr(request, _REQUEST_CHALLENGE_ATTRIBUTE, exception.auth_header)
        raise exception

    def _api_authentication_backends(self) -> OrderedDict[int, Any]:
        """Load cached API authenticators using the newest API row as the cache version."""
        # Include disabled rows: enabling or disabling an authenticator must
        # evict a cache created while its prior state was in effect.
        last_modified_item = Authenticator.objects.filter(category="api_auth").values("modified").order_by("-modified").first()
        last_modified = None if last_modified_item is None else last_modified_item.get("modified")
        return get_api_authentication_backends(last_modified)
