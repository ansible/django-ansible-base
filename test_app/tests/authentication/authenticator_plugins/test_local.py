from unittest import mock

import pytest
import requests
from django.contrib.auth import get_user_model
from django.test.client import RequestFactory

from ansible_base.authentication.authenticator_plugins.local import AuthenticatorPlugin
from ansible_base.authentication.session import SessionAuthentication
from ansible_base.lib.utils.response import get_relative_url

authenticated_test_page = "authenticator-list"


def mock_get_setting(setting_name):
    """Helper function to mock get_setting with appropriate values for different settings."""
    if setting_name == 'gateway_proxy_url':
        return 'http://controller.example.com'
    elif setting_name == 'GRPC_SERVER_AUTH_SERVICE_TIMEOUT':
        return '30s'  # Return a valid duration format
    else:
        return None


@pytest.fixture
def controller_auth_mocks(user):
    """
    Helper fixture that provides common mocks for controller authentication tests.
    Returns a context manager that sets up the basic mocks needed for controller auth.
    """
    from contextlib import contextmanager

    @contextmanager
    def mock_controller_auth():
        with (
            mock.patch.object(user, 'use_controller_password', True, create=True),
            mock.patch('ansible_base.authentication.authenticator_plugins.local.UserModel._default_manager.get_by_natural_key', return_value=user),
        ):
            yield

    return mock_controller_auth


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
        ('{"anything": "here"}', 400),
    ],
)
def test_local_auth_create_configuration_must_be_empty(admin_api_client, configuration, expected_status_code, shut_up_logging):
    """
    Attempt to create a local authenticator with invalid configuration and test
    that it fails.
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
    # Technically if you try to add anything the validator should report this as an invalid field but lets force the issue
    from django.core.exceptions import ValidationError

    from ansible_base.authentication.authenticator_plugins.local import LocalConfiguration

    config = LocalConfiguration()
    with pytest.raises(ValidationError):
        config.validate({'something', 'here'})


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


@pytest.mark.django_db()
def test_can_authenticate_from_controller_nonexistent_user():
    """
    Test that _can_authenticate_from_controller returns False for a non-existent user.
    """
    plugin = AuthenticatorPlugin()
    result = plugin._can_authenticate_from_controller("nonexistent_user", "password")
    assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_success(user, controller_auth_mocks):
    """
    Test that _can_authenticate_from_controller returns True when all conditions are met.
    """
    plugin = AuthenticatorPlugin()

    # Set user password to encrypted (indicating partial migration)
    user.password = "$encrypted$"
    user.save()

    # Use fixture for common mocks and add specific controller user response
    with controller_auth_mocks(), mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "", "password": "$encrypted$"}):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is True


@pytest.mark.django_db()
def test_can_authenticate_from_controller_no_controller_user(user):
    """
    Test that _can_authenticate_from_controller returns False when controller user not found.
    """
    plugin = AuthenticatorPlugin()

    # Mock the controller user response to return None
    with mock.patch.object(plugin, '_get_controller_user', return_value=None):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_invalid_format(user):
    """
    Test that _can_authenticate_from_controller returns False when controller user format is invalid.
    """
    plugin = AuthenticatorPlugin()

    # Mock the controller user response to return invalid format (False)
    with mock.patch.object(plugin, '_get_controller_user', return_value=False):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_missing_ldap_dn_with_encrypted_password(user):
    """
    Test that _can_authenticate_from_controller returns False when ldap_dn is missing and password is encrypted.
    """
    plugin = AuthenticatorPlugin()

    # Set user password to encrypted (indicating partial migration)
    user.password = "$encrypted$"
    user.save()

    # Mock the controller user response without ldap_dn
    with mock.patch.object(plugin, '_get_controller_user', return_value={"username": "testuser"}):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_non_local_user_with_encrypted_password(user):
    """
    Test that _can_authenticate_from_controller returns False when user is not local and password is encrypted.
    """
    plugin = AuthenticatorPlugin()

    # Set user password to encrypted (indicating partial migration)
    user.password = "$encrypted$"
    user.save()

    # Mock the controller user response with non-empty ldap_dn
    with mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "cn=testuser,ou=users,dc=example,dc=com"}):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_non_local_user_with_regular_password(user):
    """
    Test that _can_authenticate_from_controller returns False when user is not local (has ldap_dn).
    """
    plugin = AuthenticatorPlugin()

    # Set user password to regular password (not encrypted)
    user.set_password("regular_password")
    user.save()

    # Mock the controller user response with non-empty ldap_dn (LDAP user)
    with mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "cn=testuser,ou=users,dc=example,dc=com", "password": "regular_password"}):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_get_controller_user_success(user):
    """
    Test that _get_controller_user returns user data when successful.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 1, "results": [{"ldap_dn": ""}]}
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")
            assert result == {"ldap_dn": ""}


