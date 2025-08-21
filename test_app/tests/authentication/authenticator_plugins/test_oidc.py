import contextlib
import json
from unittest import mock

import pytest
from jwt.exceptions import PyJWTError

from ansible_base.authentication.authenticator_plugins.oidc import AuthenticatorPlugin
from ansible_base.authentication.session import SessionAuthentication
from ansible_base.lib.utils.response import get_fully_qualified_url, get_relative_url

authenticated_test_page = "authenticator-list"


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.oidc.AuthenticatorPlugin.authenticate")
def test_oidc_auth_successful(authenticate, unauthenticated_api_client, oidc_authenticator, user):
    """
    Test that a successful OIDC authentication returns a 200 on the /me endpoint.

    Here we mock the OIDC authentication backend to return a user.
    """
    client = unauthenticated_api_client
    authenticate.return_value = user
    client.login()

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 200


@mock.patch("rest_framework.views.APIView.authentication_classes", [SessionAuthentication])
@mock.patch("ansible_base.authentication.authenticator_plugins.oidc.AuthenticatorPlugin.authenticate", return_value=None)
def test_oidc_auth_failed(authenticate, unauthenticated_api_client, oidc_authenticator):
    """
    Test that a failed OIDC authentication returns a 401 on the /me endpoint.
    """
    client = unauthenticated_api_client
    client.login()

    url = get_relative_url(authenticated_test_page)
    response = client.get(url)
    assert response.status_code == 401


def test_oidc_create_via_api_without_callback_url(admin_api_client, oidc_configuration):
    del oidc_configuration['CALLBACK_URL']

    authenticator_data = {
        "name": "Test OIDC Authenticator",
        "enabled": True,
        "create_objects": True,
        "remove_users": True,
        "type": "ansible_base.authentication.authenticator_plugins.oidc",
        "configuration": oidc_configuration,
    }

    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=authenticator_data, format="json", SERVER_NAME="dab.example.com")
    assert response.status_code == 201, response.data

    slug = response.data["slug"]
    expected_path = get_fully_qualified_url('social:complete', kwargs={'backend': slug})
    assert response.data["configuration"]["CALLBACK_URL"] == f"http://dab.example.com{expected_path}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "endpoint_url, expected_status_code, expected_error",
    [
        (None, 400, {'OIDC_ENDPOINT': ['This field may not be null.']}),
        ('', 400, {'OIDC_ENDPOINT': ['This field may not be blank.']}),
        ('foobar', 400, {'OIDC_ENDPOINT': ['Enter a valid URL.']}),
        ('123456', 400, {'OIDC_ENDPOINT': ['Enter a valid URL.']}),
        ('/////', 400, {'OIDC_ENDPOINT': ['Enter a valid URL.']}),
        ('...', 400, {'OIDC_ENDPOINT': ['Enter a valid URL.']}),
        ('192.168.1.1', 400, {'OIDC_ENDPOINT': ['Enter a valid URL.']}),
        ('0.0.0.0', 400, {'OIDC_ENDPOINT': ['Enter a valid URL.']}),
        ('httpXX://foobar', 400, {'OIDC_ENDPOINT': ['Enter a valid URL.']}),
        ('http://foobar::not::ip::v6', 400, {'OIDC_ENDPOINT': ["Port could not be cast to integer value as ':not::ip::v6'"]}),
        ('http://foobar:ABDC', 400, {'OIDC_ENDPOINT': ["Port could not be cast to integer value as 'ABDC'"]}),
        ('http://foobar', 201, {}),
        ('http://foobar:80', 201, {}),
        ('https://foobar', 201, {}),
        ('https://foobar:443', 201, {}),
        ('http://[::1]', 201, {}),
        ('http://[::1]:80', 201, {}),
        ('http://[::192.9.5.5]/', 201, {}),
        ('http://[::FFFF:129.144.52.38]:80', 201, {}),
    ],
)
def test_oidc_endpoint_url_validation(
    admin_api_client,
    endpoint_url,
    expected_status_code,
    expected_error,
):
    config = {
        "OIDC_ENDPOINT": endpoint_url,
        "VERIFY_SSL": True,
        "KEY": "12345",
        "SECRET": "abcdefg12345",
    }

    data = {
        "name": "OIDC TEST",
        "enabled": True,
        "create_objects": True,
        "remove_users": True,
        "configuration": config,
        "type": "ansible_base.authentication.authenticator_plugins.oidc",
    }

    url = get_relative_url("authenticator-list")
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == expected_status_code
    if expected_error:
        assert response.json() == expected_error
    else:
        assert response.json()['configuration']['OIDC_ENDPOINT'] == endpoint_url


