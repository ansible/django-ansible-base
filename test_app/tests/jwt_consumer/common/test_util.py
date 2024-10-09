import time
from unittest import mock

from django.test.utils import override_settings

from ansible_base.jwt_consumer.common.util import generate_x_trusted_proxy_header, validate_x_trusted_proxy_header


class TestValidateTrustedProxy:
    def test_validate_trusted_proxy_header_bad_cached_key_but_correct_setting(self, rsa_keypair, random_public_key, create_mock_method):
        field_dicts = [
            {"key": random_public_key, "cached": True},
            {"key": rsa_keypair.public, "cached": False},
        ]
        with override_settings(ANSIBLE_BASE_JWT_KEY=rsa_keypair.public):
            with mock.patch("ansible_base.jwt_consumer.common.util.JWTCert.get_decryption_key", create_mock_method(field_dicts)):
                assert validate_x_trusted_proxy_header(generate_x_trusted_proxy_header(rsa_keypair.private))

    def test_validate_trusted_proxy_header_no_key(self, caplog):
        with override_settings(ANSIBLE_BASE_JWT_KEY=None):
            assert not validate_x_trusted_proxy_header("any input")
            assert "Failed to validate x-trusted-proxy-header, unable to load cert" in caplog.text

    @mock.patch("cryptography.hazmat.primitives.serialization.load_pem_public_key", side_effect=Exception())
    def test_validate_trusted_proxy_header_fail_load_public_key(self, mock_load_pem_public_key, caplog, random_public_key):
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
            assert not validate_x_trusted_proxy_header("any input")
            assert "Failed to load public key" in caplog.text

    def test_validate_trusted_proxy_header_bad_public_key(self, random_public_key):
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
            assert not validate_x_trusted_proxy_header("0-12345123451234512345")

    def test_header_timeout(self, expected_log, rsa_keypair):
        header = generate_x_trusted_proxy_header(rsa_keypair.private)
        with override_settings(ANSIBLE_BASE_JWT_KEY=rsa_keypair.public):
            # Assert this header is valid if used right away
            assert validate_x_trusted_proxy_header(header) is True

            # By default the header is only valid for 300ms so a 1/2 second sleep will expire it
            time.sleep(0.5)
            with expected_log(
                'ansible_base.jwt_consumer.common.util.logger', 'warning', 'was too old to be valid alter trusted_header_timeout_in_ns if needed'
            ):
                assert validate_x_trusted_proxy_header(header) is False

    def test_invalid_header_timestamp(self, expected_log, rsa_keypair):
        header = generate_x_trusted_proxy_header(rsa_keypair.private)
        _, signed_part = header.split('-')
        header = f'asdf-{signed_part}'
        with override_settings(ANSIBLE_BASE_JWT_KEY=rsa_keypair.public):
            with expected_log('ansible_base.jwt_consumer.common.util.logger', 'warning', 'Unable to convert timestamp (base64)'):
                assert validate_x_trusted_proxy_header(header) is False
