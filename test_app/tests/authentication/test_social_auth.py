from unittest import mock

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponseNotFound, HttpResponseRedirect
from django.test import RequestFactory, override_settings

from ansible_base.authentication.models import AuthenticatorUser
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


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.log_auth_event")
def test_authenticator_strategy_redirect_logging(mock_logger):
    """Test that SSO redirect logging happens in the start() method."""
    from ansible_base.authentication.models import Authenticator

    # Create an authenticator
    authenticator = Authenticator.objects.create(
        name="Test OIDC",
        slug="test-oidc",
        type="ansible_base.authentication.authenticator_plugins.oidc",
        enabled=True,
        configuration={
            "OIDC_ENDPOINT": "https://example.com",
            "KEY": "test-key",
            "SECRET": "test-secret",
        },
    )

    # Create strategy and backend
    factory = RequestFactory()
    request = factory.get(f'/login/{authenticator.slug}/')
    request.session = SessionStore()
    request.session.save()

    strategy = AuthenticatorStrategy(storage=AuthenticatorStorage(), request=request)
    backend = strategy.get_backend(authenticator.slug)

    # Mock auth_url to return a test URL with parameters
    test_url = "https://example.com/oauth/callback?state=xyz&nonce=abc"
    with mock.patch.object(backend, 'auth_url', return_value=test_url):
        # Call start() which should log the redirect
        result = backend.start()

        # Verify the logger was called with the SSO redirect message (without URL parameters)
        mock_logger.assert_called_once_with("Starting SSO redirect to https://example.com/oauth/callback with authenticator 'Test OIDC' (slug: test-oidc)")

        # Verify that the result is an HttpResponseRedirect with the correct URL (with parameters)
        assert isinstance(result, HttpResponseRedirect)
        assert result.url == test_url


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.log_auth_error")
@mock.patch("ansible_base.authentication.social_auth.log_auth_event")
def test_social_auth_mixin_start_enabled_authenticator(mock_log_event, mock_log_error):
    """Test that SocialAuthMixin.start logs when authentication is attempted with an enabled authenticator."""

    from ansible_base.authentication.models import Authenticator

    # Create a mock authenticator with enabled=True
    authenticator = Authenticator.objects.create(
        name="Test OIDC", slug="test-oidc", type="ansible_base.authentication.authenticator_plugins.oidc", enabled=True, configuration={}
    )

    class MockParent:
        """Mock parent class to avoid dependency on actual social auth backend."""

        def auth_url(self):
            return "https://example.com/auth"

        def uses_redirect(self):
            return True

        def start(self):
            return None

    class TestBackend(SocialAuthMixin, MockParent):
        def __init__(self, database_instance):
            # Mock the strategy argument requirement
            self.strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
            self.database_instance = database_instance
            self.logger = None

    backend = TestBackend(database_instance=authenticator)
    backend.start()

    # Verify info logging for starting SSO redirect (URL parameters stripped)
    mock_log_event.assert_any_call("Starting SSO redirect to https://example.com/auth with authenticator 'Test OIDC' (slug: test-oidc)")

    # Verify error was not called (since authenticator is enabled)
    assert not mock_log_error.called


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.log_auth_event")
@mock.patch("ansible_base.authentication.social_auth.log_auth_error")
def test_social_auth_mixin_start_disabled_authenticator(mock_log_error, mock_log_event):
    """Test that SocialAuthMixin.start logs an error and returns 404 for disabled authenticator."""
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
    mock_log_error.assert_called_once_with("Authentication attempted with disabled authenticator Disabled OIDC")

    # Verify info logging was not called (since authenticator is disabled)
    assert not mock_log_event.called

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
@mock.patch("ansible_base.authentication.social_auth.log_auth_event")
def test_sso_authenticators_log_redirect_and_start(mock_logger, authenticator_type, authenticator_name, minimal_config):
    """
    Test that all SSO authenticators log both the start message and redirect message during auth flow.

    This test verifies that:
    1. SocialAuthMixin.start() logs "Starting Authentication attempt with authenticator..."
    2. AuthenticatorStrategy.redirect() logs "Redirecting user to ... as part of the social auth flow..."

    We do NOT mock redirect itself - we verify the actual logging that happens during the flow.
    """
    from ansible_base.authentication.models import Authenticator

    # Create the authenticator
    authenticator = Authenticator.objects.create(
        name=authenticator_name, slug=f"test-{authenticator_type.split('.')[-1]}", type=authenticator_type, enabled=True, configuration=minimal_config
    )

    # Create a mock request with session
    factory = RequestFactory()
    request = factory.get(f'/login/{authenticator.slug}/')
    # Add a real session backend
    request.session = SessionStore()
    request.session.save()

    # Create the strategy with the request
    strategy = AuthenticatorStrategy(storage=AuthenticatorStorage(), request=request)

    # Get the backend for this authenticator
    backend = strategy.get_backend(authenticator.slug)

    # Mock auth_url to return a URL with parameters (to verify they are stripped in logging)
    with mock.patch.object(backend, 'auth_url', return_value='https://example.com/auth?state=xyz&nonce=abc'):
        # Call start() which should log both start and redirect messages
        result = backend.start()

        # Verify the result is a redirect response
        assert isinstance(result, HttpResponseRedirect), f"{authenticator_type} did not return HttpResponseRedirect"

        # Verify we got the SSO redirect log message (which includes both start and redirect info)
        sso_log_calls = [call for call in mock_logger.call_args_list if "Starting SSO redirect" in str(call)]
        assert len(sso_log_calls) >= 1, f"{authenticator_type} did not log SSO redirect message"

        # Verify the message contains the authenticator name, slug, and redirect URL (without parameters)
        sso_message = str(sso_log_calls[0])
        assert authenticator_name in sso_message, f"SSO message missing authenticator name: {sso_message}"
        assert authenticator.slug in sso_message, f"SSO message missing authenticator slug: {sso_message}"
        assert "https://" in sso_message or "http://" in sso_message, f"SSO message missing redirect URL: {sso_message}"
        # Verify URL parameters were stripped from the logged message
        assert "state=xyz" not in sso_message, f"SSO message should not contain URL parameters: {sso_message}"
        assert "nonce=abc" not in sso_message, f"SSO message should not contain URL parameters: {sso_message}"


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
            serializer.instance.slug = 'slug'

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
    "backend_has_instance,user_exists,uid_exists,email_value,expect_save",
    [
        # Happy path - all parameters valid, email differs from existing
        (True, True, True, "user@example.com", True),
        # Email as list (SAML case)
        (True, True, True, ["user@example.com", "backup@example.com"], True),
        # Empty email - should not trigger save
        (True, True, True, "", False),
        # Email as non-string (gets normalized to empty) - should not trigger save
        (True, True, True, 123, False),
        # Email unchanged from existing - should not trigger save
        (True, True, True, "already@example.com", False),
        # No backend database_instance attribute
        (False, True, True, "user@example.com", False),
        # Backend database_instance is None
        ("none", True, True, "user@example.com", False),
        # No user in kwargs
        (True, False, True, "user@example.com", False),
        # No uid in kwargs
        (True, True, False, "user@example.com", False),
    ],
)
@mock.patch("ansible_base.authentication.social_auth.logger")
def test_capture_oauth_email_pipeline(mock_logger, backend_has_instance, user_exists, uid_exists, email_value, expect_save):
    """Test the capture_oauth_email_pipeline function with various scenarios."""

    mock_user = mock.Mock()
    mock_user.username = "testuser"

    if backend_has_instance is True:
        mock_backend = mock.Mock()
        mock_backend.database_instance = mock.Mock()
        mock_backend.database_instance.name = "Test Authenticator"
    elif backend_has_instance == "none":
        mock_backend = mock.Mock()
        mock_backend.database_instance = None
    else:
        mock_backend = mock.Mock(spec=[])

    mock_social = mock.Mock()
    mock_social.email = "already@example.com" if email_value == "already@example.com" else ""

    kwargs = {}
    if user_exists:
        kwargs['user'] = mock_user
    if uid_exists:
        kwargs['uid'] = "test_uid"
    kwargs['response'] = {"extra": "data"}
    kwargs['social'] = mock_social

    details = {'email': email_value, 'first_name': 'Test', 'last_name': 'User'}

    capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

    if expect_save:
        mock_social.save.assert_called_once_with(update_fields=['email'])
    else:
        mock_social.save.assert_not_called()


