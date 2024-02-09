from unittest import mock

from django.urls import reverse

from ansible_base.authentication.session import SessionAuthentication

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.github_team.AuthenticatorPlugin.authenticate")
def test_github_team_auth_successful(authenticate, unauthenticated_api_client, github_team_authenticator, user):
    """
    Test that a successful Github authentication returns a 200 on the /me endpoint.

    Here we mock the Github authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    lres = client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.github_team.AuthenticatorPlugin.authenticate", return_value=None)
def test_github_team_auth_failed(authenticate, unauthenticated_api_client, github_team_authenticator):
    """
    Test that a failed Github authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401
