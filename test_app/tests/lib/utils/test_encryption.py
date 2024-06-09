import pytest

from ansible_base.lib.utils.encryption import ENCRYPTED_STRING, ENCRYPTION_METHOD, Fernet256

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


def test_extract_data():
    """
    Ensure that the base 64 encoded data is extracted correctly
    """
    fernet = Fernet256()
    input_string = "test"

    # Test extracting data with UTF8 marker
    encrypted_str_w_marker = fernet.encrypt_string(input_string)
    expected_data_w_marker = encrypted_str_w_marker[len(f'{ENCRYPTED_STRING}UTF8${ENCRYPTION_METHOD}$') :]
    assert fernet.extract_data(encrypted_str_w_marker) == expected_data_w_marker

    # Test extracting data without UTF8 marker
    encrypted_str_wo_marker = encrypted_str_w_marker.replace("UTF8$", "")
    expected_data_wo_marker = encrypted_str_wo_marker[len(f'{ENCRYPTED_STRING}{ENCRYPTION_METHOD}$') :]
    assert fernet.extract_data(encrypted_str_wo_marker) == expected_data_wo_marker


def test_is_encrypted_string():
    """
    Note: is_encrypted_string can only perform a partial test to check if the
    input string is encrypted by our algorithm
    The test can't guarantee 100% accuracy due to the nature of base 64 encoding
    """
    fernet = Fernet256()
    input_string = "test"
    encrypted_string = fernet.encrypt_string(input_string)

    # Test for encrypted string
    assert fernet.is_encrypted_string(encrypted_string, False) is True

    # Test for non-encrypted string
    assert fernet.is_encrypted_string(input_string, False) is False


def test_encrypt_decrypt_string():
    """
    Ensure that the decrypted string is equal to the original plain text string.
    """
    fernet = Fernet256()
    input_string = "test"

    encrypted = fernet.encrypt_string(input_string)
    decrypted_string = fernet.decrypt_string(encrypted)
    assert decrypted_string == input_string
