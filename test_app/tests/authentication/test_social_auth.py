from unittest import mock

import pytest
from django.conf import settings
from django.test import override_settings

from ansible_base.authentication.social_auth import (
    AuthenticatorStorage,
    AuthenticatorStrategy,
    SocialAuthMixin,
    SocialAuthValidateCallbackMixin,
    capture_oauth_email_pipeline,
    create_user_claims_pipeline,
)


@mock.patch("ansible_base.authentication.social_auth.logger")
@override_settings(ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION='does.not.exist')
def test_authenticator_strategy_init_fail_to_load_function(logger):
    _ = AuthenticatorStrategy(storage=AuthenticatorStorage())
    logger.error.assert_any_call(SubstringMatcher(f"Failed to run {settings.ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION} to get additional settings"))


@mock.patch("ansible_base.authentication.social_auth.logger")
@override_settings(ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION='test_app.tests.authentication.test_social_auth.set_settings')
def test_authenticator_strategy_init_load_function(logger):
    strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
    logger.debug.assert_any_call(f"Attempting to load social settings from {settings.ANSIBLE_BASE_SOCIAL_AUTH_STRATEGY_SETTINGS_FUNCTION}")
    assert strategy.settings['A_SETTING'] == "set"


def set_settings():
    return {"A_SETTING": "set"}


# borrowed from https://www.michaelpollmeier.com/python-mock-how-to-assert-a-substring-of-logger-output
class SubstringMatcher:
    def __init__(self, containing):
        self.containing = containing.lower()

    def __eq__(self, other):
        return other.lower().find(self.containing) > -1

    def __unicode__(self):
        return 'a string containing "%s"' % self.containing

    __repr__ = __unicode__


