import logging
import re
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import urlparse

import pytest
import requests
from django.test.utils import override_settings
from rest_framework.exceptions import AuthenticationFailed
from typeguard import suppress_type_checks

from ansible_base.jwt_consumer.common.auth import JWTAuthentication, JWTCommonAuth, default_mapped_user_fields


class TestJWTCommonAuth:
    def test_init(self):
        my_auth = JWTCommonAuth()
        assert my_auth.mapped_user_fields == default_mapped_user_fields
        new_user_fields = ["a", "b", "c"]
        my_auth = JWTCommonAuth(new_user_fields)
        assert my_auth.mapped_user_fields == new_user_fields

    def test_parse_jwt_no_header(self, caplog, mocked_http, shut_up_logging):
        with caplog.at_level(logging.INFO):
            my_auth = JWTCommonAuth()
            my_auth.parse_jwt_token(mocked_http.mocked_parse_jwt_token_get_request('without_headers'))
            assert "X-DAB-JW-TOKEN header not set for JWT authentication" in caplog.text

    @pytest.mark.django_db
    @override_settings(INSTALLED_APPS=['django.contrib.auth', 'django.contrib.contenttypes', 'test_app'])
    def test_parse_jwt_happy_path(self, mocked_http, test_encryption_public_key, shut_up_logging, jwt_token):
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            my_auth = JWTCommonAuth()
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
            user, validated_body = my_auth.parse_jwt_token(request)
            assert validated_body == jwt_token.unencrypted_token
            assert user.username == jwt_token.unencrypted_token['sub']
            assert user.first_name == jwt_token.unencrypted_token["first_name"]
            assert user.last_name == jwt_token.unencrypted_token["last_name"]
            assert user.email == jwt_token.unencrypted_token["email"]
            assert user.is_superuser == jwt_token.unencrypted_token["is_superuser"]

    def test_parse_jwt_no_jwt_key(self, mocked_http, caplog):
        my_auth = JWTCommonAuth()
        request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
        with caplog.at_level(logging.INFO):
            user, validated_body = my_auth.parse_jwt_token(request)
            assert user is None
            assert validated_body is None
            assert 'Failed to get the setting ANSIBLE_BASE_JWT_KEY' in caplog.text

    def test_log_exception(self):
        common_auth = JWTCommonAuth()
        message = "This is a test"
        with pytest.raises(AuthenticationFailed, match=message):
            common_auth.log_and_raise(message)

    def test_get_decryption_key_absolute_junk(self):
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match="Unable to determine how to handle  to get key"):
            common_auth.get_decryption_key("")

    def test_get_decryption_key_invalid_scheme(self):
        common_auth = JWTCommonAuth()
        url = "ftp://www.ansible.com"
        with pytest.raises(
            AuthenticationFailed,
            match=f"Unable to determine how to handle {url} to get key",
        ):
            common_auth.get_decryption_key(url)

    @pytest.mark.parametrize(
        "error, exception_class",
        [
            ("The specified file {0} does not exist", FileNotFoundError()),
            ("The specified file {0} is not a file", IsADirectoryError()),
            ("Permission error when reading {0}", PermissionError()),
            ("Failed reading {0}: argh", IOError('argh')),
        ],
    )
    def test_get_decryption_key_file_exceptions(self, error, exception_class, tmp_path_factory):
        common_auth = JWTCommonAuth()
        url = 'file:///gibberish'
        url_parts = urlparse(url)
        with mock.patch("builtins.open", mock.mock_open()) as mock_file:
            mock_file.side_effect = exception_class
            with pytest.raises(AuthenticationFailed, match=error.format(url_parts.path)):
                common_auth.get_decryption_key(url)

    # This would test any method returning junk instead of an RSA key
    def test_get_decryption_key_invalid_input(self):
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match="Returned key does not start and end with BEGIN/END PUBLIC KEY"):
            common_auth.get_decryption_key("absolute_junk")

    def test_get_decryption_key_file_read(self, tmp_path_factory, test_encryption_public_key):
        common_auth = JWTCommonAuth()
        temp_dir = tmp_path_factory.mktemp("ansible_base.jwt_consumer.common.auth")
        temp_file_name = f"{temp_dir}/test.file"
        for cert_data in [test_encryption_public_key, test_encryption_public_key.replace("\n", "")]:
            with open(temp_file_name, "w") as f:
                f.write(cert_data)
            response = common_auth.get_decryption_key(f"file:{temp_file_name}")
            assert response == cert_data

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.ConnectionError))
    def test_get_decryption_key_connection_error(self):
        common_auth = JWTCommonAuth()
        url = "http://dne.cuz.junk.redhat.com"
        with pytest.raises(AuthenticationFailed, match=rf"Failed to connect to {url}.*"):
            common_auth.get_decryption_key(url)

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.Timeout))
    def test_get_decryption_key_url_timeout(self):
        common_auth = JWTCommonAuth()
        url = "http://dne.cuz.junk.redhat.com"
        timeout = 0.1
        with pytest.raises(AuthenticationFailed, match=rf"Timed out after {timeout} secs when connecting to {url}.*"):
            common_auth.get_decryption_key(url, timeout=timeout)

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.RequestException))
    def test_get_decryption_key_url_random_exception(self):
        common_auth = JWTCommonAuth()
        url = "http://dne.cuz.junk.redhat.com"
        with pytest.raises(AuthenticationFailed, match=r"Failed to get JWT decryption key from JWT server: \(RequestException\).*"):
            common_auth.get_decryption_key(url)

    @pytest.mark.parametrize("status_code", ['302', '504'])
    def test_get_decryption_key_url_bad_status_codes(self, status_code, mocked_http):
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            common_auth = JWTCommonAuth()
            with pytest.raises(AuthenticationFailed, match=f"Failed to get 200 response from the issuer: {status_code}"):
                common_auth.get_decryption_key(f"http://someotherurl.com/{status_code}")

    def test_get_decryption_key_url_bad_200(self, mocked_http):
        common_auth = JWTCommonAuth()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            with pytest.raises(AuthenticationFailed, match="Returned key does not start and end with BEGIN/END PUBLIC KEY"):
                common_auth.get_decryption_key("http://someotherurl.com/200_junk")

    def test_get_decryption_key_url_good_200(self, mocked_http, test_encryption_public_key):
        common_auth = JWTCommonAuth()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            try:
                cert = common_auth.get_decryption_key("http://someotherurl.com/200_good")
            except Exception as e:
                assert False, f"Got unexpected exception {e}"
            assert cert == test_encryption_public_key

    @suppress_type_checks
    @pytest.mark.parametrize(
        'user_fields,token,should_save',
        [
            # Everything is the same
            ({'first_name': 'Cindy', 'last_name': 'Lou'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, False),
            # Update because the user has old data
            ({'first_name': 'Cindy', 'last_name': 'Liu'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, True),
            # Update from multiple properties
            ({'first_name': 'Billy', 'last_name': 'Bob'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, True),
            # Extra tokens in the user are irrelevant
            ({'first_name': 'Cindy', 'last_name': 'Lou', 'email': 'test'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, False),
            ({'first_name': 'Billy', 'last_name': 'Bob', 'email': 'test'}, {'first_name': 'Cindy', 'last_name': 'Lou'}, True),
            # New properties in the token
            ({'first_name': 'Cindy', 'last_name': 'Lou'}, {'first_name': 'Cindy', 'last_name': 'Lou', 'email': 'test'}, True),
        ],
    )
    def test_map_user_fields(self, user_fields, token, should_save, caplog, shut_up_logging):
        common_auth = JWTCommonAuth()
        common_auth.map_fields = ['first_name', 'last_name']
        user = mock.Mock(unsername='Bob', **user_fields)
        with caplog.at_level(logging.INFO):
            common_auth.map_user_fields(user, token)
            if should_save:
                assert f"Saving user {user.username}" in caplog.text
                assert user.save.called

    @pytest.mark.parametrize(
        "remove",
        [
            "sub",
            "first_name",
            "last_name",
            "email",
            "is_superuser",
            "is_system_auditor",
            "iss",
            "exp",
            "aud",
            "claims",
        ],
    )
    def test_validate_token_missing_default_items(self, remove, jwt_token, test_encryption_public_key):
        # Remove the element we are testing
        del jwt_token.unencrypted_token[remove]
        # Test the function
        common_auth = JWTCommonAuth()
        with pytest.raises(
            AuthenticationFailed,
            match=f'Failed to decrypt JWT: Token is missing the "{remove}" claim',
        ):
            common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)

    def test_validate_token_expired_token(self, jwt_token, test_encryption_public_key):
        jwt_token.unencrypted_token['exp'] = datetime.now() + timedelta(minutes=-10)
        # Test the function
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match="JWT has expired"):
            common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)

    @pytest.mark.parametrize(
        "item,exception",
        [
            ("iss", "JWT did not come from the correct issuer"),
            ("aud", "JWT did not come for the correct audience"),
        ],
    )
    def test_validate_token_invalid_items(self, item, exception, jwt_token, test_encryption_public_key):
        # Replace the item with 'junk'
        jwt_token.unencrypted_token[item] = "Junk"
        # Encrypt the token
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match=exception):
            common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)

    @pytest.mark.parametrize(
        "token,key,exception_text",
        [
            (None, None, "JWT decoding failed: Invalid token type. Token must be a <class 'bytes'>, check your key and generated token"),
            ("", None, "JWT decoding failed: Not enough segments, check your key and generated token"),
            (None, "", "JWT decoding failed: Invalid token type. Token must be a <class 'bytes'>, check your key and generated token"),
            ("junk", "junk", "JWT decoding failed: Not enough segments, check your key and generated token"),
            ("a.b.c", None, "JWT decoding failed: Invalid header padding, check your key and generated token"),
        ],
    )
    def test_validate_token_with_junk_input(self, token, key, exception_text):
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match=exception_text):
            common_auth.validate_token(token, key)

    def test_validate_token_random_exception(self):
        # Encrypt the token
        common_auth = JWTCommonAuth()
        exception = IOError('blah')
        with mock.patch('jwt.decode') as decode_function:
            decode_function.side_effect = exception
            exception_text = re.escape(f"Unknown error occurred decrypting JWT ({exception.__class__}) {exception}")
            with pytest.raises(AuthenticationFailed, match=exception_text):
                common_auth.validate_token(None, None)

    def test_validate_token_valid_token(self, jwt_token, test_encryption_public_key):
        # Test the function
        common_auth = JWTCommonAuth()
        parsed_token = common_auth.validate_token(jwt_token.encrypt_token(), test_encryption_public_key)
        assert parsed_token == jwt_token.unencrypted_token