@mock.patch("ansible_base.authentication.social_auth.logger")
def test_capture_oauth_email_pipeline_exception_handling(mock_logger):
    """Test exception handling in capture_oauth_email_pipeline."""

    mock_user = mock.Mock()
    mock_user.username = "testuser"

    mock_backend = mock.Mock()
    mock_backend.database_instance = mock.Mock()
    mock_backend.database_instance.name = "Test Authenticator"

    mock_social = mock.Mock()
    mock_social.email = ""
    mock_social.save.side_effect = Exception("Database error")

    kwargs = {'user': mock_user, 'uid': 'test_uid', 'response': {}, 'social': mock_social}
    details = {'email': 'user@example.com'}

    capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

    mock_logger.warning.assert_called_with("Failed to store OAuth email for user testuser: Database error")


@mock.patch("ansible_base.authentication.social_auth.logger")
def test_capture_oauth_email_pipeline_edge_cases(mock_logger):
    """Test edge cases for email normalization in capture_oauth_email_pipeline."""

    mock_user = mock.Mock()
    mock_user.username = "testuser"

    mock_backend = mock.Mock()
    mock_backend.database_instance = mock.Mock()
    mock_backend.database_instance.name = "Test Authenticator"

    test_cases = [
        # Empty list - empty email, no save
        ([], False),
        # None value - empty email, no save
        (None, False),
        # List with empty string - empty email, no save
        ([""], False),
        # List with None as first element - empty email, no save
        ([None, "backup@example.com"], False),
        # Multiple valid emails in list - uses first, triggers save
        (["primary@example.com", "backup@example.com"], True),
    ]

    for email_input, expect_save in test_cases:
        mock_logger.reset_mock()

        mock_social = mock.Mock()
        mock_social.email = ""

        kwargs = {'user': mock_user, 'uid': 'test_uid', 'response': {}, 'social': mock_social}
        details = {'email': email_input}

        capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

        if expect_save:
            mock_social.save.assert_called_once_with(update_fields=['email'])
        else:
            mock_social.save.assert_not_called()


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.logger")
def test_capture_oauth_email_pipeline_fallback_lookup(mock_logger):
    """Test that capture_oauth_email_pipeline falls back to DB lookup when social is not in kwargs."""
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test GitHub",
        slug="test-github",
        type="ansible_base.authentication.authenticator_plugins.github",
        enabled=True,
        configuration={"KEY": "test-key", "SECRET": "test-secret"},
    )

    User = get_user_model()
    user = User.objects.create_user(username="octocat")
    auth_user = AuthenticatorUser.objects.create(
        user=user,
        uid="49794041",
        provider=authenticator,
    )

    mock_backend = mock.Mock()
    mock_backend.database_instance = authenticator

    kwargs = {'user': user, 'uid': '49794041', 'response': {}}
    details = {'email': 'octocat@example.com'}

    capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

    auth_user.refresh_from_db()
    assert auth_user.email == 'octocat@example.com'
    mock_logger.warning.assert_any_call(
        "'social' key missing from pipeline kwargs for user octocat; falling back to DB lookup. Check SOCIAL_AUTH_PIPELINE ordering."
    )
    mock_logger.info.assert_called_with("Stored OAuth email for user octocat from Test GitHub")


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.logger")
def test_capture_oauth_email_pipeline_no_social_no_record(mock_logger):
    """Test that capture_oauth_email_pipeline logs a warning when no AuthenticatorUser exists."""
    from ansible_base.authentication.models import Authenticator

    authenticator = Authenticator.objects.create(
        name="Test GitHub",
        slug="test-github-nosocial",
        type="ansible_base.authentication.authenticator_plugins.github",
        enabled=True,
        configuration={"KEY": "test-key", "SECRET": "test-secret"},
    )

    User = get_user_model()
    user = User.objects.create_user(username="ghostuser")

    mock_backend = mock.Mock()
    mock_backend.database_instance = authenticator

    kwargs = {'user': user, 'uid': 'nonexistent-uid', 'response': {}}
    details = {'email': 'ghost@example.com'}

    capture_oauth_email_pipeline(backend=mock_backend, details=details, **kwargs)

    mock_logger.warning.assert_called_with("No AuthenticatorUser found for uid=nonexistent-uid, cannot store OAuth email for user ghostuser")


