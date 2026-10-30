from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from ansible_base.authentication.bearer_authentication import (
    BearerAuthentication,
    BearerAuthenticationFailed,
    BearerAuthenticationResult,
    BearerTokenValidationError,
    ScopedBearerToken,
    get_api_authentication_backends,
)
from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.permissions import TokenScopePermission
from ansible_base.authentication.session import SessionAuthentication


def _django_request(token: str | None = None, scheme: str = "Bearer"):
    """Build a Django request that optionally has an Authorization credential."""
    headers = {} if token is None else {"HTTP_AUTHORIZATION": f"{scheme} {token}"}
    return RequestFactory().get("/", **headers)


def _request(token: str | None = None, scheme: str = "Bearer"):
    """Build a DRF request matching what BearerAuthentication receives in production."""
    return Request(_django_request(token, scheme))


class _BearerProtectedView(APIView):
    """Exercise DRF's authentication-error-to-response flow for Bearer challenges."""

    authentication_classes = [BearerAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        """Return a response only after the configured authentication succeeds."""
        return Response()


class _SessionThenBearerProtectedView(_BearerProtectedView):
    """Mirror authentication-enabled applications, where SessionAuthentication is first."""

    authentication_classes = [SessionAuthentication, BearerAuthentication]


@pytest.fixture(autouse=True)
def clear_api_authenticator_cache():
    """Keep the process-local API-authenticator cache isolated between tests."""
    get_api_authentication_backends.cache_clear()
    yield
    get_api_authentication_backends.cache_clear()


@pytest.mark.django_db
@pytest.mark.parametrize("auth_request", [_request(), _request("token", scheme="Basic")])
def test_bearer_authentication_ignores_missing_or_non_bearer_authorization(auth_request):
    """Credentials belonging to another authentication scheme are not claimed."""
    assert BearerAuthentication().authenticate(auth_request) is None


@pytest.mark.django_db
def test_bearer_authentication_rejects_an_empty_bearer_token():
    """A declared Bearer scheme with no credential is invalid."""
    authenticator = BearerAuthentication()
    request = _request("")

    with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
        authenticator.authenticate(request)


@pytest.mark.django_db
def test_bearer_authentication_passes_opaque_tokens_to_api_authenticators():
    """The generic dispatcher does not parse or otherwise constrain token format."""
    plugin = Mock()
    plugin.authenticate.return_value = None

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict([(17, plugin)]),
        ),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        request = _request("opaque-token")
        authenticator = BearerAuthentication()
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            authenticator.authenticate(request)

    plugin.authenticate.assert_called_once_with(request, token="opaque-token")


@pytest.mark.django_db
def test_bearer_authentication_returns_and_audits_api_authenticator_success():
    """The first plugin that authenticates a token wins and is audited."""
    plugin = Mock()
    user = Mock(username="external-user")
    plugin.authenticate.return_value = user

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict([(17, plugin)]),
        ),
        patch("ansible_base.authentication.bearer_authentication.log_auth_event") as log_auth_event,
        patch("ansible_base.authentication.bearer_authentication.logger") as logger,
        patch.object(BearerAuthentication, "_authenticate_local_oauth") as local_authenticate,
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (user, ScopedBearerToken(scopes=frozenset()))

    local_authenticate.assert_not_called()
    log_auth_event.assert_called_once_with('User external-user authenticated with API authenticator with ID "17"')
    logger.warning.assert_called_once_with('API authenticator with ID "17" returned a bare user; applying empty scopes')


@pytest.mark.django_db
def test_bearer_authentication_preserves_plugin_scope_context():
    """A scope-aware plugin controls DRF's request.auth without retaining the secret."""
    user = Mock(username="external-user")
    auth = ScopedBearerToken(scopes=frozenset({"read"}))
    plugin = Mock()
    plugin.authenticate.return_value = BearerAuthenticationResult(user=user, auth=auth)

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(17, plugin)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth") as local_authenticate,
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (user, auth)

    local_authenticate.assert_not_called()


