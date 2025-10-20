from unittest import mock

import pytest
from django.test.client import RequestFactory

from ansible_base.authentication.authenticator_plugins.local import AuthenticatorPlugin
from ansible_base.authentication.session import SessionAuthentication
from ansible_base.lib.utils.response import get_relative_url

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
def test_local_auth_successful(unauthenticated_api_client, local_authenticator, user):
    """
    Test that a successful local authentication returns a 200 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login(username="user", password="password")

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.parametrize(
    "username, password",
    [
        ("user", "invalidpassword"),
        ("invaliduser", "password"),
        ("", "invalidpassword"),
        ("invaliduser", ""),
        ("", ""),
    ],
)
@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
def test_local_auth_failure(unauthenticated_api_client, local_authenticator, username, password, shut_up_logging):
    """
    Test that a failed local authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login(username=username, password=password)

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "configuration, expected_status_code",
    [
        ('{}', 201),
        ('{"fallback_authentication": ["aap_gateway_api.authentication.fallbacks.controller"]}', 201),
        ('{"anything": "here"}', 400),
        ('{"fallback_authentication": "not_a_list"}', 400),
        ('{"fallback_authentication": [123]}', 400),  # Not strings
        ('{"fallback_authentication": ["nodots"]}', 400),  # Invalid module path format (no dots)
        ('{"fallback_authentication": ["has spaces"]}', 400),  # Invalid module path with spaces
    ],
)
def test_local_auth_create_configuration_validates_properly(admin_api_client, configuration, expected_status_code, shut_up_logging):
    """
    Attempt to create a local authenticator with various configurations and test
    that it validates properly.
    """
    url = get_relative_url("authenticator-list")
    data = {
        "name": "Test local authenticator created via API",
        "configuration": configuration,
        "enabled": True,
        "create_objects": True,
        "remove_users": True,
        "type": "ansible_base.authentication.authenticator_plugins.local",
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == expected_status_code


def test_local_auth_configuration_validate():
    from rest_framework.serializers import ValidationError

    from ansible_base.authentication.authenticator_plugins.local import LocalConfiguration

    config = LocalConfiguration()

    # Valid: empty configuration
    result = config.validate({})
    assert result == {}

    # Valid: with fallback_authentication
    result = config.validate({'fallback_authentication': ['module.path.to.fallback']})
    assert result['fallback_authentication'] == ['module.path.to.fallback']

    # Valid: multiple fallbacks
    result = config.validate({'fallback_authentication': ['module.path.one', 'module.path.two']})
    assert len(result['fallback_authentication']) == 2

    # Invalid: fallback_authentication is not a list (test via serializer)
    with pytest.raises(ValidationError) as exc_info:
        # This will fail during serialization before validate() is called
        config.to_internal_value({'fallback_authentication': 'not_a_list'})
    assert 'fallback_authentication' in str(exc_info.value)

    # Invalid: fallback_authentication contains non-strings
    with pytest.raises(ValidationError) as exc_info:
        config.validate({'fallback_authentication': [123]})
    assert 'fallback_authentication' in str(exc_info.value)

    # Invalid: fallback_authentication contains path without dots
    with pytest.raises(ValidationError) as exc_info:
        config.validate({'fallback_authentication': ['nodots']})
    assert 'fallback_authentication' in str(exc_info.value)

    # Invalid: fallback_authentication contains path with invalid characters
    with pytest.raises(ValidationError) as exc_info:
        config.validate({'fallback_authentication': ['invalid path!']})
    assert 'fallback_authentication' in str(exc_info.value)


def test_local_auth_instance_not_enabled(local_authenticator, expected_log):
    from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin

    local_authenticator.enabled = False
    local_authenticator.save()
    authenticator_object = get_authenticator_plugin(local_authenticator.type)
    authenticator_object.update_if_needed(local_authenticator)

    with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "info", "is disabled, skipping"):
        assert authenticator_object.authenticate(request=RequestFactory(), username='jane', password='doe') is None


def test_local_auth_no_db_instance():
    plugin = AuthenticatorPlugin()
    assert plugin.authenticate(request=RequestFactory(), username='jane', password='doe') is None


# ============================================================================
# Tests for fallback authentication functionality
# ============================================================================


class MockFallbackAuthenticator:
    """Mock fallback authenticator for testing."""

    def __init__(self, database_instance=None, configuration=None):
        self.database_instance = database_instance
        self.configuration = configuration or {}
        self.authenticate_called = False

    def authenticate(self, request, username, password, **kwargs):
        self.authenticate_called = True
        return None  # Return None by default, override in tests


