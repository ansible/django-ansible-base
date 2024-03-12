from unittest import mock

from django.urls import reverse

from ansible_base.authentication.session import SessionAuthentication

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

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.azuread.AuthenticatorPlugin.authenticate", return_value=None)
def test_azuread_auth_failed(authenticate, unauthenticated_api_client, azuread_authenticator):
    """
    Test that a failed AzureAD authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401