@pytest.mark.parametrize(
    "method,scopes,allowed",
    [
        ("GET", set(), False),
        ("POST", set(), False),
        ("GET", {"read"}, True),
        ("POST", {"read"}, False),
        ("GET", {"write"}, True),
        ("POST", {"write"}, True),
    ],
)
def test_token_scope_permission_enforces_scoped_credentials(method, scopes, allowed):
    """Read is the minimum high-level scope and write implies read."""
    request = SimpleNamespace(
        method=method,
        auth=ScopedBearerToken(scopes=frozenset(scopes)),
        user=SimpleNamespace(is_authenticated=True),
    )
    assert TokenScopePermission().has_permission(request, Mock()) is allowed


@pytest.mark.django_db
def test_bearer_authentication_uses_local_oauth_after_api_authenticators_decline():
    """A local OAuth2 token remains valid if no configured API plugin owns it."""
    plugin = Mock()
    plugin.authenticate.return_value = None
    local_user = Mock(username="local-user")
    local_token = Mock()

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict([(17, plugin)]),
        ),
        patch("ansible_base.authentication.bearer_authentication.logger") as logger,
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=(local_user, local_token)) as local_authenticate,
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (local_user, local_token)

    local_authenticate.assert_called_once()
    logger.warning.assert_not_called()


@pytest.mark.django_db
def test_bearer_authentication_tries_later_matching_external_authenticator_after_first_declines():
    """A declined matching provider does not prevent an ordered fallback provider from authenticating."""
    first_matching_external_authenticator = Mock()
    first_matching_external_authenticator.authenticate.return_value = None
    second_matching_external_authenticator = Mock()
    user = Mock(username="external-user")
    second_matching_external_authenticator.authenticate.return_value = user

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict(
                [
                    (17, first_matching_external_authenticator),
                    (42, second_matching_external_authenticator),
                ]
            ),
        ),
        patch.object(BearerAuthentication, "_authenticate_local_oauth") as local_authenticate,
    ):
        request = _request("external-token")
        assert BearerAuthentication().authenticate(request) == (user, ScopedBearerToken(scopes=frozenset()))

    first_matching_external_authenticator.authenticate.assert_called_once_with(request, token="external-token")
    second_matching_external_authenticator.authenticate.assert_called_once_with(request, token="external-token")
    local_authenticate.assert_not_called()


@pytest.mark.django_db
def test_bearer_authentication_preserves_legacy_local_oauth_token_scheme():
    """The legacy Token scheme remains reserved for the local OAuth2 backend."""
    local_user = Mock(username="local-user")
    local_token = Mock()

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends") as api_authenticators,
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=(local_user, local_token)),
    ):
        assert BearerAuthentication().authenticate(_request("token", scheme="Token")) == (local_user, local_token)

    api_authenticators.assert_not_called()