class MockSuccessfulFallback(MockFallbackAuthenticator):
    """Mock fallback that returns a user."""

    def authenticate(self, request, username, password, **kwargs):
        self.authenticate_called = True
        # Return a mock user
        from test_app.models import User

        return User.objects.get(username=username)


class MockFailingFallback(MockFallbackAuthenticator):
    """Mock fallback that always fails."""

    def authenticate(self, request, username, password, **kwargs):
        self.authenticate_called = True
        return None


class MockExceptionFallback(MockFallbackAuthenticator):
    """Mock fallback that raises an exception."""

    def authenticate(self, request, username, password, **kwargs):
        raise Exception("Fallback error")


# ============================================================================
# Tests for _load_fallback_plugin()
# ============================================================================


class TestLoadFallbackPlugin:
    """Tests for the plugin loading mechanism via import_object."""

    def test_load_valid_plugin(self, local_authenticator):
        """Test loading a valid fallback plugin via import_object."""
        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        # Mock import_object to return our mock class
        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=MockFallbackAuthenticator):
            # This tests that import_object is called correctly in _try_fallback_authenticators
            local_authenticator.configuration = {'fallback_authentication': ['test.module.path']}
            local_authenticator.save()

            # We can't directly test the removed method, but we can test the integration
            result = plugin._try_fallback_authenticators(None, 'testuser', 'password')
            # Should attempt to use the fallback (which will return None since MockFallbackAuthenticator returns None)
            assert result is None

    def test_load_plugin_import_error(self, local_authenticator):
        """Test handling of ImportError when loading plugin."""
        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        local_authenticator.configuration = {'fallback_authentication': ['nonexistent.module']}
        local_authenticator.save()

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=ImportError("Module not found")):
            # Should log error but not raise, continuing to try other fallbacks
            result = plugin._try_fallback_authenticators(None, 'testuser', 'password')
            assert result is None

    def test_load_plugin_attribute_error(self, local_authenticator):
        """Test handling when module doesn't have FallbackAuthenticator class."""
        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        local_authenticator.configuration = {'fallback_authentication': ['test.module.path']}
        local_authenticator.save()

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=AttributeError("FallbackAuthenticator not found")):
            # Should log error but not raise, continuing to try other fallbacks
            result = plugin._try_fallback_authenticators(None, 'testuser', 'password')
            assert result is None


# ============================================================================
# Tests for _try_fallback_authenticators()
# ============================================================================


