import base64
from unittest import mock

import pytest
from django.utils.encoding import smart_str

from ansible_base.lib.utils.encryption import ENCRYPTION_METHOD, Fernet256

logger = 'ansible_base.lib.utils.encryption.logger'


@pytest.mark.parametrize(
    "input",
    [
        "test",
        None,
        {},
        [],
        True,
        False,
        {"value": 1, "value2": True, "value3": ["a", "b", "c"]},
        ["a", "list"],
    ],
)
def test_fernet256_encrypt_is_idempotent(input):
    """
    Ensure that encrypting a string twice still results in the same encrypted
    string.
    """
    fernet = Fernet256()
    encrypted_string = fernet.encrypt_string(input)
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


# Define the parameterized test function
@pytest.mark.parametrize(
    "input_value, expected",
    [
        ('asdf1234', (False, None, None)),
        ('$encrypted', (False, None, None)),
        ('$encrypted$something', (False, None, None)),
        ('$encrypted$UTF8$', (False, None, None)),
        ('$encrypted$UTF8$asdf1234', (False, None, None)),
        ('$encrypted$asdf1234', (False, None, None)),
        ('$encrypted$UTF8$AESCBC$', (False, None, None)),
        ('$encrypted$AESCBC$', (False, None, None)),
        ('$encrypted$AESCBC$not4characters', (False, None, None)),
        ('$encrypted$UTF8$AESCBC$junk', (True, 'AESCBC', 'junk')),
        ('$encrypted$UTF8$AESCBC$junk12==', (True, 'AESCBC', 'junk12==')),
        ('$encrypted$UTF8$AESCBC$junk123=', (True, 'AESCBC', 'junk123=')),
        ('$encrypted$UTF8$AESCBC$junk123=asdf', (False, None, None)),
        ('$encrypted$UTF8$AESCBC$junk123a', (True, 'AESCBC', 'junk123a')),
        (smart_str(base64.b64encode(b"This is a test")), (False, None, None)),
        (f'$encrypted$UTF8$AESCBC${smart_str(base64.b64encode(b"This is a test"))}', (True, 'AESCBC', smart_str(base64.b64encode(b"This is a test")))),
        (f'$encrypted$AESCBC${smart_str(base64.b64encode(b"This is a test"))}', (True, 'AESCBC', smart_str(base64.b64encode(b"This is a test")))),
        (
            f'$encrypted$some_other_algo${smart_str(base64.b64encode(b"This is a test"))}',
            (True, 'some_other_algo', smart_str(base64.b64encode(b"This is a test"))),
        ),
        (
            f'$encrypted$UTF8$some_other_algo${smart_str(base64.b64encode(b"This is a test"))}',
            (True, 'some_other_algo', smart_str(base64.b64encode(b"This is a test"))),
        ),
    ],
)
def test_is_encrypted_string(input_value, expected):
    """
    Note: is_encrypted_string can only perform a partial test to check if the
    input string is encrypted by our algorithm
    The test can't guarantee 100% accuracy due to the nature of base 64 encoding
    """
    fernet = Fernet256()
    assert fernet.is_encrypted_string(input_value) == expected


def test_encrypt_decrypt_string():
    """
    Ensure that the decrypted string is equal to the original plain text string.
    """
    fernet = Fernet256()
    input_string = "test"

    encrypted = fernet.encrypt_string(input_string)
    decrypted_string = fernet.decrypt_string(encrypted)
    assert decrypted_string == input_string


def test_fernet256_decrypt_raise_exception_on_json_decode_error(expected_log):
    from json import JSONDecodeError

    exception = JSONDecodeError('testing', 'test', 0)
    with mock.patch('ansible_base.lib.utils.encryption.json.loads', side_effect=exception):
        with expected_log('ansible_base.lib.utils.encryption.logger', 'exception', 'Failed to'):
            fernet = Fernet256()
            input_string = "test"
            encrypted_string = fernet.encrypt_string(input_string)
            with pytest.raises(JSONDecodeError) as e:
                fernet.decrypt_string(encrypted_string)
                assert e == exception