@mock.patch("ansible_base.authentication.social_auth.logger")
def test_authenticator_strategy_redirect_logging(mock_logger):
    """Test that AuthenticatorStrategy.redirect logs the redirect URL without mocking redirect itself."""
    from django.http import HttpResponseRedirect

    strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
    test_url = "https://example.com/oauth/callback"

    # Call the redirect method directly (not mocked)
    result = strategy.redirect(test_url)

    # Verify the logger was called with the correct message
    mock_logger.info.assert_called_once_with(f"Redirecting user to {test_url} as part of the social auth flow for SSO authenticator.")

    # Verify that the result is an HttpResponseRedirect with the correct URL
    assert isinstance(result, HttpResponseRedirect)
    assert result.url == test_url


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.logger")
def test_social_auth_mixin_start_enabled_authenticator(mock_logger, random_user):
    """Test that SocialAuthMixin.start logs when authentication is attempted with an enabled authenticator."""
    from django.http import HttpResponse

    from ansible_base.authentication.models import Authenticator

    # Create a mock authenticator with enabled=True
    authenticator = Authenticator.objects.create(
        name="Test OIDC", slug="test-oidc", type="ansible_base.authentication.authenticator_plugins.oidc", enabled=True, configuration={}
    )

    class MockParent:
        """Mock parent class to avoid dependency on actual social auth backend."""

        def start(self):
            return HttpResponse("OK")

    class TestBackend(SocialAuthMixin, MockParent):
        def __init__(self, database_instance):
            # Mock the strategy argument requirement
            self.strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
            self.database_instance = database_instance
            self.logger = None

    backend = TestBackend(database_instance=authenticator)
    result = backend.start()

    # Verify info logging for starting authentication
    mock_logger.info.assert_called_once_with("Starting Authentication attempt with authenticator 'Test OIDC' (slug: test-oidc)")

    # Verify error was not called (since authenticator is enabled)
    assert not mock_logger.error.called

    # Verify that the result is an HttpResponse
    assert isinstance(result, HttpResponse)


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.logger")
def test_social_auth_mixin_start_disabled_authenticator(mock_logger):
    """Test that SocialAuthMixin.start logs an error and returns 404 for disabled authenticator."""
    from django.http import HttpResponseNotFound

    from ansible_base.authentication.models import Authenticator

    # Create a mock authenticator with enabled=False
    authenticator = Authenticator.objects.create(
        name="Disabled OIDC", slug="disabled-oidc", type="ansible_base.authentication.authenticator_plugins.oidc", enabled=False, configuration={}
    )

    class TestBackend(SocialAuthMixin):
        def __init__(self, database_instance):
            # Mock the strategy argument requirement
            self.strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
            self.database_instance = database_instance
            self.logger = None

    backend = TestBackend(database_instance=authenticator)

    # Call start method
    result = backend.start()

    # Verify error logging for disabled authenticator
    mock_logger.error.assert_called_once_with("Authentication attempted with disabled authenticator Disabled OIDC")

    # Verify info logging was not called (since authenticator is disabled)
    assert not mock_logger.info.called

    # Verify that a 404 response was returned
    assert isinstance(result, HttpResponseNotFound)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "authenticator_type,authenticator_name,minimal_config",
    [
        (
            "ansible_base.authentication.authenticator_plugins.oidc",
            "Test OIDC",
            {
                "OIDC_ENDPOINT": "https://example.com",
                "KEY": "test-key",
                "SECRET": "test-secret",
            },
        ),
        (
            "ansible_base.authentication.authenticator_plugins.azuread",
            "Test Azure AD",
            {
                "KEY": "test-key",
                "SECRET": "test-secret",
            },
        ),
        (
            "ansible_base.authentication.authenticator_plugins.github",
            "Test GitHub",
            {
                "KEY": "test-key",
                "SECRET": "test-secret",
            },
        ),
        (
            "ansible_base.authentication.authenticator_plugins.google_oauth2",
            "Test Google OAuth2",
            {
                "KEY": "test-key",
                "SECRET": "test-secret",
            },
        ),
        (
            "ansible_base.authentication.authenticator_plugins.keycloak",
            "Test Keycloak",
            {
                "ACCESS_TOKEN_URL": "https://keycloak.example.com/token",
                "AUTHORIZATION_URL": "https://keycloak.example.com/auth",
                "KEY": "test-key",
                "PUBLIC_KEY": "test-public-key",
            },
        ),
    ],
)
@mock.patch("ansible_base.authentication.social_auth.logger")
def test_sso_authenticators_log_redirect_and_start(mock_logger, authenticator_type, authenticator_name, minimal_config):
    """
    Test that all SSO authenticators log both the start message and redirect message during auth flow.

    This test verifies that:
    1. SocialAuthMixin.start() logs "Starting Authentication attempt with authenticator..."
    2. AuthenticatorStrategy.redirect() logs "Redirecting user to ... as part of the social auth flow..."

    We do NOT mock redirect itself - we verify the actual logging that happens during the flow.
    """
    from django.http import HttpResponseRedirect
    from django.test import RequestFactory

    from ansible_base.authentication.models import Authenticator

    # Create the authenticator
    authenticator = Authenticator.objects.create(
        name=authenticator_name, slug=f"test-{authenticator_type.split('.')[-1]}", type=authenticator_type, enabled=True, configuration=minimal_config
    )

    # Create a mock request with session
    factory = RequestFactory()
    request = factory.get(f'/login/{authenticator.slug}/')
    # Add a real session backend
    from django.contrib.sessions.backends.db import SessionStore

    request.session = SessionStore()
    request.session.save()

    # Create the strategy with the request
    strategy = AuthenticatorStrategy(storage=AuthenticatorStorage(), request=request)

    # Get the backend for this authenticator
    backend = strategy.get_backend(authenticator.slug)

    # Mock auth_url to return a URL instead of making external calls
    with mock.patch.object(backend, 'auth_url', return_value='https://example.com/auth'):
        # Call start() which should log both start and redirect messages
        result = backend.start()

        # Verify the result is a redirect response
        assert isinstance(result, HttpResponseRedirect), f"{authenticator_type} did not return HttpResponseRedirect"

        # Verify we got the start authentication log message
        start_log_calls = [call for call in mock_logger.info.call_args_list if "Starting Authentication attempt with authenticator" in str(call)]
        assert len(start_log_calls) >= 1, f"{authenticator_type} did not log start authentication message"

        # Verify the start message contains the authenticator name and slug
        start_message = str(start_log_calls[0])
        assert authenticator_name in start_message, f"Start message missing authenticator name: {start_message}"
        assert authenticator.slug in start_message, f"Start message missing authenticator slug: {start_message}"

        # Verify we got the redirect log message
        redirect_log_calls = [call for call in mock_logger.info.call_args_list if "Redirecting user to" in str(call) and "social auth flow" in str(call)]
        assert len(redirect_log_calls) >= 1, f"{authenticator_type} did not log redirect message"

        # Verify the redirect message contains a URL
        redirect_message = str(redirect_log_calls[0])
        assert "https://" in redirect_message or "http://" in redirect_message, f"Redirect message missing URL: {redirect_message}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "test_data,has_instance,has_slug,expected_result",
    [
        ({'foo': 'bar'}, True, True, {'foo': 'bar'}),
        ({'configuration': {'CALLBACK_URL': '/foo/bar'}}, True, True, {'configuration': {'CALLBACK_URL': '/foo/bar'}}),
        ({'configuration': {}}, True, True, {'configuration': {'CALLBACK_URL': '/foo/bar'}}),
        (
            {'type': 'foo', 'name': 'bar', 'configuration': {}},
            False,
            False,
            {'type': 'foo', 'name': 'bar', 'configuration': {'CALLBACK_URL': '/foo/bar'}, 'slug': 'generated_slug'},
        ),
    ],
)
@mock.patch("ansible_base.authentication.social_auth.get_fully_qualified_url")
@mock.patch("ansible_base.authentication.social_auth.generate_authenticator_slug", return_value="generated_slug")
def test_social_auth_validate_callback_mixin(mocked_generate_slug, mocked_reverse, test_data, has_instance, has_slug, expected_result):
    mocked_reverse.return_value = '/foo/bar'

    Serializer = mock.Mock()
    serializer = Serializer()
    serializer.instance = None
    serializer.context = {'request': None}
    if has_instance:
        SerializerInstance = mock.Mock()
        serializer.instance = SerializerInstance()
        if has_slug:
            serializer.instace.slug = 'slug'

    mixin = SocialAuthValidateCallbackMixin()
    res = mixin.validate(serializer, test_data)
    assert res == expected_result

    # should generate a slug if the serializer has no instance
    if not has_instance:
        assert mocked_generate_slug.called

    # should always call reverse if no callback url
    if has_instance and 'configuration' in test_data and not test_data.get('configuration', {}).get('CALLBACK_URL'):
        assert mocked_reverse.called