@pytest.mark.django_db()
def test_get_controller_user_no_gateway_proxy_url(user):
    """
    Test that _get_controller_user returns None when gateway_proxy_url is not set.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', return_value=None):
        result = plugin._get_controller_user(user.username, "password")
        assert result is None


@pytest.mark.django_db()
def test_get_controller_user_http_error(user):
    """
    Test that _get_controller_user returns None when HTTP error occurs.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.HTTPError("HTTP Error")

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


@pytest.mark.django_db()
def test_get_controller_user_invalid_count(user):
    """
    Test that _get_controller_user returns None when count is invalid.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 0}  # Invalid count
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


@pytest.mark.django_db()
def test_get_controller_user_empty_results(user):
    """
    Test that _get_controller_user returns None when results are empty.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 1, "results": []}
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


def test_authenticate_with_controller_validation_success(user, local_authenticator):
    """
    Test that authentication works when controller validation succeeds.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an AuthenticatorUser entry for the user with local authenticator
    AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    plugin = AuthenticatorPlugin(database_instance=local_authenticator)

    # Mock controller authentication to succeed
    with mock.patch.object(plugin, '_can_authenticate_from_controller', return_value=True):
        # Mock the super().authenticate to return None first (simulating initial auth failure)
        # then return the user on the second call (after password update)
        with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate') as mock_auth:
            mock_auth.side_effect = [None, user]  # First call returns None, second returns user

            with mock.patch.object(plugin, 'update_gateway_user') as mock_update:
                request = RequestFactory().get('/api/gateway/v1/login/')
                result = plugin.authenticate(request=request, username=user.username, password="password")

                assert result is not None
                assert result == user
                mock_update.assert_called_once_with(user.username, "password")


def test_authenticate_non_gateway_path_skips_validation(user, local_authenticator):
    """
    Test that controller validation is skipped when request path doesn't start with /api/gateway/v1/login/.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an AuthenticatorUser entry for the user with local authenticator
    AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    plugin = AuthenticatorPlugin(database_instance=local_authenticator)

    # Create a request with different path
    request = RequestFactory().get('/some/other/path/')

    with mock.patch.object(plugin, '_can_authenticate_from_controller', return_value=False) as mock_check:
        with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
            with mock.patch.object(plugin, 'update_gateway_user') as mock_update:
                result = plugin.authenticate(request=request, username=user.username, password="password")

                # _can_authenticate_from_controller is not called because path doesn't match
                mock_check.assert_not_called()
                # But update_gateway_user should not be called because path doesn't match
                mock_update.assert_not_called()
                assert result is None


def test_update_gateway_user(user):
    """
    Test that update_gateway_user correctly updates the user's password.
    """
    plugin = AuthenticatorPlugin()
    original_password = user.password

    plugin.update_gateway_user(user.username, "new_password")

    # Refresh user from database
    user.refresh_from_db()
    assert user.password != original_password
    assert user.check_password("new_password")