@pytest.mark.django_db
def test_bearer_authentication_continues_after_api_plugin_failure():
    """One faulty plugin does not prevent a later API authenticator from succeeding."""
    rejected_plugin = Mock()
    rejected_plugin.authenticate.side_effect = RuntimeError("bad plugin")
    accepted_plugin = Mock()
    user = Mock(username="external-user")
    accepted_plugin.authenticate.return_value = user

    with patch.object(
        BearerAuthentication,
        "_api_authentication_backends",
        return_value=OrderedDict([(17, rejected_plugin), (42, accepted_plugin)]),
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (user, ScopedBearerToken(scopes=frozenset()))

    rejected_plugin.authenticate.assert_called_once()
    accepted_plugin.authenticate.assert_called_once()


@pytest.mark.django_db
def test_bearer_authentication_tries_later_plugins_after_expected_token_failure():
    """A later matching provider can authenticate after an earlier one rejects a token it owns."""
    rejected_plugin = Mock()
    rejected_plugin.authenticate.side_effect = BearerTokenValidationError("expired")
    accepted_plugin = Mock()
    user = Mock(username="external-user")
    accepted_plugin.authenticate.return_value = user

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict([(17, rejected_plugin), (42, accepted_plugin)]),
        ),
        patch("ansible_base.authentication.bearer_authentication.log_auth_exception") as log_auth_exception,
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (user, ScopedBearerToken(scopes=frozenset()))

    rejected_plugin.authenticate.assert_called_once()
    accepted_plugin.authenticate.assert_called_once()
    log_auth_exception.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "reason,detail,challenge",
    [
        ("invalid", "Invalid Bearer token.", 'Bearer realm="api", error="invalid_token"'),
        (
            "expired",
            "Bearer token has expired.",
            'Bearer realm="api", error="invalid_token", error_description="The access token expired"',
        ),
        (
            "provider_unavailable",
            "Authentication service unavailable.",
            'Bearer realm="api", error="invalid_token", error_description="Authentication service unavailable"',
        ),
    ],
)
def test_bearer_authentication_returns_safe_rfc6750_failure(reason, detail, challenge):
    """The final matching-plugin failure controls the 401 detail and challenge without exposing a token."""
    plugin = Mock()
    plugin.authenticate.side_effect = BearerTokenValidationError(reason)

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(17, plugin)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        authenticator = BearerAuthentication()
        request = _request("opaque-token")
        with pytest.raises(BearerAuthenticationFailed) as exc_info:
            authenticator.authenticate(request)

    assert str(exc_info.value.detail) == detail
    assert exc_info.value.auth_header == challenge


@pytest.mark.django_db
def test_bearer_authentication_preserves_plugin_failure_when_local_oauth_rejects():
    """A local OAuth fallback must not hide a specific external-token failure."""
    plugin = Mock()
    plugin.authenticate.side_effect = BearerTokenValidationError("expired")

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(17, plugin)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", side_effect=AuthenticationFailed("Invalid token")),
    ):
        authenticator = BearerAuthentication()
        request = _request("expired-external-token")
        with pytest.raises(BearerAuthenticationFailed) as exc_info:
            authenticator.authenticate(request)

    assert str(exc_info.value.detail) == "Bearer token has expired."
    assert exc_info.value.auth_header == 'Bearer realm="api", error="invalid_token", error_description="The access token expired"'


@pytest.mark.django_db
def test_bearer_authentication_preserves_local_oauth_failure_when_plugins_decline():
    """A local OAuth failure remains the response when no plugin claimed the token."""
    local_failure = AuthenticationFailed("Invalid token")
    authenticator = BearerAuthentication()
    request = _request("local-oauth-token")

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict()),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", side_effect=local_failure),
    ):
        with pytest.raises(AuthenticationFailed) as exc_info:
            authenticator.authenticate(request)

    assert exc_info.value is local_failure


@pytest.mark.django_db
def test_bearer_authentication_exposes_safe_challenge_in_drf_response():
    """DRF reads the per-request challenge from authenticate_header when rendering a 401."""
    plugin = Mock()
    plugin.authenticate.side_effect = BearerTokenValidationError("expired")

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(17, plugin)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        response = _BearerProtectedView.as_view()(_django_request("opaque-token"))

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="api", error="invalid_token", error_description="The access token expired"'


@pytest.mark.django_db
def test_bearer_authentication_exposes_rfc6750_challenge_when_session_authentication_is_first():
    """DRF uses the first authenticator's header, which must preserve a Bearer challenge."""
    plugin = Mock()
    plugin.authenticate.side_effect = BearerTokenValidationError()

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(17, plugin)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        response = _SessionThenBearerProtectedView.as_view()(_django_request("malformed-token"))

    assert response.status_code == 401
    assert response["WWW-Authenticate"] == 'Bearer realm="api", error="invalid_token"'


