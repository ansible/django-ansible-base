import logging
import re
from datetime import datetime, timedelta
from functools import partial
from unittest import mock
from urllib.parse import urlparse

import pytest
import requests
from django.test.utils import override_settings
from jwt.exceptions import DecodeError
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.jwt_consumer.common.auth import JWTAuthentication, JWTCommonAuth, default_mapped_user_fields
from ansible_base.lib.utils.translations import translatableConditionally as _


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

    def test_log_exception_no_expansion(self, expected_log):
        common_auth = JWTCommonAuth()
        message = "This is a test"
        translated_message = 'Translated text'
        expected_log = partial(expected_log, "ansible_base.jwt_consumer.common.auth.logger")
        with mock.patch('ansible_base.lib.utils.translations.translatableConditionally.translated', return_value=translated_message):
            with expected_log("error", message):
                with pytest.raises(AuthenticationFailed, match=translated_message):
                    common_auth.log_and_raise(_(message))

    def test_log_exception_with_expansion(self, expected_log):
        common_auth = JWTCommonAuth()
        message = "Please make sure this is %(expanded)s"
        translated_message = 'Translated with %(expanded)s text'
        expansion_values = {'expanded': 'whatever'}
        expected_log = partial(expected_log, "ansible_base.jwt_consumer.common.auth.logger")
        with mock.patch('ansible_base.lib.utils.translations.translatableConditionally.translated', return_value=translated_message):
            with expected_log("error", message % expansion_values):
                with pytest.raises(AuthenticationFailed, match=translated_message % expansion_values):
                    common_auth.log_and_raise(_(message), expansion_values)

    def test_get_decryption_key_absolute_junk(self):
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match="Unable to determine how to handle  to get key"):
            common_auth.get_decryption_key("", ignore_cache=True)

    def test_get_decryption_key_invalid_scheme(self):
        common_auth = JWTCommonAuth()
        url = "ftp://www.ansible.com"
        with pytest.raises(
            AuthenticationFailed,
            match=f"Unable to determine how to handle {url} to get key",
        ):
            common_auth.get_decryption_key(url, ignore_cache=True)

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
                common_auth.get_decryption_key(url, ignore_cache=True)

    # This would test any method returning junk instead of an RSA key
    def test_get_decryption_key_invalid_input(self):
        common_auth = JWTCommonAuth()
        with pytest.raises(AuthenticationFailed, match="Returned key does not start and end with BEGIN/END PUBLIC KEY"):
            common_auth.get_decryption_key("absolute_junk", ignore_cache=True)

    @pytest.mark.parametrize(
        "remove_newlines",
        [(False), (True)],
    )
    def test_get_decryption_key_file_read(self, remove_newlines, tmp_path_factory, test_encryption_public_key):
        common_auth = JWTCommonAuth()
        temp_dir = tmp_path_factory.mktemp("ansible_base.jwt_consumer.common.auth")
        temp_file_name = f"{temp_dir}/test.file"
        if remove_newlines:
            cert_data = test_encryption_public_key.replace("\n", "")
        else:
            cert_data = test_encryption_public_key
        with open(temp_file_name, "w") as f:
            f.write(cert_data)
        key, _ = common_auth.get_decryption_key(f"file:{temp_file_name}", ignore_cache=True)
        assert key == cert_data

    def test_get_decryption_key_file_read_with_cache(self, tmp_path_factory, test_encryption_public_key):
        common_auth = JWTCommonAuth()
        temp_dir = tmp_path_factory.mktemp("ansible_base.jwt_consumer.common.auth")
        temp_file_name = f"{temp_dir}/test.file"
        cert_data = test_encryption_public_key
        with open(temp_file_name, "w") as f:
            f.write(cert_data)
        key, cached = common_auth.get_decryption_key(f"file:{temp_file_name}", ignore_cache=True)
        assert key == cert_data
        assert cached is False
        key, cached = common_auth.get_decryption_key(f"file:{temp_file_name}")
        assert key == cert_data
        assert cached is True

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.ConnectionError))
    def test_get_decryption_key_connection_error(self):
        common_auth = JWTCommonAuth()
        url = "http://dne.cuz.junk.redhat.com"
        with pytest.raises(AuthenticationFailed, match=rf"Failed to connect to {url}.*"):
            common_auth.get_decryption_key(url, ignore_cache=True)

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.Timeout))
    def test_get_decryption_key_url_timeout(self):
        common_auth = JWTCommonAuth()
        url = "http://dne.cuz.junk.redhat.com"
        timeout = 1
        with pytest.raises(AuthenticationFailed, match=rf"Timed out after {timeout} secs when connecting to {url}.*"):
            common_auth.get_decryption_key(url, timeout=timeout, ignore_cache=True)

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.RequestException))
    def test_get_decryption_key_url_random_exception(self):
        common_auth = JWTCommonAuth()
        url = "http://dne.cuz.junk.redhat.com"
        with pytest.raises(AuthenticationFailed, match=r"Failed to get JWT decryption key from JWT server: \(RequestException\).*"):
            common_auth.get_decryption_key(url, ignore_cache=True)

    @pytest.mark.parametrize("status_code", ['302', '504'])
    def test_get_decryption_key_url_bad_status_codes(self, status_code, mocked_http):
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            common_auth = JWTCommonAuth()
            with pytest.raises(AuthenticationFailed, match=f"Failed to get 200 response from the issuer: {status_code}"):
                common_auth.get_decryption_key(f"http://someotherurl.com/{status_code}", ignore_cache=True)

    def test_get_decryption_key_url_bad_200(self, mocked_http):
        common_auth = JWTCommonAuth()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            with pytest.raises(AuthenticationFailed, match="Returned key does not start and end with BEGIN/END PUBLIC KEY"):
                common_auth.get_decryption_key("http://someotherurl.com/200_junk", ignore_cache=True)

    def test_get_decryption_key_url_good_200(self, mocked_http, test_encryption_public_key):
        common_auth = JWTCommonAuth()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            try:
                cert, _ = common_auth.get_decryption_key("http://someotherurl.com/200_good", ignore_cache=True)
            except Exception as e:
                assert False, f"Got unexpected exception {e}"
            assert cert == test_encryption_public_key

    def test_get_decryption_key_url_cache(self, mocked_http, test_encryption_public_key):
        common_auth = JWTCommonAuth()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            try:
                cert, cached = common_auth.get_decryption_key("http://someotherurl.com/200_good", ignore_cache=True)
            except Exception as e:
                assert False, f"Got unexpected exception {e}"
            assert cert == test_encryption_public_key
            assert cached is False
            cert, cached = common_auth.get_decryption_key("http://someotherurl.com/200_good")
            assert cert == test_encryption_public_key
            assert cached is True

    # If other tests are running at the same time there is a chance that they might set the key in the cache.
    # Since we don't mock the response intentionally we are going to tell this test to use a different cache key
    @mock.patch('ansible_base.jwt_consumer.common.auth.cache_key', 'expiration_test_jwt_key')
    def test_cache_expiring(self, mocked_http, test_encryption_public_key):
        with mock.patch('requests.get') as requests_get:
            # Setting the cache timeout to 0 effectively says don't cache.
            with override_settings(ANSIBLE_BASE_JWT_CACHE_TIMEOUT_SECONDS=0):
                common_auth = JWTCommonAuth()
                requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
                try:
                    cert, cached = common_auth.get_decryption_key("http://someotherurl.com/200_good")
                except Exception as e:
                    assert False, f"Got unexpected exception {e}"
                assert cert == test_encryption_public_key
                assert cached is False
                cert, cached = common_auth.get_decryption_key("http://someotherurl.com/200_good")
                assert cert == test_encryption_public_key
                assert cached is False

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
            (None, None, "Invalid token type. Token must be a <class 'bytes'>"),
            ("", None, "Not enough segments"),
            (None, "", "Invalid token type. Token must be a <class 'bytes'>"),
            ("junk", "junk", "Not enough segments"),
            ("a.b.c", None, "Invalid header padding"),
        ],
    )
    def test_validate_token_with_junk_input(self, token, key, exception_text):
        common_auth = JWTCommonAuth()
        with pytest.raises(DecodeError, match=exception_text):
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
            mock_parse.return_value = (None, None)
            jwt_auth = JWTAuthentication()
            auth_provided = jwt_auth.authenticate(mock.MagicMock())
            assert auth_provided is None

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

    def test_raise_an_exception_if_the_key_is_not_cached(self, random_public_key, mocked_http):
        # We are going to return a key which will not work with jwt_token provided by mocked_http
        # Because its not cached the call to parse_jwt_token should raise the exception
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.get_decryption_key', return_value=(random_public_key, False)):
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                jwt_auth = JWTAuthentication()
                with pytest.raises(AuthenticationFailed) as af:
                    jwt_auth.authenticate(request)
                    assert 'check your key and generated token' in af
                    assert 'cached key was correct' not in af

    def test_raise_an_exception_if_the_key_is_cached_but_the_new_key_is_the_same(self, random_public_key, mocked_http):
        # We are going to:
        #     1. return a key which will not work with jwt_token provided by mocked_http
        #     2. Cache a key that is invalid
        #     3. Error when the new token is the same as the cached token

        # Pretend the key is coming from a URL
        url = 'https://example.com'
        with override_settings(ANSIBLE_BASE_JWT_KEY=url):
            # 1. Make the get_decryption_key always return the random key (which is invalid) && 2. pretend the key is cached
            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.get_decryption_key', return_value=(random_public_key, True)):
                # 3. Make the call.
                # This will attempt to use the cached key, recognize that its invalid, load the key again (which will be the same) and then error out
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                jwt_auth = JWTAuthentication()
                with pytest.raises(AuthenticationFailed) as af:
                    jwt_auth.authenticate(request)
                    assert 'check your key and generated token' in af
                    assert 'cached key was correct' in af

    def test_correctly_authenticate_if_the_cached_key_is_invalid_but_the_new_key_is_correct(
        self, random_public_key, mocked_http, test_encryption_public_key, django_user_model, jwt_token
    ):
        # Pretend the key is coming from a URL
        url = 'https://example.com'
        with override_settings(ANSIBLE_BASE_JWT_KEY=url):
            return_values = [
                (random_public_key, True),
                (test_encryption_public_key, False),
            ]
            with mock.patch('ansible_base.jwt_consumer.common.auth.JWTCommonAuth.get_decryption_key', side_effect=return_values):
                request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')
                jwt_auth = JWTAuthentication()
                user = django_user_model.objects.create_user(username=jwt_token.unencrypted_token['sub'], password="password")
                created_user, _ = jwt_auth.authenticate(request)
                assert created_user == user

    def test_user_logging_in_and_in_cache_but_deleted_in_db(self, mocked_http, django_user_model, jwt_token, test_encryption_public_key):
        user = django_user_model.objects.create_user(username=jwt_token.unencrypted_token['sub'], password="password")
        with override_settings(ANSIBLE_BASE_JWT_KEY=test_encryption_public_key):
            jwt_auth = JWTAuthentication()
            request = mocked_http.mocked_parse_jwt_token_get_request('with_headers')

            # Get the user into the cache
            user_object, created = jwt_auth.authenticate(request)
            assert user_object == user

            # delete the user from the DB
            user.delete()

            # Authenticate the user again which will recreate the user so the objects will no longer be the same
            user_object, _ = jwt_auth.authenticate(request)
            assert user_object.username == user.username
            assert user_object.id != user.id
