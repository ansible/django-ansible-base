import pytest

from ansible_base.lib.utils.encryption import ENCRYPTION_METHOD, Fernet256


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
