import json
from unittest import mock

import pytest
from django.core.exceptions import ValidationError
from jwt.exceptions import PyJWTError
from social_core.backends.open_id_connect import OpenIdConnectAuth

from ansible_base.authentication.authenticator_plugins.oidc import AuthenticatorPlugin, OpenIdConnectConfiguration
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


@mock.patch("social_core.backends.base.BaseAuth.setting")
@mock.patch("jwt.decode")
@mock.patch("social_core.backends.base.BaseAuth.request")
def test_user_data(mockedrequest, mockeddecode, mocksetting):
    class MockResponse:
        def encrypted(self, isEncrypted):
            self.headers = {"Content-Type": "application/jwt"} if isEncrypted else {"Content-Type": "application/json"}

        def json(self):
            return json.dumps({"key": "value"})

    # Mock the setting to return appropriate values
    def mock_setting(key, default=None):
        if key == "JWT_ALGORITHMS":
            return ["RS256"]  # Return a valid algorithm list
        return "VALUE"

    mocksetting.side_effect = mock_setting

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
    data = ap.user_data("token")

    # The algorithms should be the mocked value
    mockeddecode.assert_called_once_with('token', key='-----BEGIN PUBLIC KEY-----\nVALUE\n-----END PUBLIC KEY-----', algorithms=['RS256'], audience='VALUE')
    assert "key" in data

    # Decode failure
    mockeddecode.side_effect = PyJWTError()
    assert ap.user_data("token") is None


def test_jwt_algorithm_list_field_validator():
    """Test JWT algorithm list field validator"""
    from ansible_base.authentication.authenticator_plugins.oidc import JWTAlgorithmListFieldValidator

    validator = JWTAlgorithmListFieldValidator()

    # Test valid algorithms
    valid_algorithms = ["RS256", "HS256"]
    try:
        validator(valid_algorithms)
    except ValidationError:
        pytest.fail("ValidationError raised unexpectedly for valid algorithms")

    # Test invalid algorithms
    invalid_algorithms = ["RS256", "INVALID_ALG"]
    with pytest.raises(ValidationError) as exc_info:
        validator(invalid_algorithms)

    assert "INVALID_ALG" in str(exc_info.value)
    assert "RS256" in str(exc_info.value)


def test_openid_connect_configuration():
    """Test OpenIdConnectConfiguration class"""
    from ansible_base.authentication.authenticator_plugins.oidc import OpenIdConnectConfiguration

    config = OpenIdConnectConfiguration()

    # Test that required fields are present
    assert 'OIDC_ENDPOINT' in config.fields
    assert 'VERIFY_SSL' in config.fields
    assert 'KEY' in config.fields
    assert 'SECRET' in config.fields

    # Test that optional fields have correct defaults
    assert config.fields['ID_KEY'].default == "sub"
    assert config.fields['ID_TOKEN_MAX_AGE'].default == 600
    assert config.fields['RESPONSE_TYPE'].default == "code"
    assert config.fields['SCOPE'].default == ["openid", "profile", "email"]
    assert not config.fields['REDIRECT_STATE'].default


def test_authenticator_plugin_properties():
    """Test AuthenticatorPlugin properties and basic methods"""
    ap = AuthenticatorPlugin()

    # Test type and category
    assert ap.type == "open_id_connect"
    assert ap.category == "sso"
    assert ap.configuration_encrypted_fields == ['SECRET']

    # Test configuration class
    assert ap.configuration_class == OpenIdConnectConfiguration


def test_groups_claim_property():
    """Test groups_claim property"""
    ap = AuthenticatorPlugin()

    # Mock the setting method
    with mock.patch.object(ap, 'setting') as mock_setting:
        mock_setting.return_value = "custom_groups"
        assert ap.groups_claim == "custom_groups"
        mock_setting.assert_called_once_with('GROUPS_CLAIM')


def test_get_user_groups():
    """Test get_user_groups method"""
    ap = AuthenticatorPlugin()

    extra_groups = ["group1", "group2"]
    result = ap.get_user_groups(extra_groups)

    assert result == extra_groups


def test_oidc_config():
    """Test oidc_config method"""
    ap = AuthenticatorPlugin()

    # Mock the get_json method
    with mock.patch.object(ap, 'get_json') as mock_get_json:
        mock_get_json.return_value = {"test": "config"}

        # Mock the oidc_endpoint method
        with mock.patch.object(ap, 'oidc_endpoint') as mock_endpoint:
            mock_endpoint.return_value = "https://example.com"

            result = ap.oidc_config()

            assert result == {"test": "config"}
            mock_get_json.assert_called_once_with("https://example.com/.well-known/openid-configuration")


