from unittest import mock

import pytest
from django.urls import reverse

from ansible_base.authentication.session import SessionAuthentication

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.github_org.AuthenticatorPlugin.authenticate")
def test_github_org_auth_successful(authenticate, unauthenticated_api_client, github_organization_authenticator, user):
    """
    Test that a successful Github authentication returns a 200 on the /me endpoint.

    Here we mock the Github authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.github_org.AuthenticatorPlugin.authenticate", return_value=None)
def test_github_org_auth_failed(authenticate, unauthenticated_api_client, github_organization_authenticator):
    """
    Test that a failed Github authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.parametrize(
    "org_map, expected_status_code",
    [
        (
            {
                "Default": {
                    "admins": ["admin@example.com"],
                    "users": True,
                },
                "Org1": {
                    "admins": None,
                    "users": "/^[^@].*?@example\\.com$/",
                },
                "Org2": {
                    "admins": None,
                    "users": ["/^[^@].*?@example\\.com$/"],
                },
            },
            201,
        ),
    ],
)
def test_github_org_mapping(admin_api_client, org_map, expected_status_code, shut_up_logging):
    """
    Attempt to create a local authenticator with invalid configuration and test
    that it fails.
    """
    url = reverse("authenticator-list")
    data = {
        "name": "Test github org authenticator created via API",
        "configuration": {
            "KEY": "123456",
            "SECRET": "123456",
            "NAME": "github org map test",
            "ORGANIZATION_MAP": org_map,
            "ORGANIZATION_TEAM_MAP": {},
        },
        "order": 1,
        "enabled": True,
        "type": "ansible_base.authentication.authenticator_plugins.github_org",
    }
    response = admin_api_client.post(url, data=data, format='json')
    assert response.status_code == expected_status_code, response.json()
