import time
from unittest import mock

from django.test.utils import override_settings

from ansible_base.jwt_consumer.common.util import _load_pem_private_key, generate_x_trusted_proxy_header, validate_x_trusted_proxy_header


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
                'ansible_base.jwt_consumer.common.util.logger',
                'warning',
                'was too old to be valid alter trusted_header_timeout_in_ns if needed',
            ):
                assert validate_x_trusted_proxy_header(header) is False

    def test_invalid_header_timestamp(self, expected_log, rsa_keypair):
        header = generate_x_trusted_proxy_header(rsa_keypair.private)
        _, signed_part = header.split('-')
        header = f'asdf-{signed_part}'
        with override_settings(ANSIBLE_BASE_JWT_KEY=rsa_keypair.public):
            with expected_log(
                'ansible_base.jwt_consumer.common.util.logger',
                'warning',
                'Unable to convert timestamp (base64)',
            ):
                assert validate_x_trusted_proxy_header(header) is False

    def test_validate_x_trusted_proxy_header_invalid_signature(self, random_public_key, expected_log, rsa_keypair):
        with override_settings(ANSIBLE_BASE_JWT_KEY=random_public_key):
            # Ideally we would mock match bytes.fromhex but I couldn't get that to work
            # with mock.patch('ansible_base.jwt_consumer.common.util.validate_x_trusted_proxy_header.bytes.fromhex', side_effect=ValueError()):
            header = generate_x_trusted_proxy_header(rsa_keypair.private)
            with expected_log(
                'ansible_base.jwt_consumer.common.util.logger',
                'warning',
                'Failed to validate x-trusted-proxy-header, malformed, expected signature to well-formed base64',
            ):
                # 0 is invalid bytes
                timestamp, junk = header.split('-')
                assert validate_x_trusted_proxy_header(f"{timestamp}-0") is False

    def test_generate_x_trusted_proxy_header(self, rsa_keypair, rsa_keypair_factory):
        """
        This test ensures that, for the same key, the function is called only once.
        Otherwise, the function is not called and the return value is returned from the cache.
        """
        _load_pem_private_key.cache_clear()
        new_rsa_keypair = rsa_keypair_factory()

        # Create a mock private key that has the sign method
        mock_private_key = mock.Mock()
        mock_private_key.sign.return_value = b'fake_signature'

        for keypair in [rsa_keypair, new_rsa_keypair]:
            with mock.patch("cryptography.hazmat.primitives.serialization.load_pem_private_key", return_value=mock_private_key) as mock_load_pem:
                # Call the function multiple times
                generate_x_trusted_proxy_header(keypair.private)
                generate_x_trusted_proxy_header(keypair.private)
                generate_x_trusted_proxy_header(keypair.private)

                # Verify the function is called only once due to caching
                assert mock_load_pem.call_count == 1
                mock_load_pem.assert_called_with(bytes(keypair.private, 'utf-8'), password=None)
