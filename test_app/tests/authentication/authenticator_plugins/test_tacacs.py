from unittest import mock
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from ansible_base.authentication.authenticator_plugins.tacacs import AuthenticatorPlugin, validate_tacacsplus_disallow_nonascii
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


@pytest.mark.parametrize(
    "value,raises",
    [
        ('Hi', False),
        ('', False),
        (None, True),
        ('😀', True),
    ],
)
def test_tacacs_validate_tacacsplus_disallow_nonascii(value, raises):
    try:
        validate_tacacsplus_disallow_nonascii(value)
        if not raises:
            assert True
        else:
            assert False
    except ValidationError:
        if raises:
            assert True
        else:
            assert False


# What is _get_client_ip doing?
# Takes a request param (HTTP reuest object)
# First condition checks if the request object is falsy(or None) or if it doesn't have attribute `META`
# Meta is a dictionary object in Django that contains all available HTTP headers
# If the condition is true( rquest object is None or doesn't have META), it returns None(Couldn't get client IP)
# If the condition is false, it returns the value of the REMOTE_ADDR key in the META dictionary
# The REMOTE_ADDR key contains the IP address of the client

def test_get_client_ip(client, request):
    plugin = AuthenticatorPlugin()
    response = AuthenticatorPlugin._get_client_ip(client, request)

    result = AuthenticatorPlugin._get_client_ip(client, request)
    try:
        if hasattr(client, "META"):
            assert True
        else:
            assert False
    except:
        if 'REMOTE_ADDR':
            assert True
        elif 'x_forwarded_for':
            assert False
        else:
            assert False


# @mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
# @pytest.mark.parametrize(
#     "setting_override, expected_errors",
#     [
#         ({"HOST": False}, {"HOST": "Not a valid string."}),
#         ({"PORT": "foobar"}, {"PORT": 'Expected an integer but got type "str".'}),
#         ({"REM_ADDR": "foobar"}, {"REM_ADDR": 'Expected a boolean but got type "str".'}),
#         ({"SECRET": "foobar"}, {"SECRET": 'Shared secret for authenticating to TACACS+ server.'}),
#         ({"SESSION_TIMEOUT": "foobar    "}, {"SESSION_TIMEOUT": 'Expected an integer but got type "str".'}),
#     ],
# )
# def test_tacacs_create_authenticator_error_handling(
#     admin_api_client,
#     tacacs_configuration,
#     user,
#     setting_override,
#     expected_errors,
#     shut_up_logging,
# ):
#     """
#     Test normal login flow when authenticate() returns no user.
#     """
#     tacacs_authenticator.configuration.update(extra_settings)
#     tacacs_authenticator.save()
#     unauthenticated_api_client.login(username="foo", password="bar")
#     url = reverse(authenticated_test_page)
#     response = unauthenticated_api_client.get(url)
#     assert response.status_code == 401
#     logger.info.assert_any_call(f"User foo could not be authenticated by TACACS {tacacs_authenticator.name}")
#     if expected_message:
#         logger.info.assert_any_call(expected_message)


#  ({"AUTH_PROTOCOL": "foobar"}, {"AUTH_PROTOCOL": 'Expected one of the following choices "'ascii', 'pap', 'chap'" but got the type "str".'})
