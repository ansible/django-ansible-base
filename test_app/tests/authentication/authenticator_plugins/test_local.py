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
        ('{}', 201),
        ('{"fallback_authentication": ["some.module.path"]}', 400),
        ('{"anything": "here"}', 400),
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
    from ansible_base.authentication.authenticator_plugins.local import LocalConfiguration

    config = LocalConfiguration()

    # Valid: empty configuration
    result = config.validate({})
    assert result == {}


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
def test_missing_credentials_returns_none(local_authenticator, username, password):
    """Test that missing credentials return None immediately."""
    plugin = AuthenticatorPlugin(database_instance=local_authenticator)
    request = RequestFactory().post('/login')

    result = plugin.authenticate(request, username, password)

    assert result is None