def test_authenticate_logs_warning_after_controller_validation(user, local_authenticator, expected_log):
    """
    Test that authenticate logs a warning after successful controller validation.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an AuthenticatorUser entry for the user with local authenticator
    AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    plugin = AuthenticatorPlugin(database_instance=local_authenticator)

    # Mock controller authentication to succeed
    with mock.patch.object(plugin, '_can_authenticate_from_controller', return_value=True):
        # Mock the super().authenticate to return None first, then return the user
        with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate') as mock_auth:
            mock_auth.side_effect = [None, user]  # First call returns None, second returns user

            with mock.patch.object(plugin, 'update_gateway_user') as mock_update:
                with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "User has been validated by controller"):
                    # Create request with gateway login path
                    request = RequestFactory().get('/api/gateway/v1/login/')
                    result = plugin.authenticate(request=request, username=user.username, password="password")

                    assert result is not None
                    assert result == user
                    mock_update.assert_called_once_with(user.username, "password")


# Logging tests for _can_authenticate_from_controller
@pytest.mark.django_db()
def test_can_authenticate_from_controller_logs_warning_for_nonexistent_user(expected_log):
    """
    Test that _can_authenticate_from_controller logs a warning for non-existent users.
    """
    plugin = AuthenticatorPlugin()

    with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "does not exist in the database"):
        result = plugin._can_authenticate_from_controller("nonexistent_user", "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_logs_warning_invalid_format(user, expected_log):
    """
    Test that _can_authenticate_from_controller logs a warning for invalid controller user format.
    """
    plugin = AuthenticatorPlugin()

    # Mock use_controller_password to True to enable controller authentication
    mock_response = mock.Mock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"count": 1, "results": ["invalid_string_not_dict"]}

    with (
        mock.patch.object(user, 'use_controller_password', True, create=True),
        mock.patch('ansible_base.authentication.authenticator_plugins.local.UserModel._default_manager.get_by_natural_key', return_value=user),
        mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting),
        mock.patch('requests.get', return_value=mock_response),
        expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "user was not a dictionary"),
    ):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_logs_warning_not_local_user(user, expected_log):
    """
    Test that _can_authenticate_from_controller logs a warning when user cannot be confirmed as local.
    """
    plugin = AuthenticatorPlugin()

    # Set user password to encrypted (indicating partial migration)
    user.password = "$encrypted$"
    user.save()

    # Mock use_controller_password to True to enable controller authentication
    with (
        mock.patch.object(user, 'use_controller_password', True, create=True),
        mock.patch('ansible_base.authentication.authenticator_plugins.local.UserModel._default_manager.get_by_natural_key', return_value=user),
        mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "cn=user,dc=example,dc=com", "password": "$encrypted$"}),
        expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "is an ldap user and can not be authenticated"),
    ):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_authenticate_logs_fallback_condition_not_met(user, local_authenticator, expected_log):
    """
    Test that authenticate logs when fallback authentication condition is not met.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an AuthenticatorUser entry for the user with local authenticator
    AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    plugin = AuthenticatorPlugin(database_instance=local_authenticator)

    # Mock regular authentication to fail
    with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
        # Mock _can_authenticate_from_controller to return False so condition fails
        with mock.patch.object(plugin, '_can_authenticate_from_controller', return_value=False) as mock_check:
            with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "info", "Fallback authentication condition not met"):
                # Create request with gateway login path but controller auth will fail
                request = RequestFactory().get('/api/gateway/v1/login/')
                result = plugin.authenticate(request=request, username=user.username, password="password")

                # Verify the method was called and returned None
                mock_check.assert_called_once_with(user.username, "password")
                assert result is None


@pytest.mark.django_db()
def test_get_controller_user_logs_warning_for_invalid_count(user, expected_log):
    """
    Test that _get_controller_user logs a warning for invalid count.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 0}
            mock_get.return_value = mock_response

            with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "Unable to authenticate user"):
                result = plugin._get_controller_user(user.username, "password")
                assert result is None


@pytest.mark.django_db()
def test_get_controller_user_logs_warning_for_empty_results(user, expected_log):
    """
    Test that _get_controller_user logs a warning for empty results.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 1, "results": []}
            mock_get.return_value = mock_response

            with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "info", "Invalid or empty results"):
                result = plugin._get_controller_user(user.username, "password")
                assert result is None


# Comprehensive update_gateway_user tests
@pytest.mark.django_db()
def test_update_gateway_user_nonexistent_user():
    """
    Test that update_gateway_user raises exception for non-existent user.
    """
    plugin = AuthenticatorPlugin()
    UserModel = get_user_model()

    with pytest.raises(UserModel.DoesNotExist):
        plugin.update_gateway_user("nonexistent_user", "password")


@pytest.mark.django_db()
def test_update_gateway_user_logs_success(user, expected_log):
    """
    Test that update_gateway_user logs success message.
    """
    plugin = AuthenticatorPlugin()

    with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "info", f"Updated user {user.username} gateway account"):
        plugin.update_gateway_user(user.username, "new_password")

    # Verify changes
    user.refresh_from_db()
    assert user.check_password("new_password")