@mock.patch("ansible_base.authentication.authenticator_plugins.oidc.get_setting")
@mock.patch("social_core.backends.oauth.BaseOAuth2.extra_data")
def test_extra_data(mock_super, mock_get_setting):
    """Test that extra_data sets permissions directly on social.extra_data and calls parent."""
    # Setup
    mock_get_setting.return_value = "is_system_auditor"
    mock_super.return_value = {"some_data": "value"}

    ap = AuthenticatorPlugin()

    class SocialUser:
        def __init__(self):
            self.extra_data = {}

    response = {
        "is_superuser": True,
        "is_system_auditor": False,
        "Group": ["mygroup"],
        "other_field": "ignored"
    }
    social = SocialUser()

    # Execute
    result = ap.extra_data(None, None, response=response, social=social)

    # Verify parent method was called (with positional args)
    mock_super.assert_called_once_with(None, None, response, social=social)

    # Verify permissions were set directly on social.extra_data
    assert social.extra_data["is_superuser"] is True
    assert social.extra_data["is_system_auditor"] is False

    # Verify other fields are not set on social.extra_data
    assert "Group" not in social.extra_data
    assert "other_field" not in social.extra_data

    # Verify result is what parent returned
    assert result == {"some_data": "value"}


@mock.patch("ansible_base.authentication.authenticator_plugins.oidc.get_setting")
@mock.patch("social_core.backends.oauth.BaseOAuth2.extra_data")
def test_extra_data_missing_permissions(mock_super, mock_get_setting):
    """Test extra_data when permission fields are missing from response."""
    # Setup
    mock_get_setting.return_value = "is_system_auditor"
    mock_super.return_value = {"some_data": "value"}

    ap = AuthenticatorPlugin()

    class SocialUser:
        def __init__(self):
            self.extra_data = {}

    response = {"other_field": "value"}  # No permission fields
    social = SocialUser()

    # Execute
    ap.extra_data(None, None, response=response, social=social)

    # Verify no permissions were set
    assert "is_superuser" not in social.extra_data
    assert "is_system_auditor" not in social.extra_data


@mock.patch("ansible_base.authentication.authenticator_plugins.oidc.get_setting")
@mock.patch("social_core.backends.oauth.BaseOAuth2.extra_data")
def test_extra_data_custom_auditor_flag(mock_super, mock_get_setting):
    """Test extra_data with custom auditor flag from settings."""
    # Setup
    custom_flag = "custom_auditor_field"
    mock_get_setting.return_value = custom_flag
    mock_super.return_value = {"some_data": "value"}

    ap = AuthenticatorPlugin()

    class SocialUser:
        def __init__(self):
            self.extra_data = {}

    response = {
        "is_superuser": False,
        custom_flag: True,
    }
    social = SocialUser()

    # Execute
    ap.extra_data(None, None, response=response, social=social)

    # Verify get_setting was called
    mock_get_setting.assert_called_once_with('ANSIBLE_BASE_SOCIAL_AUDITOR_FLAG')

    # Verify permissions were set with custom flag
    assert social.extra_data["is_superuser"] is False
    assert social.extra_data[custom_flag] is True