id_token_no_groups = {
    "ver": "2.0",
    "iss": "https://login.microsoftonline.com/9122040d-6c67-4c5b-b112-36a304b66dad/v2.0",
    "sub": "AAAAAAAAAAAAAAAAAAAAAIkzqFVrSaSaFHy782bbtaQ",
    "aud": "6cb04018-a3f5-46a7-b995-940c78f5aef3",
    "exp": 4073899721,
    "iat": 1536274711,
    "nbf": 1536274711,
    "name": "Abe Lincoln",
    "preferred_username": "AbeLi@microsoft.com",
    "email": "AbeLi@microsoft.com",
    "oid": "00000000-0000-0000-66f3-3332eca7ea81",
    "tid": "9122040d-6c67-4c5b-b112-36a304b66dad",
    "nonce": "123523",
    "aio": "Df2UVXL1ix!lMCWMSOJBcFatzcGfvFGhjKv8q5g0x732dR5MB5BisvGQO7YWByjd8iQDLq!eGbIDakyp5mnOrcdqHeYSnltepQmRp6AIZ8jY",
}

id_token = {**id_token_no_groups, "groups": ["myidtokengroup"]}

id_token_duplicate_group = {**id_token_no_groups, "groups": ["mygroup", "myidtokengroup"]}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "backend_has_instance,user_exists,uid_exists,email_value,expected_calls",
    [
        # Happy path - all parameters valid
        (True, True, True, "user@example.com", {"get_or_create": True, "debug": True, "info": True}),
        # Email as list (SAML case)
        (True, True, True, ["user@example.com", "backup@example.com"], {"get_or_create": True, "debug": True, "info": True}),
        # Empty email
        (True, True, True, "", {"get_or_create": True, "debug": True, "info": True}),
        # Email as non-string (gets normalized to empty)
        (True, True, True, 123, {"get_or_create": True, "debug": True, "info": True}),
        # No backend database_instance attribute
        (False, True, True, "user@example.com", {"warning_backend": True}),
        # Backend database_instance is None
        ("none", True, True, "user@example.com", {"warning_backend": True}),
        # No user in kwargs
        (True, False, True, "user@example.com", {}),
        # No uid in kwargs
        (True, True, False, "user@example.com", {"warning_uid": True}),
    ],
)
@mock.patch("ansible_base.authentication.social_auth.logger")
@mock.patch("ansible_base.authentication.utils.authentication.get_or_create_authenticator_user")
def test_capture_oauth_email_pipeline(mock_get_or_create, mock_logger, backend_has_instance, user_exists, uid_exists, email_value, expected_calls):
    """Test the capture_oauth_email_pipeline function with various scenarios."""

    # Create mock objects
    mock_user = mock.Mock()
    mock_user.username = "testuser"

    if backend_has_instance is True:
        mock_backend = mock.Mock()
        mock_backend.database_instance = mock.Mock()
        mock_backend.database_instance.name = "Test Authenticator"
    elif backend_has_instance == "none":
        # Test case where backend has database_instance attribute but it's None
        mock_backend = mock.Mock()
        mock_backend.database_instance = None
    else:
        # Test case where backend doesn't have database_instance attribute
        mock_backend = mock.Mock(spec=[])  # Backend without database_instance attribute

    # Setup kwargs and details
    kwargs = {}
    if user_exists:
        kwargs['user'] = mock_user
    if uid_exists:
        kwargs['uid'] = "test_uid"
    kwargs['response'] = {"extra": "data"}

    details = {'email': email_value, 'first_name': 'Test', 'last_name': 'User'}

    # Call the function
    capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

    # Verify expected calls
    if expected_calls.get("warning_backend"):
        mock_logger.warning.assert_called_with("No backend or database_instance found in OAuth email pipeline")

    if expected_calls.get("warning_uid"):
        mock_logger.warning.assert_called_with("No uid found in OAuth email pipeline")

    if expected_calls.get("debug"):
        # Normalize email for assertion
        expected_email = email_value
        if isinstance(email_value, list) and email_value:
            expected_email = email_value[0]
        elif not isinstance(email_value, str):
            expected_email = ""

        mock_logger.debug.assert_called_with(f"Capturing OAuth email for user testuser: {expected_email}")

    if expected_calls.get("get_or_create"):
        # Verify get_or_create_authenticator_user was called with correct parameters
        assert mock_get_or_create.called
        call_args = mock_get_or_create.call_args

        # Check uid
        assert call_args[1]['uid'] == 'test_uid'

        # Check normalized email
        expected_email = email_value
        if isinstance(email_value, list) and email_value:
            expected_email = email_value[0]
        elif not isinstance(email_value, str):
            expected_email = ""
        assert call_args[1]['email'] == expected_email

        # Check other parameters
        assert call_args[1]['authenticator'] == mock_backend.database_instance
        assert call_args[1]['user_details'] == details
        assert call_args[1]['extra_data'] == {"extra": "data"}

    if expected_calls.get("info"):
        expected_email = email_value
        if isinstance(email_value, list) and email_value:
            expected_email = email_value[0]
        elif not isinstance(email_value, str):
            expected_email = ""
        mock_logger.info.assert_called_with(f"Stored OAuth email {expected_email} for user testuser from Test Authenticator")

    # If no expected calls, verify nothing was called
    if not expected_calls:
        assert not mock_get_or_create.called


