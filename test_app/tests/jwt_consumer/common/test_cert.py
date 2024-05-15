from unittest import mock
from urllib.parse import urlparse

import pytest
import requests
from django.conf import settings
from django.test import override_settings

from ansible_base.jwt_consumer.common.cert import JWTCert, JWTCertException


class TestJWTCert:
    def test_get_decryption_key_no_setting(self):
        cert = JWTCert()
        cert.get_decryption_key()
        assert cert.key is None and cert.cached is None

    @pytest.mark.parametrize(
        "setting,string",
        [
            ('', 'Unable to determine how to handle  to get key'),
            ("ftp://www.ansible.com", 'Unable to determine how to handle ftp://www.ansible.com to get key'),
            ('absolute_junk', 'Returned key does not start and end with BEGIN/END PUBLIC KEY'),
        ],
    )
    def test_get_decryption_key_random_settings(self, setting, string):
        with override_settings(ANSIBLE_BASE_JWT_KEY=setting):
            cert = JWTCert()
            with pytest.raises(JWTCertException, match=string):
                cert.get_decryption_key(ignore_cache=True)
                assert cert.key is None and cert.cached is None

    @pytest.mark.parametrize(
        "error, exception_class",
        [
            ("The specified file {0} does not exist", FileNotFoundError()),
            ("The specified file {0} is not a file", IsADirectoryError()),
            ("Permission error when reading {0}", PermissionError()),
            ("Failed reading {0}: argh", IOError('argh')),
        ],
    )
    @override_settings(ANSIBLE_BASE_JWT_KEY='file:///gibberish')
    def test_get_decryption_key_file_exceptions(self, error, exception_class, tmp_path_factory):
        cert = JWTCert()
        url_parts = urlparse(settings.ANSIBLE_BASE_JWT_KEY)
        with mock.patch("builtins.open", mock.mock_open()) as mock_file:
            mock_file.side_effect = exception_class
            with pytest.raises(JWTCertException, match=error.format(url_parts.path)):
                cert.get_decryption_key(ignore_cache=True)
                assert cert.key is None and cert.cached is None

    @pytest.mark.parametrize(
        "remove_newlines",
        [(False), (True)],
    )
    def test_get_decryption_key_file_read(self, remove_newlines, tmp_path_factory, test_encryption_public_key):
        temp_dir = tmp_path_factory.mktemp("ansible_base.jwt_consumer.common.auth")
        temp_file_name = f"{temp_dir}/test.file"
        if remove_newlines:
            cert_data = test_encryption_public_key.replace("\n", "")
        else:
            cert_data = test_encryption_public_key
        with open(temp_file_name, "w") as f:
            f.write(cert_data)
        with override_settings(ANSIBLE_BASE_JWT_KEY=f'file:{temp_file_name}'):
            cert = JWTCert()
            cert.get_decryption_key(ignore_cache=True)
            assert cert.key == cert_data
            assert cert.cached is False

    def test_get_decryption_key_file_read_with_cache(self, tmp_path_factory, test_encryption_public_key):
        temp_dir = tmp_path_factory.mktemp("ansible_base.jwt_consumer.common.auth")
        temp_file_name = f"{temp_dir}/test.file"
        cert_data = test_encryption_public_key
        with open(temp_file_name, "w") as f:
            f.write(cert_data)

        with override_settings(ANSIBLE_BASE_JWT_KEY=f'file:{temp_file_name}'):
            cert = JWTCert()
            cert.get_decryption_key(ignore_cache=True)
            assert cert.key == cert_data
            assert cert.cached is False, "First key read should not have been cached"
            cert.get_decryption_key()
            assert cert.key == cert_data
            assert cert.cached is True, "Second key read should have been cached"

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.ConnectionError))
    @override_settings(ANSIBLE_BASE_JWT_KEY="http://dne.cuz.junk.redhat.com")
    def test_get_decryption_key_connection_error(self):
        cert = JWTCert()
        with pytest.raises(JWTCertException, match=rf"Failed to connect to {settings.ANSIBLE_BASE_JWT_KEY}.*"):
            cert.get_decryption_key(ignore_cache=True)
            assert cert.key is None and cert.cached is None

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.Timeout))
    @override_settings(ANSIBLE_BASE_JWT_KEY="http://dne.cuz.junk.redhat.com", ANSIBLE_BASE_JWT_URL_TIMEOUT=1)
    def test_get_decryption_key_url_timeout(self):
        cert = JWTCert()
        with pytest.raises(
            JWTCertException, match=rf"Timed out after {settings.ANSIBLE_BASE_JWT_URL_TIMEOUT} secs when connecting to {settings.ANSIBLE_BASE_JWT_KEY}.*"
        ):
            cert.get_decryption_key(ignore_cache=True)
            assert cert.key is None and cert.cached is None

    @mock.patch('requests.get', mock.Mock(side_effect=requests.exceptions.RequestException))
    @override_settings(ANSIBLE_BASE_JWT_KEY="http://dne.cuz.junk.redhat.com")
    def test_get_decryption_key_url_random_exception(self):
        cert = JWTCert()
        with pytest.raises(JWTCertException, match=r"Failed to get JWT decryption key from JWT server: \(RequestException\).*"):
            cert.get_decryption_key(ignore_cache=True)
            assert cert.key is None and cert.cached is None

    @pytest.mark.parametrize("status_code", ['302', '504'])
    def test_get_decryption_key_url_bad_status_codes(self, status_code, mocked_http):
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            with override_settings(ANSIBLE_BASE_JWT_KEY=f"http://someotherurl.com/{status_code}"):
                cert = JWTCert()
                with pytest.raises(JWTCertException, match=f"Failed to get 200 response from the issuer: {status_code}"):
                    cert.get_decryption_key(ignore_cache=True)
                    assert cert.key is None and cert.cached is None

    @override_settings(ANSIBLE_BASE_JWT_KEY="http://someotherurl.com/200_junk/")
    def test_get_decryption_key_url_bad_200(self, mocked_http):
        cert = JWTCert()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            with pytest.raises(JWTCertException, match="Returned key does not start and end with BEGIN/END PUBLIC KEY"):
                cert.get_decryption_key(ignore_cache=True)
                assert cert.key is None and cert.cached is None

    @override_settings(ANSIBLE_BASE_JWT_KEY="http://someotherurl.com/200_good")
    def test_get_decryption_key_url_good_200(self, mocked_http, test_encryption_public_key):
        cert = JWTCert()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            try:
                cert.get_decryption_key(ignore_cache=True)
            except Exception as e:
                assert False, f"Got unexpected exception {e}"
            assert cert.key == test_encryption_public_key
            assert cert.cached is False

    @override_settings(ANSIBLE_BASE_JWT_KEY="http://someotherurl.com/200_good")
    def test_get_decryption_key_url_cache(self, mocked_http, test_encryption_public_key):
        cert = JWTCert()
        with mock.patch('requests.get') as requests_get:
            requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
            try:
                cert.get_decryption_key(ignore_cache=True)
            except Exception as e:
                assert False, f"Got unexpected exception {e}"
            assert cert.key == test_encryption_public_key
            assert cert.cached is False, "First key read should not have been cached"
            cert.get_decryption_key()
            assert cert.key == test_encryption_public_key
            assert cert.cached is True, "Second key read should have been cached"

    # If other tests are running at the same time there is a chance that they might set the key in the cache.
    # Since we don't mock the response intentionally we are going to tell this test to use a different cache key
    @mock.patch('ansible_base.jwt_consumer.common.cache.cache_key', 'expiration_test_jwt_key')
    @override_settings(ANSIBLE_BASE_JWT_KEY="http://someotherurl.com/200_good")
    def test_cache_expiring(self, mocked_http, test_encryption_public_key):
        with mock.patch('requests.get') as requests_get:
            # Setting the cache timeout to 0 effectively says don't cache.
            with override_settings(ANSIBLE_BASE_JWT_CACHE_TIMEOUT_SECONDS=0):
                cert = JWTCert()
                requests_get.side_effect = mocked_http.mocked_get_decryption_key_get_request
                try:
                    cert.get_decryption_key()
                except Exception as e:
                    assert False, f"Got unexpected exception {e}"
                assert cert.key == test_encryption_public_key
                assert cert.cached is False, "The first cert load should not have been cached"
                cert.get_decryption_key()
                assert cert.key == test_encryption_public_key
                assert cert.cached is False