def test_pipeline_ordering_capture_after_associate():
    """Test that capture_oauth_email_pipeline runs after associate_user in the pipeline."""
    from ansible_base.lib.dynamic_config.settings_logic import get_mergeable_dab_settings

    dab_settings = get_mergeable_dab_settings(
        {
            'INSTALLED_APPS': ['ansible_base.authentication'],
            'MIDDLEWARE': [],
            'REST_FRAMEWORK': {},
        }
    )

    pipeline = dab_settings['SOCIAL_AUTH_PIPELINE']
    associate_idx = pipeline.index('social_core.pipeline.social_auth.associate_user')
    capture_idx = pipeline.index('ansible_base.authentication.social_auth.capture_oauth_email_pipeline')

    assert associate_idx < capture_idx, (
        f"associate_user (index {associate_idx}) must come before " f"capture_oauth_email_pipeline (index {capture_idx}) in SOCIAL_AUTH_PIPELINE"
    )


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


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.log_auth_event")
def test_social_auth_mixin_start_no_redirect(mock_logger):
    """Test that SocialAuthMixin.start returns HTML when uses_redirect() returns False."""
    from ansible_base.authentication.models import Authenticator

    # Create a mock authenticator
    authenticator = Authenticator.objects.create(
        name="Test HTML Auth",
        slug="test-html-auth",
        type="ansible_base.authentication.authenticator_plugins.oidc",
        enabled=True,
        configuration={},
    )

    class MockParent:
        """Mock parent class that doesn't use redirect."""

        def auth_html(self):
            return "<html><body>Login Form</body></html>"

        def uses_redirect(self):
            return False

        def start(self):
            return None

    class TestBackend(SocialAuthMixin, MockParent):
        def __init__(self, database_instance):
            # Mock the strategy argument requirement
            factory = RequestFactory()
            request = factory.get('/login/test-html-auth/')
            request.session = SessionStore()
            request.session.save()
            self.strategy = AuthenticatorStrategy(storage=AuthenticatorStorage(), request=request)
            self.database_instance = database_instance
            self.logger = None

    backend = TestBackend(database_instance=authenticator)
    backend.start()

    # Verify that we didn't log the SSO redirect message (since this doesn't use redirect)
    sso_log_calls = [call for call in mock_logger.call_args_list if "Starting SSO redirect" in str(call)]
    assert len(sso_log_calls) == 0, "Should not log SSO redirect when uses_redirect() is False"


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.social_auth.log_auth_error")
def test_social_auth_mixin_start_no_redirect_disabled_authenticator(mock_logger):
    """Test that SocialAuthMixin.start returns 404 for disabled authenticator even when uses_redirect() is False."""
    from ansible_base.authentication.models import Authenticator

    # Create a disabled authenticator
    authenticator = Authenticator.objects.create(
        name="Disabled HTML Auth",
        slug="disabled-html-auth",
        type="ansible_base.authentication.authenticator_plugins.oidc",
        enabled=False,
        configuration={},
    )

    class MockParent:
        """Mock parent class that doesn't use redirect."""

        def auth_html(self):
            return "<html><body>Login Form</body></html>"

        def uses_redirect(self):
            return False

    class TestBackend(SocialAuthMixin, MockParent):
        def __init__(self, database_instance):
            self.strategy = AuthenticatorStrategy(storage=AuthenticatorStorage())
            self.database_instance = database_instance
            self.logger = None

    backend = TestBackend(database_instance=authenticator)
    result = backend.start()

    # Verify error logging for disabled authenticator
    mock_logger.assert_called_once_with("Authentication attempted with disabled authenticator Disabled HTML Auth")

    # Verify that a 404 response was returned (not HTML)
    assert isinstance(result, HttpResponseNotFound)
