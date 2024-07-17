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

    def test_validate_x_trusted_proxy_header_invalid_signature(self, random_public_key, expected_log):
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
            # Idealy we would mock match bytes.fromhex but I couldn't get that to work
            # with mock.patch('ansible_base.jwt_consumer.common.util.validate_x_trusted_proxy_header.bytes.fromhex', side_effect=ValueError()):
            with expected_log(
                'ansible_base.jwt_consumer.common.util.logger',
                'warning',
                'Failed to validate x-trusted-proxy-header, malformed, expected signature to well-formed base64',
            ):
                # 0 is invalid bytes
                assert validate_x_trusted_proxy_header("0-0") is False