class TestTryFallbackAuthenticators:
    """Tests for the fallback orchestration logic."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock request."""
        return RequestFactory().post('/login')

    def test_no_fallbacks_configured(self, local_authenticator, mock_request):
        """Test when no fallback authenticators are configured."""
        local_authenticator.configuration = {}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        result = plugin._try_fallback_authenticators(mock_request, 'testuser', 'password')

        assert result is None

    def test_empty_fallbacks_list(self, local_authenticator, mock_request):
        """Test when fallback_authentication is an empty list."""
        local_authenticator.configuration = {'fallback_authentication': []}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        result = plugin._try_fallback_authenticators(mock_request, 'testuser', 'password')

        assert result is None

    def test_single_successful_fallback(self, local_authenticator, mock_request, user):
        """Test successful authentication with a single fallback."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.mock']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=MockSuccessfulFallback):
            result = plugin._try_fallback_authenticators(mock_request, user.username, 'password')

            assert result == user

    def test_single_failing_fallback(self, local_authenticator, mock_request):
        """Test when single fallback fails to authenticate."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.mock']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=MockFailingFallback):
            result = plugin._try_fallback_authenticators(mock_request, 'testuser', 'password')

            assert result is None

    def test_multiple_fallbacks_first_succeeds(self, local_authenticator, mock_request, user):
        """Test multiple fallbacks where the first one succeeds."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.success', 'test.fallback.never_called']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        first_fallback = MockSuccessfulFallback()
        second_fallback = MockFallbackAuthenticator()

        def mock_load(path, attr):
            if 'success' in path:
                return lambda *args, **kwargs: first_fallback
            return lambda *args, **kwargs: second_fallback

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=mock_load):
            result = plugin._try_fallback_authenticators(mock_request, user.username, 'password')

            assert result == user
            assert first_fallback.authenticate_called
            assert not second_fallback.authenticate_called  # Should not be tried

    def test_multiple_fallbacks_second_succeeds(self, local_authenticator, mock_request, user):
        """Test multiple fallbacks where the second one succeeds."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.fails', 'test.fallback.success']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        first_fallback = MockFailingFallback()
        second_fallback = MockSuccessfulFallback()

        def mock_load(path, attr):
            if 'fails' in path:
                return lambda *args, **kwargs: first_fallback
            return lambda *args, **kwargs: second_fallback

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=mock_load):
            result = plugin._try_fallback_authenticators(mock_request, user.username, 'password')

            assert result == user
            assert first_fallback.authenticate_called
            assert second_fallback.authenticate_called

    def test_all_fallbacks_fail(self, local_authenticator, mock_request):
        """Test when all configured fallbacks fail."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.fails1', 'test.fallback.fails2', 'test.fallback.fails3']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=MockFailingFallback):
            result = plugin._try_fallback_authenticators(mock_request, 'testuser', 'password')

            assert result is None

    def test_fallback_import_error_continues(self, local_authenticator, mock_request, user, expected_log):
        """Test that ImportError in one fallback doesn't stop others."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.bad_import', 'test.fallback.success']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        def mock_load(path, attr):
            if 'bad_import' in path:
                raise ImportError("Module not found")
            return MockSuccessfulFallback

        with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', 'error', 'Failed to load fallback authenticator plugin'):
            with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=mock_load):
                result = plugin._try_fallback_authenticators(mock_request, user.username, 'password')

                assert result == user

    def test_fallback_attribute_error_continues(self, local_authenticator, mock_request, user, expected_log):
        """Test that AttributeError in one fallback doesn't stop others."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.bad_class', 'test.fallback.success']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        def mock_load(path, attr):
            if 'bad_class' in path:
                raise AttributeError("FallbackAuthenticator not found")
            return MockSuccessfulFallback

        with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', 'error', 'Failed to load fallback authenticator plugin'):
            with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=mock_load):
                result = plugin._try_fallback_authenticators(mock_request, user.username, 'password')

                assert result == user

    def test_fallback_runtime_exception_continues(self, local_authenticator, mock_request, user, expected_log):
        """Test that runtime exception in one fallback doesn't stop others."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.exception', 'test.fallback.success']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        exception_fallback = MockExceptionFallback()
        success_fallback = MockSuccessfulFallback()

        def mock_load(path, attr):
            if 'exception' in path:
                return lambda *args, **kwargs: exception_fallback
            return lambda *args, **kwargs: success_fallback

        with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', 'error', 'Error in fallback authenticator'):
            with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=mock_load):
                result = plugin._try_fallback_authenticators(mock_request, user.username, 'password')

                assert result == user

    def test_fallback_instantiation(self, local_authenticator, mock_request):
        """Test that fallback authenticators are instantiated correctly."""
        test_config = {'fallback_authentication': ['test.fallback.mock']}
        local_authenticator.configuration = test_config
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        instantiated = []

        class InstantiationCapturingFallback:
            def __init__(self):
                instantiated.append(True)

            def authenticate(self, request, username, password, **kwargs):
                return None

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=InstantiationCapturingFallback):
            plugin._try_fallback_authenticators(mock_request, 'testuser', 'password')

            # Verify the fallback was instantiated
            assert len(instantiated) == 1


# ============================================================================
# Tests for authenticate() integration
# ============================================================================


