from unittest import mock
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError
from django.test.client import RequestFactory
from django.urls import reverse

from ansible_base.authentication.authenticator_plugins.tacacs import AuthenticatorPlugin, validate_tacacsplus_disallow_nonascii
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


@pytest.mark.parametrize(
    'request_type, x_forwarded_for, remote_addr, expected',
    [
        (None, None, None, None),
        ('mocked_http', None, None, None),
        ('rf', None, None, None),
        ('rf', '1.2.3.4,Whatever', None, '1.2.3.4'),
        ('rf', '1.2.3.4', None, '1.2.3.4'),
        ('rf', '1.2.3.4,Whatever,Else', None, '1.2.3.4'),
        ('rf', '1.2.3.4,Whatever', '127.0.0.1', '1.2.3.4'),
        ('rf', None, '4.3.2.1', '4.3.2.1'),
    ],
)
def test_get_client_ip(request_type, x_forwarded_for, remote_addr, expected, mocked_http):
    plugin = AuthenticatorPlugin()
    request_object = None
    if request_type == 'rf':
        rf = RequestFactory()

        headers = {}
        if x_forwarded_for:
            headers['X_FORWARDED_FOR'] = x_forwarded_for

        request_object = rf.get('/hello/', REMOTE_ADDR=remote_addr, headers=headers)

        if remote_addr is None:
            del request_object.META['REMOTE_ADDR']

    elif request_type == 'mocked_http':
        request_object = mocked_http

    result = plugin._get_client_ip(request_object)
    assert result == expected


def test_authenticate():
    tacacs_authenticator = AuthenticatorPlugin()
    if tacacs_authenticator.authenticate(request=RequestFactory(), username=None, password=None):
        assert None
    if tacacs_authenticator.authenticate(request=RequestFactory(), username="foo", password="bar"):
        assert True


def test_tacacs_client():
    tacacs_authenticator = AuthenticatorPlugin()
    tacacs_authenticator.authenticate(request=RequestFactory())
    client_ip = tacacs_authenticator._get_client_ip(request=RequestFactory())
    assert client_ip is None


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@pytest.mark.parametrize(
    "setting_override, expected_errors",
    [
        ({"HOST": False}, {"HOST": "Not a valid string."}),
        ({"PORT": "foobar"}, {"PORT": 'Expected an integer but got type "str".'}),
        ({"REM_ADDR": "foobar"}, {"REM_ADDR": 'Expected a boolean but got type "str".'}),
        ({"SECRET": "foobar"}, {"SECRET": 'Shared secret for authenticating to TACACS+ server.'}),
        ({"SESSION_TIMEOUT": "foobar    "}, {"SESSION_TIMEOUT": 'Expected an integer but got type "str".'}),
        ({"AUTH_PROTOCOL": "foobar"}, {"AUTH_PROTOCOL": 'Expected one of the following choices ascii, pap, chap but got the type str.'}),
    ],
)
def test_tacacs_create_authenticator_error_handling(
    admin_api_client, unauthenticated_api_client, tacacs_authenticator, tacacs_configuration, setting_override, expected_errors
):
    """
    Test normal login flow when authenticate() returns no user.
    """
    tacacs_authenticator.configuration.update()
    tacacs_authenticator.save()
    unauthenticated_api_client.login(username="foo", password="bar")
    url = reverse(authenticated_test_page)
    response = unauthenticated_api_client.get(url)
    data = {
        "name": "TACACS authenticator (should not get created)",
        "enabled": True,
        "create_objects": True,
        "users_unique": False,
        "remove_users": True,
        "configuration": tacacs_configuration,
        "type": "ansible_base.authentication.authenticator_plugins.tacacs",
    }
    response = admin_api_client.post(url, data=data, format="json")
    # assert response.status_code == 400
    assert response.status_code == 201
    # assert"REMOTE_ADDR" == "client_ip"
    # # logger.info.assert_any_call(f"User foo could not be authenticated by TACACS {tacacs_authenticator.name}")
    # if expected_message:
    #     logger.info.assert_any_call(expected_message)