class TestJWTAuthentication:
    def test_authenticate(self, jwt_token, django_user_model, mocked_http, test_encryption_public_key):
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            user = django_user_model.objects.create_user(username=jwt_token.unencrypted_token['sub'], password="password")
            jwt_auth = JWTAuthentication()
            jwt_auth.process_user_data(user, jwt_token.unencrypted_token)
            # This double call causes line 140 `if user_needs_save` to return false
            jwt_auth.process_user_data(user, jwt_token.unencrypted_token)
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
            created_user, _ = jwt_auth.authenticate(request)
            assert user == created_user

    def test_authenticate_no_user(self, user):
        with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.parse_jwt_token') as mock_parse:
            mock_parse.return_value = (None, {})
            jwt_auth = JWTAuthentication()
            created_user = jwt_auth.authenticate(mock.MagicMock())
            assert created_user is None

    def test_process_user_data(self):
        with mock.patch("ansible_base.jwt_consumer.common.auth.JWTCommonAuth.map_user_fields") as mock_inspect:
            jwt_auth = JWTAuthentication()
            jwt_auth.process_user_data("a", "b")
            mock_inspect.assert_called_with("a", "b")

    def test_process_permissions(self, caplog, shut_up_logging):
        with caplog.at_level(logging.INFO):
            jwt_auth = JWTAuthentication()
            jwt_auth.process_permissions(None, None, None)
            assert "process_permissions was not overridden for JWTAuthentication" in caplog.text