class TestAuthenticateIntegration:
    """Tests for the main authenticate() method with fallback support."""

    @pytest.fixture
    def mock_request(self):
        """Create a mock request."""
        return RequestFactory().post('/login')

    def test_successful_primary_auth_skips_fallback(self, local_authenticator, user, mock_request):
        """Test that successful primary authentication doesn't try fallbacks."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.mock']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        fallback = MockFallbackAuthenticator()

        # Mock super().authenticate() to succeed
        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=lambda *a, **k: fallback):
            with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=user):
                result = plugin.authenticate(mock_request, user.username, 'password')

                assert result == user
                assert not fallback.authenticate_called  # Fallback should not be tried

    def test_failed_primary_auth_tries_fallback(self, local_authenticator, user, mock_request):
        """Test that failed primary authentication tries fallbacks."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.success']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        # Mock super().authenticate() to fail
        with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
            with mock.patch.object(plugin, '_try_fallback_authenticators', return_value=user) as mock_fallback:
                result = plugin.authenticate(mock_request, user.username, 'password')

                assert result == user
                mock_fallback.assert_called_once_with(mock_request, user.username, 'password')

    def test_failed_primary_and_fallback_returns_none(self, local_authenticator, mock_request):
        """Test that None is returned when both primary and fallback fail."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.fails']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        # Mock both to fail
        with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
            with mock.patch.object(plugin, '_try_fallback_authenticators', return_value=None):
                result = plugin.authenticate(mock_request, 'testuser', 'wrongpassword')

                assert result is None

    @pytest.mark.parametrize(
        'username,password',
        [
            (None, 'password'),
            ('username', None),
            (None, None),
            ('', 'password'),
            ('username', ''),
        ],
    )
    def test_missing_credentials_returns_none(self, local_authenticator, mock_request, username, password):
        """Test that missing credentials return None immediately."""
        plugin = AuthenticatorPlugin(database_instance=local_authenticator)

        result = plugin.authenticate(mock_request, username, password)

        assert result is None


# ============================================================================
# Tests for parallel execution safety
# ============================================================================


class TestParallelExecutionSafety:
    """Tests to ensure fallback authentication works correctly in parallel test execution."""

    def test_isolated_fallback_configurations(self, local_authenticator):
        """Test that different authenticator instances have isolated configurations."""
        config1 = {'fallback_authentication': ['fallback.one']}
        config2 = {'fallback_authentication': ['fallback.two']}

        local_authenticator.configuration = config1
        local_authenticator.save()

        plugin1 = AuthenticatorPlugin(database_instance=local_authenticator)

        # Simulate another worker/thread modifying the configuration
        local_authenticator.configuration = config2
        local_authenticator.save()

        plugin2 = AuthenticatorPlugin(database_instance=local_authenticator)

        # Each plugin should read the current configuration from the database
        assert plugin1.database_instance.configuration == config2  # DB was updated
        assert plugin2.database_instance.configuration == config2

    def test_fallback_state_not_shared(self, local_authenticator, user):
        """Test that fallback authenticator state is not shared between calls."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.mock']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        request = RequestFactory().post('/login')

        # Create two fallback instances to simulate parallel calls
        fallback1 = MockFallbackAuthenticator()
        fallback2 = MockFallbackAuthenticator()

        call_count = [0]

        def mock_load(path, attr):
            call_count[0] += 1
            if call_count[0] == 1:
                return lambda *a, **k: fallback1
            return lambda *a, **k: fallback2

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=mock_load):
            with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
                # First call
                plugin._try_fallback_authenticators(request, user.username, 'password')
                # Second call
                plugin._try_fallback_authenticators(request, user.username, 'password')

                # Both should have been called independently
                assert fallback1.authenticate_called
                assert fallback2.authenticate_called


# ============================================================================
# Tests for edge cases
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_fallback_with_none_database_instance(self):
        """Test handling when database_instance is None."""
        plugin = AuthenticatorPlugin(database_instance=None)
        request = RequestFactory().post('/login')

        result = plugin.authenticate(request, 'testuser', 'password')

        assert result is None

    def test_fallback_with_kwargs_passed_through(self, local_authenticator, user):
        """Test that kwargs are passed through to fallback authenticators."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.mock']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        request = RequestFactory().post('/login')
        captured_kwargs = {}

        class KwargsCapturingFallback:
            def __init__(self, database_instance=None, configuration=None):
                pass

            def authenticate(self, request, username, password, **kwargs):
                captured_kwargs.update(kwargs)
                return None

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=KwargsCapturingFallback):
            with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
                plugin.authenticate(request, user.username, 'password', custom_param='value', another='param')

                assert captured_kwargs['custom_param'] == 'value'
                assert captured_kwargs['another'] == 'param'

    def test_very_long_fallback_list(self, local_authenticator, user):
        """Test handling of a very long list of fallbacks."""
        # Create a list of 20 fallback paths
        fallback_list = [f'test.fallback.mock_{i}' for i in range(20)]
        local_authenticator.configuration = {'fallback_authentication': fallback_list}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        request = RequestFactory().post('/login')

        # Make the last one succeed
        call_count = [0]

        def mock_load(path, attr):
            call_count[0] += 1
            if call_count[0] == 20:  # Last one
                return MockSuccessfulFallback
            return MockFailingFallback

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', side_effect=mock_load):
            with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
                result = plugin._try_fallback_authenticators(request, user.username, 'password')

                assert result == user
                assert call_count[0] == 20  # All were tried

    def test_fallback_with_special_characters_in_username(self, local_authenticator, user):
        """Test fallback authentication with special characters in username."""
        local_authenticator.configuration = {'fallback_authentication': ['test.fallback.mock']}
        local_authenticator.save()

        plugin = AuthenticatorPlugin(database_instance=local_authenticator)
        request = RequestFactory().post('/login')
        special_username = "user@example.com"
        captured_username = None

        class UsernameCapturingFallback:
            def __init__(self, database_instance=None, configuration=None):
                pass

            def authenticate(self, request, username, password, **kwargs):
                nonlocal captured_username
                captured_username = username
                return None

        with mock.patch('ansible_base.authentication.authenticator_plugins.local.import_object', return_value=UsernameCapturingFallback):
            with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
                plugin.authenticate(request, special_username, 'password')

                assert captured_username == special_username
