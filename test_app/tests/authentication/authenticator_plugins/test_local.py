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


def test_local_auth_determine_username_returns_different_user(local_authenticator, ldap_authenticator, random_user):
    from ansible_base.authentication.models import AuthenticatorUser

    # Tie the random user to another authenticator, this will force determine_username_from_uid to return something different
    AuthenticatorUser.objects.create(uid=random_user.username, user=random_user, provider=ldap_authenticator)
    plugin = AuthenticatorPlugin(database_instance=local_authenticator)
    assert plugin.authenticate(request=RequestFactory(), username=random_user.username, password='doe') is None
