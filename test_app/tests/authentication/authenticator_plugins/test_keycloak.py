import json
from types import SimpleNamespace
from unittest import mock

from django.urls import reverse

from ansible_base.authentication.authenticator_plugins.keycloak import AuthenticatorPlugin
from ansible_base.authentication.session import SessionAuthentication

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.keycloak.AuthenticatorPlugin.authenticate")
def test_keycloak_auth_successful(authenticate, unauthenticated_api_client, keycloak_authenticator, user):
    """
    Test that a successful keycloak authentication returns a 200 on the /me endpoint.

    Here we mock the keycloak authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    did_login = client.login()
    assert did_login, "Failed to login"

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.keycloak.AuthenticatorPlugin.authenticate")
def test_keycloak_auth_failure(authenticate, unauthenticated_api_client, keycloak_authenticator):
    """
    Test that a failed keycloak authentication returns a 401 on the /me endpoint.

    Here we mock the keycloak authentication backend to return None.
    """
    client = unauthenticated_api_client
    authenticate.return_value = None
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


@mock.patch("social_core.backends.oauth.BaseOAuth2.extra_data")
def test_extra_data(mockedsuper):
    ap = AuthenticatorPlugin()

    class SocialUser:
        def __init__(self):
            self.extra_data = {}

    rDict = {}
    rDict["is_superuser"] = "True"
    rDict["Group"] = ["mygroup"]
    social = SocialUser()
    ap.extra_data(None, None, response=rDict, social=social)
    assert mockedsuper.called
    assert "is_superuser" in social.extra_data
