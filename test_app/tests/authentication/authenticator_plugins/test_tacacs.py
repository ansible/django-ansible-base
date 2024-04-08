from functools import partial
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
def test_tacacs_AuthenticatorPlugin_authenticate_no_authenticator(logger):
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
def test_tacacs_get_client_ip(request_type, x_forwarded_for, remote_addr, expected, mocked_http):
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


@pytest.mark.parametrize(
    "username,password,result",
    [
        (None, None, None),
        ("username", None, None),
        (None, "password", None),
    ],
)
@pytest.mark.django_db
def test_tacacs_authenticate_no_user_pass_combos(username, password, result):
    tacacs_authenticator_plugin = AuthenticatorPlugin()
    assert tacacs_authenticator_plugin.authenticate(request=RequestFactory(), username=username, password=password) is result


def test_tacacs_authenticate_no_database_instance(expected_log):
    expected_log = partial(expected_log, "ansible_base.authentication.authenticator_plugins.tacacs.logger")
    tacacs_authenticator_plugin = AuthenticatorPlugin()

    with expected_log("error", "AuthenticatorPlugin was missing an authenticator"):
        assert tacacs_authenticator_plugin.authenticate(request=RequestFactory(), username='jane', password='doe') is None


@pytest.mark.django_db
def test_tacacs_authenticate_database_instance_disabled(expected_log, tacacs_authenticator):
    from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin

    expected_log = partial(expected_log, "ansible_base.authentication.authenticator_plugins.tacacs.logger")
    tacacs_authenticator.enabled = False
    tacacs_authenticator.save()

    authenticator_object = get_authenticator_plugin(tacacs_authenticator.type)
    authenticator_object.update_if_needed(tacacs_authenticator)

    with expected_log("info", "is disabled, skipping"):
        assert authenticator_object.authenticate(request=RequestFactory(), username='jane', password='doe') is None


@pytest.mark.django_db
def test_tacacs_authenticate_with_client_ip(tacacs_authenticator):
    from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin

    mocked_ip = '4.3.2.1'
    with mock.patch('tacacs_plus.client.TACACSClient.authenticate') as mock_auth:
        authenticator_object = get_authenticator_plugin(tacacs_authenticator.type)
        authenticator_object.update_if_needed(tacacs_authenticator)
        rf = RequestFactory()
        request_object = rf.get('/hello/', REMOTE_ADDR=mocked_ip)
        authenticator_object.authenticate(request=request_object, username='jane', password='doe')
        mock_auth.assert_called_once_with('jane', 'doe', authen_type=1, rem_addr=mocked_ip)


@pytest.mark.django_db
def test_tacacs_authenticate_with_exception(expected_log, tacacs_authenticator):
    from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin

    expected_log = partial(expected_log, "ansible_base.authentication.authenticator_plugins.tacacs.logger")

    with mock.patch('tacacs_plus.client.TACACSClient.authenticate', side_effect=Exception("Failing on purpose")):
        authenticator_object = get_authenticator_plugin(tacacs_authenticator.type)
        authenticator_object.update_if_needed(tacacs_authenticator)
        with expected_log("exception", "TACACS+ Authentication Error"):
            assert authenticator_object.authenticate(request=RequestFactory(), username='jane', password='doe') is None


class AuthenticateResponse:
    def __init__(self, valid):
        self.valid = valid

    def valid(self):
        return self.valid