@pytest.mark.django_db
def test_bearer_authentication_audits_unexpected_plugin_exceptions_without_token_value():
    """Unexpected plugin defects are audited while expected rejections stay out of the audit log."""
    plugin = Mock()
    plugin.authenticate.side_effect = RuntimeError("untrusted token content")

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(17, plugin)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
        patch("ansible_base.authentication.bearer_authentication.log_auth_exception") as log_auth_exception,
    ):
        authenticator = BearerAuthentication()
        request = _request("untrusted token content")
        with pytest.raises(BearerAuthenticationFailed):
            authenticator.authenticate(request)

    audit_message = log_auth_exception.call_args.args[0]
    assert audit_message == 'API authenticator with ID "17" raised an exception'
    assert "untrusted token content" not in audit_message


@pytest.mark.django_db
def test_bearer_authentication_rejects_token_when_all_handlers_decline():
    """A claimed Bearer credential receives a 401 when no handler can authenticate it."""
    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict()),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        authenticator = BearerAuthentication()
        request = _request("opaque-token")
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            authenticator.authenticate(request)


@pytest.mark.django_db
def test_api_authentication_backends_cache_and_refresh_configuration(oauth_bearer_authenticator):
    """API plugins are rebuilt only when the API-authenticator timestamp changes."""
    plugin = Mock()
    initial_modified = oauth_bearer_authenticator.modified

    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_plugin",
        return_value=plugin,
    ) as get_plugin:
        cached = get_api_authentication_backends(initial_modified)
        assert cached == OrderedDict([(oauth_bearer_authenticator.id, plugin)])
        assert get_api_authentication_backends(initial_modified) is cached
        get_plugin.assert_called_once_with(oauth_bearer_authenticator.type)
        plugin.update_if_needed.assert_called_once_with(oauth_bearer_authenticator)

        oauth_bearer_authenticator.name = "Updated OAuth Bearer authenticator"
        oauth_bearer_authenticator.save()
        get_api_authentication_backends(oauth_bearer_authenticator.modified)

    assert get_plugin.call_count == 2


@pytest.mark.django_db
def test_api_authentication_cache_version_includes_disabled_authenticators(oauth_bearer_authenticator):
    """Enabling a previously disabled API authenticator invalidates a cached dispatcher list."""
    disabled = Authenticator.objects.create(
        name="Disabled API authenticator",
        enabled=False,
        type=oauth_bearer_authenticator.type,
        configuration=oauth_bearer_authenticator.configuration,
        category="api_auth",
        order=oauth_bearer_authenticator.order + 1,
    )
    with patch("ansible_base.authentication.bearer_authentication.get_api_authentication_backends") as get_backends:
        BearerAuthentication()._api_authentication_backends()

    assert get_backends.call_args.args[0] == disabled.modified


@pytest.mark.django_db
def test_api_authentication_backends_skip_plugins_that_are_not_installed(oauth_bearer_authenticator):
    """A configured plugin unavailable in this deployment cannot break Bearer dispatch."""
    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_plugin",
        side_effect=ImportError,
    ):
        assert get_api_authentication_backends(oauth_bearer_authenticator.modified) == OrderedDict()


def test_bearer_authentication_skips_local_oauth_when_its_optional_app_is_absent():
    """Authentication-only deployments must not import local OAuth2 provider code."""
    with patch.object(BearerAuthentication, "_oauth2_provider_installed", return_value=False):
        assert BearerAuthentication()._authenticate_local_oauth(_request("token")) is None


def test_bearer_authentication_returns_the_local_oauth_challenge():
    """Use the established local OAuth2 challenge for all rejected Bearer credentials."""
    request = _request("token")
    with (
        patch.object(BearerAuthentication, "_oauth2_provider_installed", return_value=True),
        patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate_header",
            return_value='Bearer realm="api"',
        ),
    ):
        assert BearerAuthentication().authenticate_header(request) == 'Bearer realm="api"'


def test_bearer_authentication_returns_standard_challenge_without_oauth2_provider():
    """Authentication-only applications expose a standard Bearer challenge."""
    with patch.object(BearerAuthentication, "_oauth2_provider_installed", return_value=False):
        assert BearerAuthentication().authenticate_header(_request("token")) == "Bearer"
