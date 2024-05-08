import pytest
from django.test import override_settings

from ansible_base.lib.utils.encryption import (
    ENCRYPTION_METHOD,
    Fernet256,
    SharedSecretNotFound,
    generate_hmac_sha256_shared_secret,
    validate_hmac_sha256_shared_secret,
)

logger = 'ansible_base.lib.utils.encryption.logger'


def test_fernet256_encrypt_is_idempotent():
    """
    Ensure that encrypting a string twice still results in the same encrypted
    string.
    """
    fernet = Fernet256()
    input_string = "test"
    encrypted_string = fernet.encrypt_string(input_string)
    double_encrypted_string = fernet.encrypt_string(encrypted_string)
    assert encrypted_string == double_encrypted_string


def test_fernet256_decrypt_is_idempotent():
    """
    Ensure that decrypting a string twice still results in the original string.
    """
    fernet = Fernet256()
    input_string = "test"
    encrypted_string = fernet.encrypt_string(input_string)
    decrypted_string = fernet.decrypt_string(encrypted_string)
    double_decrypted_string = fernet.decrypt_string(decrypted_string)
    assert decrypted_string == double_decrypted_string
    assert decrypted_string == input_string


def test_fernet256_unsupported_algorithm():
    """
    Ensure that an exception is raised when a string with an unsupported
    algorithm is passed to decrypt_string.
    """
    fernet = Fernet256()
    input_string = "test"
    encrypted_string = fernet.encrypt_string(input_string)
    encrypted_string = encrypted_string.replace(ENCRYPTION_METHOD, "monkey")

    with pytest.raises(ValueError) as e:
        fernet.decrypt_string(encrypted_string)
    assert str(e.value) == "Unsupported algorithm: monkey"


def test_generate_hmac_field_setting_set(expected_log):
    """
    Ensure a log is generated if the variable is unset
    """
    hmac_message = 'The setting ANSIBLE_BASE_SHARED_SECRET was not set, some functionality may be disabled.'
    with expected_log(logger, 'error', hmac_message, assert_not_called=True):
        generate_hmac_sha256_shared_secret()


def test_generate_hmac_field_setting_unset(expected_log):
    """
    Ensure a log is generated if the variable is unset
    """
    with override_settings(ANSIBLE_BASE_SHARED_SECRET=None):
        with pytest.raises(SharedSecretNotFound):
            generate_hmac_sha256_shared_secret()


def test_generate_hmac_no_nonce_is_ok():
    """
    Validate that if we don't set an nonce it will pick one and do the encryption with it
    """
    secret = generate_hmac_sha256_shared_secret()
    nonce, _ = secret.split(':')
    assert secret == generate_hmac_sha256_shared_secret(nonce=nonce)


@pytest.mark.parametrize(
    "pre_shared_secret,causes_failure",
    [
        ("some_string", False),
        (1, False),
        (None, True),
        ('', True),
        (True, False),
        ({}, True),
        ([], True),
    ],
)
def test_generate_hmac_different_types_of_pre_shared_secret(pre_shared_secret, causes_failure):
    with override_settings(ANSIBLE_BASE_SHARED_SECRET=pre_shared_secret):
        try:
            generate_hmac_sha256_shared_secret()
        except SharedSecretNotFound:
            if not causes_failure:
                assert False, f"Should not have gotten a SharedSecretNotFound exception for {pre_shared_secret}"


@pytest.mark.parametrize(
    "nonce,secret,valid",
    [
        (None, None, True),
        (7, None, False),
        (None, 'gibberish', False),
        ('12', 'junk', False),
    ],
)
def test_generate_hmac_validation(nonce, secret, valid):
    generated_nonce, generated_secret = generate_hmac_sha256_shared_secret().split(':')
    if nonce:
        generated_nonce = nonce
    if secret:
        generated_secret = secret
    assert validate_hmac_sha256_shared_secret(f'{generated_nonce}:{generated_secret}') is valid
