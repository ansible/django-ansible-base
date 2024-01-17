import pytest
from rest_framework.exceptions import ValidationError

from ansible_base.lib.utils.validation import to_python_boolean, validate_cert_with_key, validate_image_data, validate_url


@pytest.mark.parametrize(
    "valid,url,schemes,allow_plain_hostname",
    [
        (False, 4, [], True),
        (False, "https://example", ['https'], False),
        (True, "https://example", ['https'], True),
        (True, "https://somedomain.example.com/sso/complete/saml/", ['https'], True),
        (False, "https://somedomain.example.com/sso/complete/saml/", ['ldaps'], True),
        (True, "ldaps://somedomain.example.com/sso/complete/saml/", ['ldaps'], True),
        (False, "https://somedomain.[obfuscated.domain]/sso/complete/saml/", ['https'], True),
    ],
)
def test_validate_bad_urls(valid, url, schemes, allow_plain_hostname):
    exception = None
    try:
        validate_url(url, schemes=schemes, allow_plain_hostname=allow_plain_hostname)
    except ValidationError as e:
        exception = e

    if valid and exception:
        assert False, f"Configuration should have been valid but got exception: {exception}"
    elif not valid and not exception:
        assert False, "Expected an exception but test passed"


@pytest.mark.parametrize(
    "cert, key",
    [
        (False, False),
        (None, None),
        (None, False),
        (False, None),
        ("", ""),
        ("", None),
        (None, ""),
        ("", "asdf"),
        ("asdf", ""),
        ("asdf", None),
        (None, "asdf"),
    ],
)
def test_validate_cert_with_key_falsy_param(cert, key):
    """
    Ensure that validate_cert_with_key returns None when passed falsy values.
    """
    assert validate_cert_with_key(cert, key) is None


@pytest.mark.parametrize(
    "cert, key",
    [
        ("asdf", "asdf"),
        # In the below, None, means use the value from the fixture
        (None, "asdf"),
        ("asdf", None),
    ],
)
def test_validate_cert_with_key_invalid_params(rsa_keypair_with_cert, cert, key):
    """
    Ensure that validate_cert_with_key is False when it fails to load a cert or key.
    """
    if cert is None:
        cert = rsa_keypair_with_cert.certificate
    if key is None:
        key = rsa_keypair_with_cert.private
    assert validate_cert_with_key(cert, key) is False


def test_validate_cert_with_key_mismatch(rsa_keypair_with_cert_1, rsa_keypair_with_cert_2):
    """
    Ensure that validate_cert_with_key raises a ValidationError when the cert and key don't match.
    """
    with pytest.raises(ValidationError) as e:
        validate_cert_with_key(rsa_keypair_with_cert_1.certificate, rsa_keypair_with_cert_2.private)
    assert "The certificate and private key do not match" in str(e.value)


def test_validate_image_data_with_valid_data():
    """
    Ensure that validate_image_data accepts valid data.
    """
    image_data = "data:image/gif;base64,R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs="
    res = validate_image_data(image_data)
    assert not res


def test_validate_image_data_with_wrong_format():
    """
    Ensure that validate_image_data raises a ValidationError when data format doesn't match.
    """
    image_data = "image"
    with pytest.raises(ValidationError) as e:
        validate_image_data(image_data)
    assert "Invalid format for custom logo. Must be a data URL with a base64-encoded GIF, PNG or JPEG image." in str(e.value)


def test_validate_image_data_with_bad_data():
    """
    Ensure that validate_image_data raises a ValidationError when data is bad/corrupted.
    """
    image_data = "data:image/gif;base64,thisisbaddata"
    with pytest.raises(ValidationError) as e:
        validate_image_data(image_data)
    assert "Invalid base64-encoded data in data URL." in str(e.value)


@pytest.mark.parametrize(
    "value,return_value,raises",
    (
        (True, True, False),
        ("true", True, False),
        ("TRUE", True, False),
        (1, True, False),
        ("t", True, False),
        ("T", True, False),
        ("on", None, True),
        (False, False, False),
        ("false", False, False),
        ("FALSE", False, False),
        (0, False, False),
        ("f", False, False),
        ("F", False, False),
        ("off", False, True),
    ),
)
def test_to_python_boolean(value, return_value, raises):
    try:
        response = to_python_boolean(value)
        assert response == return_value
    except ValueError:
        if not raises:
            assert False, "We did not expect this to raise an exception"


@pytest.mark.parametrize(
    "value",
    (
        (None),
        ("none"),
        ("None"),
        ("null"),
        ("Null"),
    ),
)
def test_to_python_boolean_none(value):
    assert to_python_boolean(value, allow_none=True) is None