@pytest.mark.django_db()
def test_update_gateway_user_updates_resource_flag(user):
    """
    Test that update_gateway_user properly updates the user password.
    """
    plugin = AuthenticatorPlugin()

    plugin.update_gateway_user(user.username, "new_password")

    # Verify password was updated
    user.refresh_from_db()
    assert user.check_password("new_password")


# Authentication flow edge cases
@pytest.mark.django_db()
def test_authenticate_regular_auth_success_skips_controller_validation(user, local_authenticator):
    """
    Test that authentication skips controller validation when regular authentication succeeds.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an AuthenticatorUser entry for the user with local authenticator
    AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    plugin = AuthenticatorPlugin(database_instance=local_authenticator)

    with mock.patch.object(plugin, '_can_authenticate_from_controller', return_value=False) as mock_check:
        with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=user):
            with mock.patch.object(plugin, 'update_gateway_user') as mock_update:
                # Create request with gateway login path
                request = RequestFactory().get('/api/gateway/v1/login/')
                result = plugin.authenticate(request=request, username=user.username, password="password")

                # _can_authenticate_from_controller should not be called since regular auth succeeded
                mock_check.assert_not_called()
                # update_gateway_user should not be called since regular auth succeeded
                mock_update.assert_not_called()
                assert result is not None


# Test missing parameters and edge cases in _get_controller_user
@pytest.mark.django_db()
def test_get_controller_user_missing_count_field(user):
    """
    Test that _get_controller_user handles missing count field.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"results": [{"ldap_dn": ""}]}  # Missing count
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


@pytest.mark.django_db()
def test_get_controller_user_non_list_results(user):
    """
    Test that _get_controller_user handles non-list results field.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 1, "results": "not_a_list"}
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


# Test successful authentication flow with all components
@pytest.mark.django_db()
def test_authenticate_successful_controller_validation_full_flow(user, local_authenticator):
    """
    Test complete successful authentication flow with controller validation.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an AuthenticatorUser entry for the user with local authenticator
    AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    plugin = AuthenticatorPlugin(database_instance=local_authenticator)

    # Set user password to encrypted (indicating partial migration)
    user.password = "$encrypted$"
    user.save()

    # Mock use_controller_password to True to enable controller authentication
    with mock.patch.object(user, 'use_controller_password', True, create=True):
        # Mock the database lookup to return our mocked user
        with mock.patch('ansible_base.authentication.authenticator_plugins.local.UserModel._default_manager.get_by_natural_key', return_value=user):
            # Mock all the components for a successful flow
            with (
                mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "", "password": "$encrypted$"}),
                mock.patch('django.contrib.auth.backends.ModelBackend.authenticate') as mock_auth,
                mock.patch.object(plugin, 'update_gateway_user') as mock_update,
            ):
                mock_auth.side_effect = [None, user]  # First call fails, second succeeds after password update

                # Create request with gateway login path
                request = RequestFactory().get('/api/gateway/v1/login/')
                result = plugin.authenticate(request=request, username=user.username, password="password")

                # Verify successful authentication
                assert result is not None
                assert result == user

                # Verify update_gateway_user was called
                mock_update.assert_called_once_with(user.username, "password")


# Test connection and timeout errors
@pytest.mark.django_db()
def test_get_controller_user_connection_error(user):
    """
    Test that _get_controller_user handles connection errors gracefully.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError("Connection failed")

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


@pytest.mark.django_db()
def test_get_controller_user_timeout_error(user):
    """
    Test that _get_controller_user handles timeout errors gracefully.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.Timeout("Request timed out")

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


@pytest.mark.django_db()
def test_get_controller_user_general_request_exception(user):
    """
    Test that _get_controller_user handles general request exceptions gracefully.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_get.side_effect = requests.exceptions.RequestException("General request error")

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


# Test JSON parsing error handling
@pytest.mark.django_db()
def test_get_controller_user_json_decode_error(user):
    """
    Test that _get_controller_user handles JSON decode errors gracefully.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.side_effect = ValueError("Invalid JSON")
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


