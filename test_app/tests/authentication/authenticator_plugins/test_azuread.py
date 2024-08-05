from unittest import mock

import pytest
from django.test import override_settings

from ansible_base.authentication.session import SessionAuthentication
from ansible_base.lib.utils.response import get_fully_qualified_url, get_relative_url

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.azuread.AuthenticatorPlugin.authenticate")
def test_azuread_auth_successful(authenticate, unauthenticated_api_client, azuread_authenticator, user):
    """
    Test that a successful AzureADauthentication returns a 200 on the /me endpoint.

    Here we mock the AzureAD authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize(
    "key, secret, expected_status_code, expected_error",
    [
        (None, None, 400, {'KEY': ['This field may not be null.']}),
        ('', None, 400, {'KEY': ['This field may not be blank.']}),
        ('testaz', '', 400, {'SECRET': ['This field may not be blank.']}),
        ('testaz', None, 201, {}),
        ('testaz', "testaz_secret", 201, {}),
    ],
)
def test_azuread_callback_url_validation(
    admin_api_client,
    key,
    secret,
    expected_status_code,
    expected_error,
):
    config = {"KEY": key, "SECRET": secret}

    data = {
        "name": "AZUREAD TEST",
        "enabled": True,
        "create_objects": True,
        "remove_users": True,
        "configuration": config,
        "type": "ansible_base.authentication.authenticator_plugins.azuread",
    }

    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == expected_status_code
    if expected_error:
        assert response.json() == expected_error
    else:
        slug = response.data["slug"]
        with override_settings(FRONT_END_URL='http://testserver/'):
            expected_path = get_fully_qualified_url('social:complete', kwargs={'backend': slug})
            assert response.json()['configuration']['CALLBACK_URL'] == expected_path


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.azuread.AuthenticatorPlugin.authenticate", return_value=None)
def test_azuread_auth_failed(authenticate, unauthenticated_api_client, azuread_authenticator):
    """
    Test that a failed AzureAD authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401