@mock.patch("social_core.backends.base.BaseAuth.setting")
@mock.patch("jwt.decode")
@mock.patch("social_core.backends.base.BaseAuth.request")
def test_user_data(mockedrequest, mockeddecode, mocksetting):
    class MockResponse:
        def encrypted(self, isEncrypted):
            self.headers = {"Content-Type": "application/jwt"} if isEncrypted else {"Content-Type": "application/json"}

        def json(self):
            return json.dumps({"key": "value"})

    mocksetting.return_value = "VALUE"

    ap = AuthenticatorPlugin()

    # No decode
    mr = MockResponse()
    mr.encrypted(False)
    mockedrequest.return_value = mr
    data = ap.user_data("token")

    assert not mockeddecode.called
    assert "key" in data

    # With decode
    mr = MockResponse()
    mr.encrypted(True)
    mockedrequest.return_value = mr
    mockeddecode.return_value = mr.json()
    # Mock _get_jwt_algorithms to return a list as expected
    with mock.patch.object(ap, '_get_jwt_algorithms') as mock_get_algs:
        mock_get_algs.return_value = ['VALUE']
        data = ap.user_data("token")

        mockeddecode.assert_called_once_with(
            'token',
            key='-----BEGIN PUBLIC KEY-----\nVALUE\n-----END PUBLIC KEY-----',
            algorithms=['VALUE'],
            audience='VALUE',
            options={}
        )
        assert "key" in data

        # Decode failure
        mockeddecode.side_effect = PyJWTError()
        assert ap.user_data("token") is None