@mock.patch("ansible_base.authentication.social_auth.logger")
@mock.patch("ansible_base.authentication.utils.authentication.get_or_create_authenticator_user")
def test_capture_oauth_email_pipeline_exception_handling(mock_get_or_create, mock_logger):
    """Test exception handling in capture_oauth_email_pipeline."""

    # Setup mocks to raise exception
    mock_get_or_create.side_effect = Exception("Database error")

    mock_user = mock.Mock()
    mock_user.username = "testuser"

    mock_backend = mock.Mock()
    mock_backend.database_instance = mock.Mock()
    mock_backend.database_instance.name = "Test Authenticator"

    kwargs = {'user': mock_user, 'uid': 'test_uid', 'response': {}}
    details = {'email': 'user@example.com'}

    # Call the function
    capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

    # Verify exception was caught and logged
    mock_logger.warning.assert_called_with("Failed to store OAuth email for user testuser: Database error")


@mock.patch("ansible_base.authentication.social_auth.logger")
@mock.patch("ansible_base.authentication.utils.authentication.get_or_create_authenticator_user")
def test_capture_oauth_email_pipeline_edge_cases(mock_get_or_create, mock_logger):
    """Test edge cases for email normalization in capture_oauth_email_pipeline."""

    mock_user = mock.Mock()
    mock_user.username = "testuser"

    mock_backend = mock.Mock()
    mock_backend.database_instance = mock.Mock()
    mock_backend.database_instance.name = "Test Authenticator"

    test_cases = [
        # Empty list
        ([], ""),
        # None value
        (None, ""),
        # List with empty string
        ([""], ""),
        # List with None as first element
        ([None, "backup@example.com"], ""),
        # Multiple valid emails in list
        (["primary@example.com", "backup@example.com"], "primary@example.com"),
    ]

    for email_input, expected_email in test_cases:
        # Reset mocks
        mock_get_or_create.reset_mock()
        mock_logger.reset_mock()

        kwargs = {'user': mock_user, 'uid': 'test_uid', 'response': {}}
        details = {'email': email_input}

        # Call the function
        capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

        # Verify the email was normalized correctly
        call_args = mock_get_or_create.call_args
        assert call_args[1]['email'] == expected_email, f"Failed for input {email_input}, got {call_args[1]['email']}, expected {expected_email}"


