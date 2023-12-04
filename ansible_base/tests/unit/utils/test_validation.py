import pytest
from rest_framework.exceptions import ValidationError

from ansible_base.utils.validation import validate_cert_with_key, validate_url


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