class TestGetJwtAlgorithms:
    """Test the _get_jwt_algorithms method."""

    @pytest.mark.parametrize(
        "scenario,admin_setting,oidc_config_data,oidc_exception,django_setting,library_default,"
        "expected_result,expected_debug_calls,expected_error_call",
        [
            # Admin setting takes priority
            (
                "admin_setting_provided",
                ["RS256", "HS256"],  # admin_setting
                None,  # oidc_config_data (not used)
                None,  # oidc_exception (not used)
                None,  # django_setting (not used)
                None,  # library_default (not used)
                ["RS256", "HS256"],  # expected_result
                [],  # expected_debug_calls (no debug calls when admin setting exists)
                None  # expected_error_call
            ),
            # OIDC config success
            (
                "oidc_config_success",
                None,  # admin_setting
                {"id_token_encryption_alg_values_supported": ["RS256", "ES256"]},  # oidc_config_data
                None,  # oidc_exception
                None,  # django_setting (not used)
                None,  # library_default (not used)
                ["RS256", "ES256"],  # expected_result
                [
                    "Attempting to get the JWT algorithms from the .well-known/openid-configuration",
                    "JWT algorithms supported by the IDP: ['RS256', 'ES256']"
                ],  # expected_debug_calls
                None  # expected_error_call
            ),
            # OIDC config has no algorithms - falls back to Django settings
            (
                "oidc_no_algorithms_django_fallback",
                None,  # admin_setting
                {"id_token_encryption_alg_values_supported": None},  # oidc_config_data
                None,  # oidc_exception
                ["HS256", "RS256"],  # django_setting
                None,  # library_default (not used)
                ["HS256", "RS256"],  # expected_result
                ["Attempting to get the JWT algorithms from the .well-known/openid-configuration"],  # expected_debug_calls
                "No algorithms found in OIDC config"  # expected_error_call
            ),
            # OIDC config has no algorithms - falls back to library defaults
            (
                "oidc_no_algorithms_library_fallback",
                None,  # admin_setting
                {"id_token_encryption_alg_values_supported": None},  # oidc_config_data
                None,  # oidc_exception
                None,  # django_setting (not available)
                ["ES256"],  # library_default
                ["ES256"],  # expected_result
                ["Attempting to get the JWT algorithms from the .well-known/openid-configuration"],  # expected_debug_calls
                "No algorithms found in OIDC config"  # expected_error_call
            ),
            # OIDC config raises network exception
            (
                "oidc_config_exception",
                None,  # admin_setting
                None,  # oidc_config_data (not used due to exception)
                Exception("Network error"),  # oidc_exception
                ["RS256", "HS256"],  # django_setting
                None,  # library_default (not used)
                ["RS256", "HS256"],  # expected_result
                ["Attempting to get the JWT algorithms from the .well-known/openid-configuration"],  # expected_debug_calls
                "Network error"  # expected_error_call
            ),
        ]
    )
    @mock.patch("ansible_base.authentication.authenticator_plugins.oidc.logger")
    @mock.patch("social_core.backends.base.BaseAuth.setting")
    def test_get_jwt_algorithms_scenarios(
        self, mock_setting, mock_logger, expected_log, scenario, admin_setting, oidc_config_data,
        oidc_exception, django_setting, library_default, expected_result,
        expected_debug_calls, expected_error_call
    ):
        """Test _get_jwt_algorithms method across different scenarios."""
        # Setup
        mock_setting.return_value = admin_setting
        ap = AuthenticatorPlugin()

        # Setup context managers for mocking
        context_managers = []
        # Mock OIDC config if needed
        if admin_setting is None:  # Only mock OIDC config if no admin setting
            oidc_config_mock = mock.patch.object(ap, 'oidc_config')
            context_managers.append(oidc_config_mock)
        # Mock Django settings if specified
        if django_setting is not None:
            django_settings_mock = mock.patch("django.conf.settings.JWT_ALGORITHMS", django_setting, create=True)
            context_managers.append(django_settings_mock)
        # Mock library defaults if specified
        if library_default is not None:
            library_mock = mock.patch("social_core.backends.open_id_connect.OpenIdConnectAuth.JWT_ALGORITHMS", library_default)
            context_managers.append(library_mock)
        # Execute with all context managers and expected logging
        with contextlib.ExitStack() as stack:
            mocks = [stack.enter_context(cm) for cm in context_managers]

            # Configure OIDC config mock if it exists
            if admin_setting is None and len(mocks) > 0:
                oidc_mock = mocks[0]
                if oidc_exception:
                    oidc_mock.side_effect = oidc_exception
                else:
                    oidc_mock.return_value = oidc_config_data

            # Execute with expected logging
            if expected_error_call:
                # Use expected_log for single error call
                with expected_log(
                    'ansible_base.authentication.authenticator_plugins.oidc.logger',
                    'error',
                    expected_error_call
                ):
                    result = ap._get_jwt_algorithms()
            else:
                # Execute without expected_log for error
                result = ap._get_jwt_algorithms()

            # Verify result
            assert result == expected_result

            # Verify admin setting calls
            if admin_setting is not None:
                # The method calls setting() twice - once for the if check, once for the return
                assert mock_setting.call_count == 2
                mock_setting.assert_has_calls([
                    mock.call("JWT_ALGORITHMS"),
                    mock.call("JWT_ALGORITHMS")
                ])
            else:
                mock_setting.assert_called_once_with("JWT_ALGORITHMS")

            # Verify debug calls using mock_logger (for multiple calls)
            if expected_debug_calls:
                for debug_call in expected_debug_calls:
                    mock_logger.debug.assert_any_call(debug_call)