@pytest.mark.parametrize(
    "groups_claim,user_info_groups,id_token,expected_groups",
    [
        (None, ["mygroup"], {}, ["mygroup"]),
        ("groups", ["mygroup"], {}, ["mygroup"]),
        (None, None, {}, []),
        ("groups", None, {}, []),
        # Check extracting groups claim from id_token
        ("groups", None, id_token, ["myidtokengroup"]),
        # Test extracting groups claim from id_token when groups claim does not exist
        (None, None, id_token, []),
        # Test merging groups from UserInfo and id_token.
        ("groups", ["mygroup"], id_token, ["myidtokengroup", "mygroup"]),
        # Test merging groups from UserInfo and id_token where we have duplicate groups.
        ("groups", ["mygroup"], id_token_duplicate_group, ["myidtokengroup", "mygroup"]),
        # Test where id_token has no groups-claim.
        ("groups", ["mygroup"], id_token_no_groups, ["mygroup"]),
    ],
)
@mock.patch("ansible_base.authentication.utils.claims.update_user_claims")
def test_create_user_claims_pipeline(mock_update_user_claims, groups_claim, user_info_groups, id_token, expected_groups):
    '''
    We are testing to see if extracting groups from a claim is working correctly
    '''

    class MockBackend(SocialAuthMixin):
        database_instance = None

        def __init__(self, groups_claim=None, id_token=None):
            if groups_claim is not None:
                self.groups_claim = groups_claim
            if id_token is not None:
                self.id_token = id_token

        def get_user_groups(self, extra_groups=[]):
            return extra_groups

    backend = MockBackend(groups_claim=groups_claim, id_token=id_token)

    rData = {}
    if user_info_groups is not None:
        rData[backend.groups_claim] = user_info_groups

    user = {
        'auth_time': "2024-11-07T05:19:08.224936Z",
        'id_token': id_token,
        'refresh_token': None,
        'id': "ccd2cf13-d927-41ad-cd8c-adb18b2e5f78",
        'access_token': "asdf",
        'token_type': "Bearer",
    }

    create_user_claims_pipeline(backend=backend, response=rData, user=user)

    assert mock_update_user_claims.called
    call_args = mock_update_user_claims.call_args

    assert call_args[0][0] == user
    assert call_args[0][1] is None
    assert call_args[0][2].sort() == expected_groups.sort()
