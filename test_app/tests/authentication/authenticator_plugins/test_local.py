from unittest import mock

import pytest
from django.urls import reverse

from ansible_base.authentication.session import SessionAuthentication

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
def test_local_auth_successful(unauthenticated_api_client, local_authenticator, user):
    """
    Test that a successful local authentication returns a 200 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login(username="user", password="password")

    url = reverse(authenticated_test_page)
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

    url = reverse(authenticated_test_page)
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
    url = reverse("authenticator-list")
    data = {
        "name": "Test local authenticator created via API",
        "configuration": configuration,
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "type": "ansible_base.authentication.authenticator_plugins.local",
    }
    response = admin_api_client.post(url, data=data)
    assert response.status_code == expected_status_code
