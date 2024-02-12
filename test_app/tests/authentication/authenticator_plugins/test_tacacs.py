from unittest import mock
from unittest.mock import MagicMock

import pytest
from django.urls import reverse

from ansible_base.authentication.authenticator_plugins.tacacs import AuthenticatorPlugin
from ansible_base.authentication.models import Authenticator
from ansible_base.authentication.session import SessionAuthentication

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.tacacs.AuthenticatorPlugin.authenticate")
def test_tacacs_auth_successful(authenticate, unauthenticated_api_client, tacacs_authenticator, user):
    """
    Test that a successful TACACS authentication returns a 200 on the /me endpoint.

    Here we mock the TACACS authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    did_login = client.login()
    assert did_login, "Failed to login"

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.tacacs.AuthenticatorPlugin.authenticate")
def test_tacacs_auth_failure(authenticate, unauthenticated_api_client, tacacs_authenticator):
    """
    Test that a failed tacacs authentication returns a 401 on the /me endpoint.

    Here we mock the tacacs authentication backend to return None.
    """
    client = unauthenticated_api_client
    authenticate.return_value = None
    client.login()

    url = reverse(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


@pytest.mark.django_db
@mock.patch("ansible_base.authentication.authenticator_plugins.tacacs.logger")
def test_AuthenticatorPlugin_authenticate_no_authenticator(logger):
    """
    Test how AuthenticatorPlugin.authenticate handles no authenticator.
    """
    backend = AuthenticatorPlugin(database_instance=None)
    request = MagicMock()
    assert backend.authenticate(request, username="foo", password="bar") is None
    logger.error.assert_called_with("AuthenticatorPlugin was missing an authenticator")


# @mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
# @pytest.mark.parametrize(
#     "setting_override, expected_errors, argvalues",
#     [
#         ({"HOST": False}, {"HOST": "Not a valid string."}),
#         ({"PORT": "foobar"}, {"PORT": 'Expected an integer but got type "str".'}),
#         ({"AUTH_PROTOCOL": "foobar"}, {"AUTH_PROTOCOL": 'Expected one of the following choices "'ascii', 'pap', 'chap'" but got the type "str".'}),
#         ({"REM_ADDR": "foobar"}, {"REM_ADDR": 'Expected a boolean but got type "str".'}),
#         ({"SECRET": "foobar"}, {"SECRET": 'Shared secret for authenticating to TACACS+ server.'}),
#         ({"SESSION_TIMEOUT": "foobar    "}, {"SESSION_TIMEOUT": 'Expected an integer but got type "str".'}),
#     ]

# )

# def test_tacacsplus_settings(authenticate, unauthenticated_api_client, tacacs_authenticator):
#     client = unauthenticated_api_client
#     url = reverse('api:setting_singleton_detail', kwargs={'name': 'tacacsplus'})
#     response = client.get(url, user=admin, expect=200)
#     put(url, user=admin, data=response.data, expect=200)
#     patch(url, user=admin, data={'SECRET': 'mysecret'}, expect=200)
#     patch(url, user=admin, data={'SECRET': ''}, expect=200)
#     patch(url, user=admin, data={'HOST': 'localhost'}, expect=400)
#     patch(url, user=admin, data={'SECRET': 'mysecret'}, expect=200)
#     patch(url, user=admin, data={'HOST': 'localhost'}, expect=200)
#     patch(url, user=admin, data={'HOST': '', 'SECRET': ''}, expect=200)
#     patch(url, user=admin, data={'HOST': 'localhost', 'SECRET': ''}, expect=400)
#     patch(url, user=admin, data={'HOST': 'localhost', 'SECRET': 'mysecret'}, expect=200)