# Test authentication without request object
@pytest.mark.django_db()
def test_authenticate_without_request_object(user, local_authenticator):
    """
    Test authentication behavior when no request object is provided.
    """
    from ansible_base.authentication.models import AuthenticatorUser

    # Create an AuthenticatorUser entry for the user with local authenticator
    AuthenticatorUser.objects.create(uid=user.username, user=user, provider=local_authenticator)

    plugin = AuthenticatorPlugin(database_instance=local_authenticator)

    with mock.patch.object(plugin, '_can_authenticate_from_controller', return_value=False) as mock_check:
        with mock.patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=None):
            with mock.patch.object(plugin, 'update_gateway_user') as mock_update:
                result = plugin.authenticate(request=None, username=user.username, password="password")

                # _can_authenticate_from_controller should not be called without request
                mock_check.assert_not_called()
                # But update_gateway_user should not be called without request
                mock_update.assert_not_called()
                assert result is None


# Test for enterprise user password check
@pytest.mark.django_db()
def test_can_authenticate_from_controller_enterprise_user(user, expected_log):
    """
    Test that _can_authenticate_from_controller returns False for enterprise users (password != "$encrypted$").
    """
    plugin = AuthenticatorPlugin()

    # Mock use_controller_password to True to enable controller authentication
    with (
        mock.patch.object(user, 'use_controller_password', True, create=True),
        mock.patch('ansible_base.authentication.authenticator_plugins.local.UserModel._default_manager.get_by_natural_key', return_value=user),
        mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "", "password": "regular_password"}),
        expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "is an enterprise user and can not be authenticated"),
    ):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_enterprise_user_missing_password(user, expected_log):
    """
    Test that _can_authenticate_from_controller returns False for enterprise users when password field is missing.
    """
    plugin = AuthenticatorPlugin()

    # Mock use_controller_password to True to enable controller authentication
    with (
        mock.patch.object(user, 'use_controller_password', True, create=True),
        mock.patch('ansible_base.authentication.authenticator_plugins.local.UserModel._default_manager.get_by_natural_key', return_value=user),
        mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "", "username": "testuser"}),
        expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "is an enterprise user and can not be authenticated"),
    ):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


@pytest.mark.django_db()
def test_can_authenticate_from_controller_enterprise_user_none_password(user, expected_log):
    """
    Test that _can_authenticate_from_controller returns False for enterprise users when password is None.
    """
    plugin = AuthenticatorPlugin()

    # Mock use_controller_password to True to enable controller authentication
    with (
        mock.patch.object(user, 'use_controller_password', True, create=True),
        mock.patch('ansible_base.authentication.authenticator_plugins.local.UserModel._default_manager.get_by_natural_key', return_value=user),
        mock.patch.object(plugin, '_get_controller_user', return_value={"ldap_dn": "", "password": None}),
        expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "is an enterprise user and can not be authenticated"),
    ):
        result = plugin._can_authenticate_from_controller(user.username, "password")
        assert result is False


# Test for timeout handling - if not timeout
@pytest.mark.django_db()
def test_get_controller_user_no_timeout_setting(user):
    """
    Test that _get_controller_user uses default timeout when GRPC_SERVER_AUTH_SERVICE_TIMEOUT is not set.
    """
    plugin = AuthenticatorPlugin()

    def mock_get_setting_no_timeout(setting_name):
        if setting_name == 'gateway_proxy_url':
            return 'http://controller.example.com'
        elif setting_name == 'GRPC_SERVER_AUTH_SERVICE_TIMEOUT':
            return None  # No timeout setting
        else:
            return None

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting_no_timeout):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 1, "results": [{"ldap_dn": ""}]}
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")

            # Verify that requests.get was called with the default timeout of 10
            mock_get.assert_called_once_with('http://controller.example.com/api/controller/v2/me/', auth=mock.ANY, timeout=10)  # Default timeout should be 10
            assert result == {"ldap_dn": ""}


@pytest.mark.django_db()
def test_get_controller_user_zero_timeout_setting(user):
    """
    Test that _get_controller_user uses default timeout when GRPC_SERVER_AUTH_SERVICE_TIMEOUT converts to 0.
    """
    plugin = AuthenticatorPlugin()

    def mock_get_setting_zero_timeout(setting_name):
        if setting_name == 'gateway_proxy_url':
            return 'http://controller.example.com'
        elif setting_name == 'GRPC_SERVER_AUTH_SERVICE_TIMEOUT':
            return '0s'  # Zero timeout
        else:
            return None

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting_zero_timeout):
        with mock.patch('requests.get') as mock_get:
            mock_response = mock.Mock()
            mock_response.raise_for_status.return_value = None
            mock_response.json.return_value = {"count": 1, "results": [{"ldap_dn": ""}]}
            mock_get.return_value = mock_response

            result = plugin._get_controller_user(user.username, "password")

            # Verify that requests.get was called with the default timeout of 10 (since 0 is falsy)
            mock_get.assert_called_once_with('http://controller.example.com/api/controller/v2/me/', auth=mock.ANY, timeout=10)  # Default timeout should be 10
            assert result == {"ldap_dn": ""}