def test_public_key_with_key():
    """Test public_key method when key is provided"""
    ap = AuthenticatorPlugin()

    # Mock the setting method
    with mock.patch.object(ap, 'setting') as mock_setting:
        mock_setting.return_value = "test_key_content"

        result = ap.public_key()

        expected = "-----BEGIN PUBLIC KEY-----\ntest_key_content\n-----END PUBLIC KEY-----"
        assert result == expected


def test_public_key_with_formatted_key():
    """Test public_key method when key is already formatted"""
    ap = AuthenticatorPlugin()

    # Mock the setting method
    with mock.patch.object(ap, 'setting') as mock_setting:
        formatted_key = "-----BEGIN PUBLIC KEY-----\ntest_key_content\n-----END PUBLIC KEY-----"
        mock_setting.return_value = formatted_key

        result = ap.public_key()

        assert result == formatted_key


def test_public_key_no_key():
    """Test public_key method when no key is provided"""
    ap = AuthenticatorPlugin()

    # Mock the setting method
    with mock.patch.object(ap, 'setting') as mock_setting:
        mock_setting.return_value = None

        result = ap.public_key()

        assert result is None


def test_user_data_json_response():
    """Test user_data method with JSON response"""
    ap = AuthenticatorPlugin()

    # Mock database_instance to avoid slug attribute error
    mock_db_instance = mock.MagicMock()
    mock_db_instance.slug = "test_slug"
    ap.database_instance = mock_db_instance

    # Mock the request method
    class MockResponse:
        def __init__(self):
            self.headers = {"Content-Type": "application/json"}

        def json(self):
            return {"user": "data"}

    with mock.patch.object(ap, 'request') as mock_request:
        mock_request.return_value = MockResponse()

        # Mock userinfo_url to avoid calling the actual method
        with mock.patch.object(ap, 'userinfo_url') as mock_userinfo_url:
            mock_userinfo_url.return_value = "https://example.com/userinfo"

            result = ap.user_data("token")

            assert result == {"user": "data"}


def test_user_data_jwt_response_no_public_key():
    """Test user_data method with JWT response but no public key"""
    ap = AuthenticatorPlugin()

    # Mock database_instance to avoid slug attribute error
    mock_db_instance = mock.MagicMock()
    mock_db_instance.slug = "test_slug"
    ap.database_instance = mock_db_instance

    # Mock the request method
    class MockResponse:
        def __init__(self):
            self.headers = {"Content-Type": "application/jwt"}

    with mock.patch.object(ap, 'request') as mock_request:
        mock_request.return_value = MockResponse()

        # Mock userinfo_url to avoid calling the actual method
        with mock.patch.object(ap, 'userinfo_url') as mock_userinfo_url:
            mock_userinfo_url.return_value = "https://example.com/userinfo"

            # Mock public_key to return None
            with mock.patch.object(ap, 'public_key') as mock_pubkey:
                mock_pubkey.return_value = None

                result = ap.user_data("token")

                assert result is None


def test_user_data_jwt_response_with_public_key():
    """Test user_data method with JWT response and public key"""
    ap = AuthenticatorPlugin()

    # Mock the request method
    class MockResponse:
        def __init__(self):
            self.headers = {"Content-Type": "application/jwt"}

    with mock.patch.object(ap, 'request') as mock_request:
        mock_request.return_value = MockResponse()

        # Mock public_key to return a key
        with mock.patch.object(ap, 'public_key') as mock_pubkey:
            mock_pubkey.return_value = "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"

            # Mock the setting method
            with mock.patch.object(ap, 'setting') as mock_setting:
                mock_setting.side_effect = lambda key, default=None: ["RS256"] if key == "JWT_ALGORITHMS" else "test_audience"

                # Mock jwt.decode
                with mock.patch('jwt.decode') as mock_jwt_decode:
                    mock_jwt_decode.return_value = {"decoded": "data"}

                    result = ap.user_data("token")

                    assert result == {"decoded": "data"}