@pytest.mark.parametrize(
    "password,user_is_valid,pre_create_user,response",
    [
        ("doe", False, False, None),
        ("doe", True, True, True),
        ("doe", True, False, True),
    ],
)
@pytest.mark.django_db
def test_tacacs_authenticate_with_authentication(expected_log, tacacs_authenticator, randname, password, user_is_valid, pre_create_user, response):
    from django.contrib.auth import get_user_model

    from ansible_base.authentication.authenticator_plugins.utils import get_authenticator_plugin

    expected_log = partial(expected_log, "ansible_base.authentication.utils.authentication.logger")

    response_object = AuthenticateResponse(user_is_valid)
    with mock.patch('tacacs_plus.client.TACACSClient.authenticate', return_value=response_object):
        authenticator_object = get_authenticator_plugin(tacacs_authenticator.type)
        authenticator_object.update_if_needed(tacacs_authenticator)
        username = randname("test_user")
        User = get_user_model()

        # Ensure the user is not there
        User.objects.filter(username=username).delete()

        if not user_is_valid:
            # If we don't have a valid user we will never create the user
            logger_create_user_called = False
        elif pre_create_user:
            User.objects.create(username=username)
            # Since we are pre-creating the user we won't get a log
            logger_create_user_called = False
        else:
            # The authenticator will create the user
            logger_create_user_called = True

        with expected_log('info', f'Authenticator {tacacs_authenticator.name} created User', assert_not_called=(not logger_create_user_called)):
            authentication_response = authenticator_object.authenticate(request=RequestFactory(), username=username, password=password)

        if response is None:
            assert authentication_response is response
        else:
            assert authentication_response.username == username


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@pytest.mark.parametrize(
    "setting_override, expected_errors",
    [
        ({"HOST": False}, {"HOST": "Not a valid string."}),
        ({"-HOST": False}, {"HOST": "This field is required."}),
        ({"PORT": "foobar"}, {"PORT": 'A valid integer is required.'}),
        ({"PORT": -1}, {"PORT": 'Ensure this value is greater than or equal to 1.'}),
        ({"PORT": 65536}, {"PORT": 'Ensure this value is less than or equal to 65535.'}),
        ({"-PORT": 65536}, {}),
        ({"REM_ADDR": "foobar"}, {"REM_ADDR": 'Must be a valid boolean.'}),
        ({"SECRET": False}, {"SECRET": 'Not a valid string.'}),
        ({"SECRET": "😀"}, {"SECRET": 'TACACS+ secret does not allow non-ascii characters'}),
        ({"SESSION_TIMEOUT": "foobar    "}, {"SESSION_TIMEOUT": 'A valid integer is required.'}),
        ({"SESSION_TIMEOUT": -1}, {"SESSION_TIMEOUT": 'Ensure this value is greater than or equal to 0.'}),
        ({"AUTH_PROTOCOL": "foobar"}, {"AUTH_PROTOCOL": '"foobar" is not a valid choice.'}),
        # According to:
        # https://www.cisco.com/en/US/docs/switches/datacenter/nexus1000/kvm/config_guide/security/b_Cisco_Nexus_1000V_for_KVM_Security_Configuration_Guide_521SK111_chapter_0100.html
        # there may be limitations on the password including things like no white space, no unicode and max 64 characters.
        # We already handle no unicode but don't enfore the length or whitespace issues.
    ],
)
def test_tacacs_create_authenticator_error_handling(admin_api_client, tacacs_configuration, setting_override, expected_errors):
    """
    Test normal login flow when authenticate() returns no user.
    """
    for key, value in setting_override.items():
        if key.startswith("-"):
            del tacacs_configuration[key[1:]]
        else:
            tacacs_configuration[key] = value

    url = reverse("authenticator-list")
    data = {
        "name": "TACACS authenticator (should not get created)",
        "enabled": True,
        "create_objects": True,
        "remove_users": True,
        "configuration": tacacs_configuration,
        "type": "ansible_base.authentication.authenticator_plugins.tacacs",
    }

    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400 if expected_errors else 201, f"Expected a {400 if expected_errors else 201} but got {response.status_code}"
    if expected_errors:
        for key, value in expected_errors.items():
            assert key in response.data
            if type(response.data[key]) is dict:
                for sub_key in response.data[key]:
                    assert value[sub_key] in response.data[key][sub_key]
            elif type(response.data[key]) is list:
                assert any(value in item for item in response.data[key]), f"Expected error '{value}' in {response.data[key]}"
            else:
                assert value in response.data[key]