@pytest.mark.django_db()
def test_get_controller_user_invalid_timeout_format(user):
    """
    Test that _get_controller_user handles invalid timeout format and raises ValueError.
    """
    plugin = AuthenticatorPlugin()

    def mock_get_setting_invalid_timeout(setting_name):
        if setting_name == 'gateway_proxy_url':
            return 'http://controller.example.com'
        elif setting_name == 'GRPC_SERVER_AUTH_SERVICE_TIMEOUT':
            return 'invalid_format'  # Invalid timeout format
        else:
            return None

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting_invalid_timeout):
        # The ValueError should be raised by _convert_to_seconds, which will be caught in the generic exception handler
        result = plugin._get_controller_user(user.username, "password")
        assert result is None


# Test for generic exception handling
@pytest.mark.django_db()
def test_get_controller_user_generic_exception(user):
    """
    Test that _get_controller_user handles generic exceptions gracefully.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            # Force a generic exception (not HTTP, Connection, Timeout, or JSON related)
            mock_get.side_effect = Exception("Unexpected error")

            result = plugin._get_controller_user(user.username, "password")
            assert result is None


@pytest.mark.django_db()
def test_get_controller_user_generic_exception_from_conversion(user):
    """
    Test that _get_controller_user handles generic exceptions from _convert_to_seconds.
    """
    plugin = AuthenticatorPlugin()

    def mock_get_setting_exception(setting_name):
        if setting_name == 'gateway_proxy_url':
            return 'http://controller.example.com'
        elif setting_name == 'GRPC_SERVER_AUTH_SERVICE_TIMEOUT':
            return 'invalid_format'  # This will cause ValueError in _convert_to_seconds
        else:
            return None

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting_exception):
        result = plugin._get_controller_user(user.username, "password")
        assert result is None


@pytest.mark.django_db()
def test_get_controller_user_generic_exception_during_urljoin(user):
    """
    Test that _get_controller_user handles generic exceptions during URL joining.
    """
    plugin = AuthenticatorPlugin()

    def mock_get_setting_none_url(setting_name):
        if setting_name == 'gateway_proxy_url':
            return None  # This will cause early return
        elif setting_name == 'GRPC_SERVER_AUTH_SERVICE_TIMEOUT':
            return '30s'
        else:
            return None

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting_none_url):
        result = plugin._get_controller_user(user.username, "password")
        assert result is None


@pytest.mark.django_db()
def test_get_controller_user_generic_exception_with_logging(user, expected_log):
    """
    Test that _get_controller_user logs generic exceptions properly.
    """
    plugin = AuthenticatorPlugin()

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting):
        with mock.patch('requests.get') as mock_get:
            # Create a custom exception that will be caught by the generic handler
            class CustomException(Exception):
                pass

            mock_get.side_effect = CustomException("Custom error")

            with expected_log('ansible_base.authentication.authenticator_plugins.local.logger', "warning", "An unexpected error occurred"):
                result = plugin._get_controller_user(user.username, "password")
                assert result is None


@pytest.mark.django_db()
def test_get_controller_user_timeout_conversion_exception_handling(user):
    """
    Test that _get_controller_user handles timeout conversion exceptions correctly.
    """
    plugin = AuthenticatorPlugin()

    def mock_get_setting_bad_timeout(setting_name):
        if setting_name == 'gateway_proxy_url':
            return 'http://controller.example.com'
        elif setting_name == 'GRPC_SERVER_AUTH_SERVICE_TIMEOUT':
            return 'not_a_valid_duration'
        else:
            return None

    with mock.patch('ansible_base.authentication.authenticator_plugins.local.get_setting', side_effect=mock_get_setting_bad_timeout):
        # This should handle the ValueError from _convert_to_seconds in the generic exception handler
        result = plugin._get_controller_user(user.username, "password")
        assert result is None