class TestUserDataWithNoneAlgorithm:
    """Test the user_data method with 'none' algorithm support."""

    @pytest.mark.parametrize(
        "scenario,algorithms,public_key,decode_result,decode_exception,expected_result,"
        "expected_jwt_options,expected_info_log,expected_error_log",
        [
            # 'none' algorithm scenario
            (
                "none_algorithm",
                ['none'],  # algorithms
                "test_key",  # public_key
                {"sub": "user123", "email": "test@example.com"},  # decode_result
                None,  # decode_exception
                {"sub": "user123", "email": "test@example.com"},  # expected_result
                {'verify_signature': False},  # expected_jwt_options
                "JWT decryption algorithm is set to ['none'], will proceed but this is insecure",  # expected_info_log
                None  # expected_error_log
            ),
            # Regular algorithm scenario
            (
                "regular_algorithm",
                ['RS256'],  # algorithms
                "test_key",  # public_key
                {"sub": "user123", "email": "test@example.com"},  # decode_result
                None,  # decode_exception
                {"sub": "user123", "email": "test@example.com"},  # expected_result
                {},  # expected_jwt_options
                None,  # expected_info_log
                None  # expected_error_log
            ),
            # JWT decode error scenario
            (
                "jwt_decode_error",
                ['RS256'],  # algorithms
                "test_key",  # public_key
                None,  # decode_result (not used due to exception)
                PyJWTError("Invalid signature"),  # decode_exception
                None,  # expected_result
                {},  # expected_jwt_options
                None,  # expected_info_log
                "Invalid signature"  # expected_error_log
            ),
        ]
    )
    @mock.patch("social_core.backends.base.BaseAuth.setting")
    @mock.patch("jwt.decode")
    @mock.patch("social_core.backends.base.BaseAuth.request")
    def test_user_data_jwt_scenarios(
        self, mock_request, mock_decode, mock_setting, expected_log, scenario,
        algorithms, public_key, decode_result, decode_exception, expected_result,
        expected_jwt_options, expected_info_log, expected_error_log
    ):
        """Test user_data method across different JWT scenarios."""
        # Setup
        mock_setting.side_effect = lambda key, *args: {
            "PUBLIC_KEY": public_key,
            "KEY": "test_audience"
        }.get(key, "default")

        ap = AuthenticatorPlugin()

        # Mock the response with JWT content type
        class MockResponse:
            headers = {"Content-Type": "application/jwt"}

        mock_request.return_value = MockResponse()
        if decode_exception:
            mock_decode.side_effect = decode_exception
        else:
            mock_decode.return_value = decode_result

        # Mock _get_jwt_algorithms
        with mock.patch.object(ap, '_get_jwt_algorithms') as mock_get_algs:
            mock_get_algs.return_value = algorithms

            # Execute with expected logging
            if expected_info_log:
                with expected_log(
                    'ansible_base.authentication.authenticator_plugins.oidc.logger',
                    'info',
                    expected_info_log
                ):
                    result = ap.user_data("test_token")
            elif expected_error_log:
                with expected_log(
                    'ansible_base.authentication.authenticator_plugins.oidc.logger',
                    'error',
                    expected_error_log
                ):
                    result = ap.user_data("test_token")
            else:
                result = ap.user_data("test_token")

            # Verify result
            assert result == expected_result

            # Verify jwt.decode was called with correct parameters
            if public_key:  # Only check decode call if public key exists
                mock_decode.assert_called_once_with(
                    'test_token',
                    key='-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----',
                    algorithms=algorithms,
                    audience='test_audience',
                    options=expected_jwt_options
                )

    @mock.patch("social_core.backends.base.BaseAuth.setting")
    @mock.patch("social_core.backends.base.BaseAuth.request")
    def test_user_data_no_public_key_with_logging(self, mock_request, mock_setting, expected_log):
        """Test user_data when no public key is configured and verify error logging."""
        # Setup
        mock_setting.side_effect = lambda key, *args: {
            "PUBLIC_KEY": None,  # No public key
            "KEY": "test_audience"
        }.get(key, "default")

        ap = AuthenticatorPlugin()

        # Mock the response with JWT content type
        class MockResponse:
            headers = {"Content-Type": "application/jwt"}

        mock_request.return_value = MockResponse()

        # Execute with expected logging
        with expected_log(
            'ansible_base.authentication.authenticator_plugins.oidc.logger',
            'error',
            "OIDC client sent encrypted user info response, but no public key found."
        ):
            result = ap.user_data("test_token")

        # Verify
        assert result is None