def test_user_data_jwt_response_decode_error():
    """Test user_data method with JWT response but decode error"""
    ap = AuthenticatorPlugin()

    # Mock the request method
    class MockResponse:
        def __init__(self):
            self.headers = {"Content-Type": "application/jwt"}

    with mock.patch.object(ap, 'request') as mock_request:
        mock_request.return_value = MockResponse()

        # Mock public_key to return a key
        with mock.patch.object(ap, 'public_key') as mock_pubkey:
            mock_pubkey.return_value = "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"

            # Mock the setting method
            with mock.patch.object(ap, 'setting') as mock_setting:
                mock_setting.side_effect = lambda key, default=None: ["RS256"] if key == "JWT_ALGORITHMS" else "test_audience"

                # Mock jwt.decode to raise an error
                with mock.patch('jwt.decode') as mock_jwt_decode:
                    mock_jwt_decode.side_effect = PyJWTError("Invalid token")

                    result = ap.user_data("token")

                    assert result is None


def test_get_alternative_uid_different_values():
    """Test get_alternative_uid method when values are different"""
    ap = AuthenticatorPlugin()

    kwargs = {"response": {"preferred_username": "user123"}, "uid": "different_uid"}

    result = ap.get_alternative_uid(**kwargs)

    assert result == "user123"


def test_get_alternative_uid_same_values():
    """Test get_alternative_uid method when values are the same"""
    ap = AuthenticatorPlugin()

    kwargs = {"response": {"preferred_username": "user123"}, "uid": "user123"}

    result = ap.get_alternative_uid(**kwargs)

    assert result is None


def test_get_alternative_uid_missing_preferred_username():
    """Test get_alternative_uid method when preferred_username is missing"""
    ap = AuthenticatorPlugin()

    kwargs = {"response": {}, "uid": "user123"}

    result = ap.get_alternative_uid(**kwargs)

    assert result is None


def test_discover_algorithms_from_config_signing():
    """Test _discover_algorithms_from_config method with signing algorithms"""
    ap = AuthenticatorPlugin()

    config = {"id_token_signing_alg_values_supported": ["RS256", "ES256"]}

    result = ap._discover_algorithms_from_config(config)

    assert result == ["RS256", "ES256"]


def test_discover_algorithms_from_config_encryption():
    """Test _discover_algorithms_from_config method with encryption algorithms"""
    ap = AuthenticatorPlugin()

    config = {"id_token_encryption_alg_values_supported": ["A256GCM", "A128GCM"]}

    result = ap._discover_algorithms_from_config(config)

    assert result == ["A256GCM", "A128GCM"]


def test_discover_algorithms_from_config_userinfo():
    """Test _discover_algorithms_from_config method with userinfo algorithms"""
    ap = AuthenticatorPlugin()

    config = {"userinfo_signing_alg_values_supported": ["HS256", "HS512"]}

    result = ap._discover_algorithms_from_config(config)

    assert result == ["HS256", "HS512"]


def test_discover_algorithms_from_config_no_algorithms():
    """Test _discover_algorithms_from_config method with no algorithms"""
    ap = AuthenticatorPlugin()

    config = {}

    result = ap._discover_algorithms_from_config(config)

    assert result is None


def test_get_jwt_algorithms_with_existing_setting():
    """Test _get_jwt_algorithms method with existing setting"""
    ap = AuthenticatorPlugin()

    existing_setting = ["RS256", "HS256"]

    result = ap._get_jwt_algorithms(existing_setting)

    assert result == ["RS256", "HS256"]
    assert ap.JWT_ALGORITHMS == ["RS256", "HS256"]


def test_get_jwt_algorithms_with_string_setting():
    """Test _get_jwt_algorithms method with string setting (should be converted to list)"""
    ap = AuthenticatorPlugin()

    existing_setting = "RS256"

    result = ap._get_jwt_algorithms(existing_setting)

    assert result == ["RS256"]
    assert ap.JWT_ALGORITHMS == ["RS256"]


def test_get_jwt_algorithms_with_none_setting():
    """Test _get_jwt_algorithms method with None setting (falls back to discovery then defaults)"""
    ap = AuthenticatorPlugin()

    # Mock oidc_config to fail, so it falls back to defaults
    with mock.patch.object(ap, 'oidc_config') as mock_oidc_config:
        mock_oidc_config.side_effect = Exception("Discovery failed")

        # Mock OpenIdConnectAuth.JWT_ALGORITHMS
        with mock.patch("social_core.backends.open_id_connect.OpenIdConnectAuth.JWT_ALGORITHMS", ["RS256"]):
            existing_setting = None

            result = ap._get_jwt_algorithms(existing_setting)

            assert result == ["RS256"]
            assert ap.JWT_ALGORITHMS == ["RS256"]


