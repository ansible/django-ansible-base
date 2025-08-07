import pytest
from rest_framework.exceptions import ValidationError
from typeguard import suppress_type_checks

from ansible_base.lib.utils.validation import to_python_boolean, validate_cert_with_key, validate_domain_name, validate_image_data, validate_url


@suppress_type_checks
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
        (False, None, ['https', 'http'], True),
        (False, '', ['https', 'http'], True),
        (False, 'foobar', ['https', 'http'], True),
        (False, '123456', ['https', 'http'], True),
        (False, '/////', ['https', 'http'], True),
        (False, '...', ['https', 'http'], True),
        (False, '192.168.1.1', ['https', 'http'], True),
        (False, '0.0.0.0', ['https', 'http'], True),
        (False, 'httpXX://foobar', ['https', 'http'], True),
        (False, 'http://foobar::not::ip::v6', ['https', 'http'], True),
        (False, 'http://foobar:ABDC', ['https', 'http'], True),
        (True, 'http://foobar:80', ['https', 'http'], True),
        (True, 'https://foobar', ['https', 'http'], True),
        (True, 'https://foobar:443', ['https', 'http'], True),
        (True, 'http://[::1]', ['https', 'http'], True),
        (True, 'http://[::1]:80', ['https', 'http'], True),
        (True, 'http://[::192.9.5.5]/', ['https', 'http'], True),
        (True, 'http://[::FFFF:129.144.52.38]:80', ['https', 'http'], True),
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


def test_validate_cert_with_signed_certificate(rsa_keypair_with_signed_cert_1):
    """
    Ensure that validate_cert_with_key raises a ValidationError when the cert and key don't match.
    """
    keypair = rsa_keypair_with_signed_cert_1.root
    assert validate_cert_with_key(keypair.certificate, keypair.private)
    keypair = rsa_keypair_with_signed_cert_1.subordinate
    assert validate_cert_with_key(keypair.certificate, keypair.private)


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


@pytest.mark.parametrize(
    "domain,expected,description",
    [
        # Valid domains
        ("example.com", True, "Basic valid domain"),
        ("sub.example.com", True, "Valid subdomain"),
        ("api.v2.example.com", True, "Multi-level subdomain"),
        ("test-site.example.org", True, "Domain with hyphen in subdomain"),
        ("a.co", True, "Short valid domain"),
        ("test.museum", True, "Long TLD"),
        ("123.com", True, "Numeric subdomain with valid TLD"),
        ("example.co.uk", True, "Country code TLD"),
        ("x.example.info", True, "Single letter subdomain"),
        ("test123.example.net", True, "Alphanumeric subdomain"),
        # Valid with trailing dot (DNS allows this)
        ("example.com.", True, "Domain with trailing dot"),
        ("sub.example.org.", True, "Subdomain with trailing dot"),
        # Invalid domains - format issues
        ("example", False, "Single label (no TLD)"),
        ("", False, "Empty string"),
        ("example.c", False, "Single-character TLD"),
        ("test.123", False, "All-numeric TLD"),
        ("example-.com", False, "Label ending with hyphen"),
        ("-example.com", False, "Label starting with hyphen"),
        ("exam_ple.com", False, "Underscore in domain"),
        ("example..com", False, "Consecutive dots"),
        (".example.com", False, "Leading dot"),
        ("example.", False, "Trailing dot with no TLD"),
        ("example.com-", False, "TLD ending with hyphen"),
        # Invalid domains - length issues
        ("a" * 64 + ".com", False, "Label too long (>63 chars)"),
        ("a." + "b" * 250, False, "Total domain too long (>255 chars)"),
        # Invalid domains - character issues
        ("example.com!", False, "Invalid character (!)"),
        ("example@domain.com", False, "Invalid character (@)"),
        ("example.com/path", False, "Invalid character (/)"),
        ("example domain.com", False, "Space in domain"),
        ("example.com?query", False, "Invalid character (?)"),
        ("example.com#fragment", False, "Invalid character (#)"),
        # Edge cases with special characters
        ("exam\tple.com", False, "Tab character"),
        ("exam\nple.com", False, "Newline character"),
        ("exam ple.com", False, "Space character"),
        # TLD validation edge cases
        ("example.1", False, "Single digit TLD"),
        ("example.12", False, "Two digit TLD"),
        ("example.1a", True, "Mixed digit-letter TLD (valid)"),
        # Complex valid cases
        ("very-long-subdomain-name.example.com", True, "Long subdomain name"),
        ("a1-b2-c3.example.org", True, "Multiple hyphens in subdomain"),
        ("test.example.co.uk", True, "Multi-part country TLD"),
    ],
)
def test_validate_domain_name(domain, expected, description):
    """
    Test validate_domain_name function with various domain inputs.
    """
    result = validate_domain_name(domain)
    assert result == expected, f"Failed for {description}: '{domain}' -> Expected: {expected}, Got: {result}"


@pytest.mark.parametrize(
    "domain",
    [
        None,
        123,
        [],
        {},
        True,
        False,
    ],
)
def test_validate_domain_name_non_string_inputs(domain):
    """
    Test validate_domain_name function with non-string inputs.
    All non-string inputs should return False.
    """
    result = validate_domain_name(domain)
    assert result is False, f"Non-string input '{domain}' should return False, got {result}"


def test_validate_domain_name_boundary_conditions():
    """
    Test validate_domain_name with boundary conditions for length limits.
    """
    # Test maximum valid label length (63 characters)
    max_label = "a" * 63
    assert validate_domain_name(f"{max_label}.com") is True

    # Test label that's too long (64 characters)
    too_long_label = "a" * 64
    assert validate_domain_name(f"{too_long_label}.com") is False

    # Test maximum valid total domain length (close to 255)
    # Create a domain that's close to but under 255 chars
    long_domain = "a" * 60 + "." + "b" * 60 + "." + "c" * 60 + "." + "d" * 60 + ".com"
    # This should be around 249 characters, which is valid
    assert len(long_domain) < 255
    assert validate_domain_name(long_domain) is True

    # Test minimum valid TLD length (2 characters)
    assert validate_domain_name("example.co") is True

    # Test single character TLD (invalid)
    assert validate_domain_name("example.c") is False


def test_validate_domain_name_tld_requirements():
    """
    Test TLD-specific validation requirements.
    """
    # TLD must contain at least one letter
    assert validate_domain_name("example.123") is False  # All numeric
    assert validate_domain_name("example.12a") is True  # Contains letter
    assert validate_domain_name("example.a12") is True  # Contains letter
    assert validate_domain_name("example.abc") is True  # All letters

    # TLD must be at least 2 characters
    assert validate_domain_name("example.a") is False  # Too short
    assert validate_domain_name("example.ab") is True  # Minimum length

    # TLD cannot start or end with hyphen (covered by label rules)
    assert validate_domain_name("example.-com") is False  # TLD starts with hyphen
    assert validate_domain_name("example.com-") is False  # TLD ends with hyphen