def test_get_jwt_algorithms_discovery_success():
    """Test _get_jwt_algorithms method with successful discovery"""
    ap = AuthenticatorPlugin()

    # Mock oidc_config to return a config with algorithms
    with mock.patch.object(ap, 'oidc_config') as mock_oidc_config:
        mock_oidc_config.return_value = {"id_token_signing_alg_values_supported": ["RS256", "ES256"]}

        result = ap._get_jwt_algorithms()

        assert result == ["RS256", "ES256"]
        assert ap.JWT_ALGORITHMS == ["RS256", "ES256"]


def test_get_jwt_algorithms_discovery_failure():
    """Test _get_jwt_algorithms method with discovery failure"""
    ap = AuthenticatorPlugin()

    # Mock oidc_config to return a config with no algorithms
    with mock.patch.object(ap, 'oidc_config') as mock_oidc_config:
        mock_oidc_config.return_value = {}

        # Mock OpenIdConnectAuth.JWT_ALGORITHMS
        with mock.patch("social_core.backends.open_id_connect.OpenIdConnectAuth.JWT_ALGORITHMS", ["RS256"]):
            result = ap._get_jwt_algorithms()

            assert result == ["RS256"]
            assert ap.JWT_ALGORITHMS == ["RS256"]


def test_get_jwt_algorithms_discovery_exception():
    """Test _get_jwt_algorithms method with discovery exception"""
    ap = AuthenticatorPlugin()

    # Mock oidc_config to raise an exception
    with mock.patch.object(ap, 'oidc_config') as mock_oidc_config:
        mock_oidc_config.side_effect = Exception("Network error")

        # Mock OpenIdConnectAuth.JWT_ALGORITHMS
        with mock.patch("social_core.backends.open_id_connect.OpenIdConnectAuth.JWT_ALGORITHMS", ["RS256"]):
            result = ap._get_jwt_algorithms()

            assert result == ["RS256"]
            assert ap.JWT_ALGORITHMS == ["RS256"]


def test_extra_data_with_permissions():
    """Test extra_data method with permissions in response"""
    ap = AuthenticatorPlugin()

    # Mock get_setting
    with mock.patch("ansible_base.authentication.authenticator_plugins.oidc.get_setting") as mock_get_setting:
        mock_get_setting.return_value = "is_system_auditor"

        # Mock super().extra_data
        with mock.patch.object(OpenIdConnectAuth, 'extra_data') as mock_super_extra_data:
            mock_super_extra_data.return_value = {"extra": "data"}

            user = mock.MagicMock()
            backend = mock.MagicMock()
            response = {"is_superuser": True, "is_system_auditor": False}

            # Create a proper mock social object with extra_data as a dict
            social_mock = mock.MagicMock()
            social_mock.extra_data = {}

            kwargs = {"social": social_mock}

            result = ap.extra_data(user, backend, response, **kwargs)

            assert result == {"extra": "data"}
            assert kwargs["social"].extra_data["is_superuser"] is True
            assert kwargs["social"].extra_data["is_system_auditor"] is False


def test_extra_data_without_permissions():
    """Test extra_data method without permissions in response"""
    ap = AuthenticatorPlugin()

    # Mock get_setting
    with mock.patch("ansible_base.authentication.authenticator_plugins.oidc.get_setting") as mock_get_setting:
        mock_get_setting.return_value = "is_system_auditor"

        # Mock super().extra_data
        with mock.patch.object(OpenIdConnectAuth, 'extra_data') as mock_super_extra_data:
            mock_super_extra_data.return_value = {"extra": "data"}

            user = mock.MagicMock()
            backend = mock.MagicMock()
            response = {"email": "user@example.com"}

            # Create a proper mock social object with extra_data as a dict
            social_mock = mock.MagicMock()
            social_mock.extra_data = {}

            kwargs = {"social": social_mock}

            result = ap.extra_data(user, backend, response, **kwargs)

            assert result == {"extra": "data"}
            # No permissions should be added to extra_data
            assert "is_superuser" not in kwargs["social"].extra_data
            assert "is_system_auditor" not in kwargs["social"].extra_data
