import pytest
from rest_framework.exceptions import ValidationError

from ansible_base.lib.utils.validation import (
    _is_valid_domain_format,
    _is_valid_label,
    _is_valid_tld,
    _normalize_domain,
    to_python_boolean,
    validate_cert_with_key,
    validate_domain_name,
    validate_free_text,
    validate_image_data,
    validate_port,
    validate_resource_name,
    validate_url,
)


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


# Tests for the new helper functions


@pytest.mark.parametrize(
    "domain,expected,description",
    [
        # Valid basic formats
        ("example.com", True, "Basic valid format"),
        ("sub.example.com", True, "Valid subdomain format"),
        ("a.b", True, "Minimal valid format"),
        ("test.co.uk", True, "Multi-part TLD format"),
        ("example.com.", True, "Format with trailing dot"),
        # Invalid - non-string types
        (None, False, "None input"),
        (123, False, "Integer input"),
        ([], False, "List input"),
        ({}, False, "Dict input"),
        (True, False, "Boolean input"),
        # Invalid - empty or too long
        ("", False, "Empty string"),
        ("a" * 256, False, "String too long (>255 chars)"),
        # Invalid - no dot (not FQDN)
        ("example", False, "No dot - not FQDN"),
        ("localhost", False, "Localhost without dot"),
        # Valid edge cases
        ("a.b", True, "Minimal length with dot"),
        ("x" * 253 + ".c", True, "Maximum valid length"),
    ],
)
def test_is_valid_domain_format(domain, expected, description):
    """
    Test _is_valid_domain_format helper function.
    """
    result = _is_valid_domain_format(domain)
    assert result == expected, f"Failed for {description}: '{domain}' -> Expected: {expected}, Got: {result}"


@pytest.mark.parametrize(
    "domain,expected,description",
    [
        # Domains without trailing dot (no change)
        ("example.com", "example.com", "Domain without trailing dot"),
        ("sub.example.org", "sub.example.org", "Subdomain without trailing dot"),
        ("a.b", "a.b", "Minimal domain without trailing dot"),
        # Domains with trailing dot (should be removed)
        ("example.com.", "example.com", "Domain with trailing dot"),
        ("sub.example.org.", "sub.example.org", "Subdomain with trailing dot"),
        ("a.b.", "a.b", "Minimal domain with trailing dot"),
        ("test.co.uk.", "test.co.uk", "Multi-part TLD with trailing dot"),
        # Edge cases
        ("", "", "Empty string"),
        (".", "", "Single dot only"),
        ("example.", "example", "Domain ending with single dot"),
    ],
)
def test_normalize_domain(domain, expected, description):
    """
    Test _normalize_domain helper function.
    """
    result = _normalize_domain(domain)
    assert result == expected, f"Failed for {description}: '{domain}' -> Expected: '{expected}', Got: '{result}'"


@pytest.mark.parametrize(
    "label,expected,description",
    [
        # Valid labels
        ("example", True, "Basic valid label"),
        ("test123", True, "Alphanumeric label"),
        ("sub-domain", True, "Label with hyphen in middle"),
        ("a", True, "Single character label"),
        ("123", True, "Numeric label"),
        ("a" * 63, True, "Maximum length label (63 chars)"),
        ("test-123-abc", True, "Multiple hyphens in middle"),
        # Invalid - empty or too long
        ("", False, "Empty label"),
        ("a" * 64, False, "Label too long (64 chars)"),
        # Invalid - invalid characters
        ("test_domain", False, "Underscore in label"),
        ("test domain", False, "Space in label"),
        ("test.domain", False, "Dot in label"),
        ("test@domain", False, "At symbol in label"),
        ("test#domain", False, "Hash in label"),
        ("test!domain", False, "Exclamation in label"),
        ("test/domain", False, "Slash in label"),
        ("test\\domain", False, "Backslash in label"),
        ("test?domain", False, "Question mark in label"),
        ("test&domain", False, "Ampersand in label"),
        ("test%domain", False, "Percent in label"),
        # Invalid - hyphens at start/end
        ("-example", False, "Label starting with hyphen"),
        ("example-", False, "Label ending with hyphen"),
        ("-", False, "Single hyphen"),
        ("-test-", False, "Hyphens at both ends"),
        ("--test", False, "Multiple leading hyphens"),
        ("test--", False, "Multiple trailing hyphens"),
    ],
)
def test_is_valid_label(label, expected, description):
    """
    Test _is_valid_label helper function.
    """
    result = _is_valid_label(label)
    assert result == expected, f"Failed for {description}: '{label}' -> Expected: {expected}, Got: {result}"


@pytest.mark.parametrize(
    "tld,expected,description",
    [
        # Valid TLDs
        ("com", True, "Common TLD"),
        ("org", True, "Organization TLD"),
        ("co", True, "Minimal length TLD"),
        ("info", True, "Long TLD"),
        ("museum", True, "Very long TLD"),
        ("uk", True, "Country code TLD"),
        ("123a", True, "TLD with numbers and letter"),
        ("a123", True, "TLD starting with letter"),
        ("12a3", True, "TLD with mixed numbers and letters"),
        ("abc123", True, "TLD ending with numbers"),
        ("a1b2c3", True, "TLD with alternating letters and numbers"),
        # Invalid - too short
        ("c", False, "Single character TLD"),
        ("a", False, "Single letter TLD"),
        ("1", False, "Single digit TLD"),
        # Invalid - all numeric
        ("123", False, "All numeric TLD"),
        ("12", False, "Two digit TLD"),
        ("1234", False, "Four digit TLD"),
        ("999", False, "All nines TLD"),
        ("000", False, "All zeros TLD"),
        # Invalid - no letters
        ("12", False, "Two digits only"),
        ("123", False, "Three digits only"),
        # Invalid - empty
        ("", False, "Empty TLD"),
        # Valid edge cases with letters
        ("1a", True, "Number followed by letter"),
        ("a1", True, "Letter followed by number"),
        ("11a", True, "Two numbers followed by letter"),
        ("a11", True, "Letter followed by two numbers"),
    ],
)
def test_is_valid_tld(tld, expected, description):
    """
    Test _is_valid_tld helper function.
    """
    result = _is_valid_tld(tld)
    assert result == expected, f"Failed for {description}: '{tld}' -> Expected: {expected}, Got: {result}"


def test_helper_functions_integration():
    """
    Test that the helper functions work together correctly for domain validation.
    This tests the integration of all helper functions with the main validate_domain_name.
    """
    # Test a valid domain through all helper functions
    domain = "sub.example.com"

    # Should pass format validation
    assert _is_valid_domain_format(domain) is True

    # Should normalize correctly (no change for this example)
    normalized = _normalize_domain(domain)
    assert normalized == "sub.example.com"

    # Should validate all labels
    labels = normalized.split('.')
    for label in labels:
        assert _is_valid_label(label) is True, f"Label '{label}' should be valid"

    # Should validate TLD
    tld = labels[-1]
    assert _is_valid_tld(tld) is True

    # Overall validation should pass
    assert validate_domain_name(domain) is True


def test_helper_functions_edge_case_integration():
    """
    Test helper functions with edge cases that should fail at different stages.
    """
    # Test domain that fails format validation
    invalid_format = "example"  # No dot
    assert _is_valid_domain_format(invalid_format) is False
    assert validate_domain_name(invalid_format) is False

    # Test domain that passes format but fails label validation
    invalid_label = "exam_ple.com"  # Underscore in label
    assert _is_valid_domain_format(invalid_label) is True
    normalized = _normalize_domain(invalid_label)
    labels = normalized.split('.')
    assert _is_valid_label(labels[0]) is False  # "exam_ple" should fail
    assert validate_domain_name(invalid_label) is False

    # Test domain that passes format and labels but fails TLD validation
    invalid_tld = "example.123"  # All-numeric TLD
    assert _is_valid_domain_format(invalid_tld) is True
    normalized = _normalize_domain(invalid_tld)
    labels = normalized.split('.')
    assert _is_valid_label(labels[0]) is True  # "example" should pass
    assert _is_valid_tld(labels[1]) is False  # "123" should fail
    assert validate_domain_name(invalid_tld) is False


def test_helper_functions_with_trailing_dot():
    """
    Test that normalization properly handles trailing dots.
    """
    domain_with_dot = "example.com."
    domain_without_dot = "example.com"

    # Both should pass format validation
    assert _is_valid_domain_format(domain_with_dot) is True
    assert _is_valid_domain_format(domain_without_dot) is True

    # Normalization should make them equivalent
    normalized_with_dot = _normalize_domain(domain_with_dot)
    normalized_without_dot = _normalize_domain(domain_without_dot)
    assert normalized_with_dot == normalized_without_dot == "example.com"

    # Both should validate to the same result
    assert validate_domain_name(domain_with_dot) is True
    assert validate_domain_name(domain_without_dot) is True


class TestValidatePort:
    """Test cases for validate_port function"""

    @pytest.mark.parametrize(
        "port,expected,description",
        [
            # Valid cases - integers
            (1, True, "Minimum valid port as integer"),
            (80, True, "Standard HTTP port as integer"),
            (443, True, "Standard HTTPS port as integer"),
            (8080, True, "Common development port as integer"),
            (65535, True, "Maximum valid port as integer"),
            # Valid cases - strings
            ("1", True, "Minimum valid port as string"),
            ("80", True, "Standard HTTP port as string"),
            ("443", True, "Standard HTTPS port as string"),
            ("8080", True, "Common development port as string"),
            ("65535", True, "Maximum valid port as string"),
            ("22", True, "SSH port as string"),
            ("3306", True, "MySQL port as string"),
            ("5432", True, "PostgreSQL port as string"),
            # Invalid cases - out of range integers
            (0, False, "Port 0 is reserved"),
            (-1, False, "Negative port number"),
            (65536, False, "Port above maximum range"),
            (99999, False, "Port well above maximum range"),
            # Invalid cases - out of range strings
            ("0", False, "Port 0 as string"),
            ("-1", False, "Negative port as string"),
            ("65536", False, "Port above maximum range as string"),
            ("99999", False, "Port well above maximum range as string"),
            # Invalid cases - non-numeric strings
            ("abc", False, "Non-numeric string"),
            ("80a", False, "String with letters and numbers"),
            ("", False, "Empty string"),
            (" ", False, "Whitespace string"),
            ("80.5", False, "Decimal number as string"),
            ("80 ", False, "String with trailing space"),
            (" 80", False, "String with leading space"),
            ("8080.0", False, "String with decimal point"),
            # Invalid cases - other types
            (None, False, "None value"),
            (80.5, False, "Float number"),
            ([], False, "Empty list"),
            ([80], False, "List with port number"),
            ({}, False, "Empty dictionary"),
            ({"port": 80}, False, "Dictionary with port"),
            (True, False, "Boolean True"),
            (False, False, "Boolean False"),
            (set([80]), False, "Set with port number"),
            (tuple([80]), False, "Tuple with port number"),
        ],
    )
    def test_validate_port(self, port, expected, description):
        """Test validate_port function with various port inputs."""
        result = validate_port(port)
        assert result is expected, f"Failed for {description}: validate_port({port!r}) returned {result}, expected {expected}"

    @pytest.mark.parametrize(
        "port,expected,description",
        [
            # Boundary values - integers
            (1, True, "Minimum valid port as integer"),
            (65535, True, "Maximum valid port as integer"),
            (0, False, "Port 0 is reserved (integer)"),
            (65536, False, "Port above maximum range (integer)"),
            # Boundary values - strings
            ("1", True, "Minimum valid port as string"),
            ("65535", True, "Maximum valid port as string"),
            ("0", False, "Port 0 is reserved (string)"),
            ("65536", False, "Port above maximum range (string)"),
            # Common ports - integers
            (21, True, "FTP port as integer"),
            (22, True, "SSH port as integer"),
            (23, True, "Telnet port as integer"),
            (25, True, "SMTP port as integer"),
            (53, True, "DNS port as integer"),
            (80, True, "HTTP port as integer"),
            (110, True, "POP3 port as integer"),
            (143, True, "IMAP port as integer"),
            (443, True, "HTTPS port as integer"),
            (993, True, "IMAPS port as integer"),
            (995, True, "POP3S port as integer"),
            (3306, True, "MySQL port as integer"),
            (5432, True, "PostgreSQL port as integer"),
            (6379, True, "Redis port as integer"),
            (8080, True, "HTTP alternate port as integer"),
            (8443, True, "HTTPS alternate port as integer"),
            # Common ports - strings
            ("21", True, "FTP port as string"),
            ("22", True, "SSH port as string"),
            ("23", True, "Telnet port as string"),
            ("25", True, "SMTP port as string"),
            ("53", True, "DNS port as string"),
            ("80", True, "HTTP port as string"),
            ("110", True, "POP3 port as string"),
            ("143", True, "IMAP port as string"),
            ("443", True, "HTTPS port as string"),
            ("993", True, "IMAPS port as string"),
            ("995", True, "POP3S port as string"),
            ("3306", True, "MySQL port as string"),
            ("5432", True, "PostgreSQL port as string"),
            ("6379", True, "Redis port as string"),
            ("8080", True, "HTTP alternate port as string"),
            ("8443", True, "HTTPS alternate port as string"),
        ],
    )
    def test_validate_port_edge_cases(self, port, expected, description):
        """Test validate_port with boundary values and common ports."""
        result = validate_port(port)
        assert result is expected, f"Failed for {description}: validate_port({port!r}) returned {result}, expected {expected}"

    @pytest.mark.parametrize(
        "port_string,expected,description",
        [
            # Leading zeros - should work
            ("08", True, "Leading zero string should convert to valid port 8"),
            ("080", True, "Leading zero string should convert to valid port 80"),
            ("0443", True, "Leading zero string should convert to valid port 443"),
            # Python notation strings - should be invalid
            ("80L", False, "Old Python long notation should be invalid"),
            ("80l", False, "Lowercase long notation should be invalid"),
            ("0x50", False, "Hexadecimal notation should be invalid"),
            ("0o100", False, "Octal notation should be invalid"),
            ("0b1010000", False, "Binary notation should be invalid"),
            ("8.0e1", False, "Scientific notation should be invalid"),
            ("1e2", False, "Scientific notation (1e2) should be invalid"),
            ("2E3", False, "Scientific notation (2E3) should be invalid"),
            # Special float strings - should be invalid
            ("inf", False, "Infinity string should be invalid"),
            ("infinity", False, "Infinity string should be invalid"),
            ("-inf", False, "Negative infinity string should be invalid"),
            ("nan", False, "NaN string should be invalid"),
            ("NaN", False, "NaN string (uppercase) should be invalid"),
            # Complex number strings - should be invalid
            ("80+0j", False, "Complex number string should be invalid"),
            ("80j", False, "Imaginary number string should be invalid"),
            # Fraction strings - should be invalid
            ("1/2", False, "Fraction string should be invalid"),
            ("80/1", False, "Fraction string should be invalid"),
            # Unicode and special characters - Unicode digits work with int()
            ("８０", True, "Unicode digits should be valid (Python int() accepts them)"),
            ("80°", False, "String with degree symbol should be invalid"),
            ("80°C", False, "String with temperature should be invalid"),
            ("80%", False, "String with percent should be invalid"),
            ("$80", False, "String with dollar sign should be invalid"),
            ("80€", False, "String with euro symbol should be invalid"),
            # Edge case valid strings with unusual formatting
            ("+80", True, "Positive sign should be valid"),
            ("00080", True, "Multiple leading zeros should be valid"),
            # Additional invalid formats
            ("80.0.0", False, "Multiple decimal points should be invalid"),
            ("80..0", False, "Double decimal point should be invalid"),
            ("80,000", False, "Comma separator should be invalid"),
            ("80_000", False, "Underscore separator should be invalid"),
            ("80 000", False, "Space separator should be invalid"),
        ],
    )
    def test_validate_port_string_edge_cases(self, port_string, expected, description):
        """Test validate_port with string edge cases that could cause int() conversion issues."""
        result = validate_port(port_string)
        assert result is expected, f"Failed for {description}: validate_port({port_string!r}) returned {result}, expected {expected}"


class TestValidateFreeText:
    @pytest.mark.parametrize(
        "value,description",
        [
            ("Production organization for the EMEA region", "plain English text"),
            ("Hello world éèê üöä 你好 العربية", "Unicode and international characters"),
            ("$500 budget", "currency with dollar sign"),
            ("https://example.com/path?q=1&r=2", "HTTPS URL"),
            ("mailto:user@example.com", "mailto link"),
            ("ftp://server.local/file", "FTP URL"),
            ("Tab\there, newline\nhere", "tab and newline whitespace"),
            ("`backtick code`", "backtick markdown"),
            ("on= something, one=thing", "short 'on' prefixes (not event handlers)"),
            ("$var without braces", "bare dollar variable"),
            ("", "empty string"),
            ("a" * 10000, "very long plain text"),
            ("Config: key=value, on=true", "on= with only two chars after 'on'"),
            ("line one\r\nline two", "Windows CRLF line endings"),
            ("line one\rline two", "bare carriage return"),
            ("R&D department", "ampersand in prose"),
            ("100% complete", "percent sign in prose"),
            ("5 < 10 and 10 > 5", "bare angle brackets in math"),
            ("AT&T is a company", "ampersand in company name"),
            ("Sample data: 42", "prose with data colon"),
            ("data: received at 10:00", "data colon in sentence"),
            ("data:image/png;base64,iVBORw0KGgo=", "data URI with safe image MIME type"),
            ("Persian: ‌word", "ZWNJ for Persian/Arabic letter joining"),
            ("mixed ‎dir text", "LTR mark in mixed-direction text"),
            ("mixed ‏dir text", "RTL mark in mixed-direction text"),
            ("‪hello‬", "LTR embedding with pop"),
            ("⁦hello⁩", "bidi isolate with pop"),
        ],
    )
    def test_accepts_valid_text(self, value, description):
        validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("<script>alert(1)</script>", "script tag"),
            ("<SCRIPT>alert(1)</SCRIPT>", "script tag uppercase"),
            ("< script >alert(1)", "script tag with spaces"),
            ("</script>", "closing script tag"),
            ("<iframe src=x>", "iframe tag"),
            ("</iframe>", "closing iframe tag"),
            ("<object data=x>", "object tag"),
            ("<embed src=x>", "embed tag"),
            ("<form action=x>", "form tag"),
            ("<base href=x>", "base tag"),
            ("<meta http-equiv=refresh>", "meta tag"),
            ("<link rel=stylesheet>", "link tag"),
            ("<svg onload=alert(1)>", "svg tag"),
            ('<svg onload="alert(1)">', "svg tag with quoted attribute"),
            ("<math><mtext>xss</mtext></math>", "math tag"),
            ("<template>injection</template>", "template tag"),
            ("＜script＞alert(1)", "fullwidth angle bracket bypass"),
            ("<b>bold</b>", "bold tag"),
            ("<em>emphasis</em>", "emphasis tag"),
            ("<br>", "line break tag"),
            ("<img src=photo.jpg>", "img tag"),
            ("<details>expandable section</details>", "details tag"),
            ("<p>paragraph</p>", "paragraph tag"),
        ],
    )
    def test_rejects_html_tags(self, value, description):
        with pytest.raises(ValidationError):
            validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("%3Cscript%3Ealert(1)%3C/script%3E", "percent-encoded script tag"),
            ("&#60;script&#62;alert(1)&#60;/script&#62;", "HTML-entity script tag"),
            ("&#36;(whoami)", "HTML-entity shell substitution"),
            ("%24%7BPATH%7D", "percent-encoded variable expansion"),
            ("%3Ciframe%20src%3Dx%3E", "percent-encoded iframe tag"),
            ("＜ｓｃｒｉｐｔ＞alert(1)", "fullwidth chars that NFKC-fold to script tag"),
            ("ｊａｖａｓｃｒｉｐｔ:alert(1)", "fullwidth javascript URI scheme with ASCII colon"),
            ("ｊａｖａｓｃｒｉｐｔ：alert(1)", "fullwidth javascript URI scheme with fullwidth colon U+FF1A"),
            ("&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;", "double entity-encoded script tag"),
        ],
    )
    def test_rejects_encoded_bypass_attempts(self, value, description):
        with pytest.raises(ValidationError):
            validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("onerror=alert(1)", "bare onerror not inside a tag"),
            ("onclick=doStuff()", "bare onclick not inside a tag"),
            ("onload=init()", "bare onload not inside a tag"),
            ("onmouseover=alert(1)", "bare onmouseover not inside a tag"),
            ("ONERROR=alert(1)", "bare onerror uppercase not inside a tag"),
            ("online=true", "prose containing on-prefix word"),
        ],
    )
    def test_allows_bare_event_handler_like_strings(self, value, description):
        validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("javascript:alert(1)", "javascript protocol"),
            ("JAVASCRIPT:void(0)", "javascript protocol uppercase"),
            ("vbscript:MsgBox", "vbscript protocol"),
            ("data:text/html,<h1>hi</h1>", "data URI with markup caught by _contains_markup"),
            ("data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==", "data URI base64-encoded script"),
            ("data:text/javascript,alert(1)", "data URI with javascript MIME"),
            ("data:application/javascript,alert(1)", "data URI with application/javascript MIME"),
            ("data:application/xhtml+xml,<x/>", "data URI with xhtml+xml MIME"),
            ("DATA:TEXT/HTML,<b>x</b>", "data URI uppercase"),
            ("data:image/svg+xml;base64,PHN2ZyBvbmxvYWQ9YWxlcnQoMSk+", "data URI with SVG MIME type"),
            ("data:application/xml;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==", "data URI with application/xml MIME"),
            ("data:text/xml;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==", "data URI with text/xml MIME"),
            ("data:text/ecmascript,alert(1)", "data URI with text/ecmascript MIME"),
            ("data:application/ecmascript,alert(1)", "data URI with application/ecmascript MIME"),
            ("data:text/x-javascript,alert(1)", "data URI with text/x-javascript MIME"),
            ("data:text/jscript,alert(1)", "data URI with text/jscript MIME"),
            ("data:text/livescript,alert(1)", "data URI with text/livescript MIME"),
            ("data:text/javascript1.5,alert(1)", "data URI with versioned JS MIME type"),
        ],
    )
    def test_rejects_dangerous_uri_schemes(self, value, description):
        with pytest.raises(ValidationError):
            validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("jav\tascript:alert(1)", "tab in javascript scheme"),
            ("jav\nascript:alert(1)", "LF in javascript scheme"),
            ("jav\rascript:alert(1)", "CR in javascript scheme"),
            ("vb\tscript:MsgBox", "tab in vbscript scheme"),
            ("java\t\nscript:alert(1)", "mixed tab+LF in scheme"),
        ],
    )
    def test_rejects_uri_scheme_with_whatwg_stripped_chars(self, value, description):
        """WHATWG URL parser strips tab/LF/CR from scheme names before matching."""
        with pytest.raises(ValidationError):
            validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("$(whoami)", "command substitution"),
            ("$(cat /etc/passwd)", "command substitution with path"),
            ("${PATH}", "variable expansion"),
            ("${USER}", "variable expansion USER"),
        ],
    )
    def test_rejects_shell_substitution(self, value, description):
        with pytest.raises(ValidationError):
            validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("\x00 null byte", "null byte"),
            ("\x08 backspace", "backspace"),
            ("\x1b[31m red", "ANSI escape sequence"),
            ("\x7f DEL", "DEL character"),
            ("\x80 C1 control", "C1 control character"),
            ("\x9f end of C1", "C1 block end"),
            ("​ zero-width space", "zero-width space"),
            ("\u202d left-to-right override", "LRO Trojan Source"),
            ("\u202e right-to-left override", "RLO Trojan Source"),
            ("⁠ word joiner", "invisible operator"),
            ("⁡ function application", "invisible operator"),
            ("⁪ inhibit symmetric", "deprecated formatting"),
            ("⁯ nominal digit shapes", "deprecated formatting"),
            ("﻿ BOM", "byte order mark"),
            ("￹ annotation anchor", "interlinear annotation"),
        ],
    )
    def test_rejects_control_characters(self, value, description):
        with pytest.raises(ValidationError):
            validate_free_text(value)

    @pytest.mark.parametrize(
        "value,description",
        [
            ("{{ config }}", "Jinja2 expression"),
            ("{% import os %}", "Jinja2 tag"),
            ("{{ settings.SECRET_KEY }}", "Jinja2 secret access"),
        ],
    )
    def test_rejects_template_injection(self, value, description):
        with pytest.raises(ValidationError):
            validate_free_text(value)

    @pytest.mark.parametrize(
        "value",
        [None, 42, 3.14, [], {}],
    )
    def test_skips_non_string_values(self, value):
        validate_free_text(value)

    def test_error_message_markup(self):
        with pytest.raises(ValidationError, match="HTML tags"):
            validate_free_text("<script>alert(1)</script>")

    def test_error_message_control(self):
        with pytest.raises(ValidationError, match="control characters"):
            validate_free_text("\x00 null")

    def test_error_message_injection(self):
        with pytest.raises(ValidationError, match="shell or template"):
            validate_free_text("$(whoami)")


class TestValidateResourceName:
    """Test the validate_resource_name function."""

    # Valid names should pass validation
    @pytest.mark.parametrize(
        "name",
        [
            "simple",  # basic word
            "My Production Organization",  # spaces
            "deploy-staging-2",  # hyphens and numbers
            "user@domain.com",  # @ and dots
            "_internal_name",  # underscores
            "CamelCaseName",  # mixed case
            "123numeric",  # starts with number
            "mixed 123 name-with.all@types",  # kitchen sink
            "équipe",  # unicode (French)
            "チーム名",  # unicode (Japanese)
            "Проект",  # unicode (Russian)
            "a",  # single character
        ],
    )
    def test_valid_names(self, name):
        validate_resource_name(name)

    def test_accepts_max_length_name(self):
        # Exactly 512 characters (at the limit)
        max_name = "a" * 512
        validate_resource_name(max_name)

    # Security injection attacks should be rejected
    @pytest.mark.parametrize(
        "name",
        [
            "<script>alert(1)</script>",  # XSS
            '<img src=x onerror="alert(1)">',  # HTML injection
            "$(whoami)",  # shell substitution
            "`id`",  # backtick execution
            "name; rm -rf /",  # shell command
            "'; DROP TABLE users--",  # SQL injection
            "1 OR 1=1",  # SQL boolean bypass
            "name)(cn=*))(|(cn=*",  # LDAP injection
            "../../../etc/passwd",  # path traversal
            "/etc/shadow",  # absolute path
            "name\x00injected",  # null byte injection
            "\x1b[31mred\x1b[0m",  # ANSI escape sequences
        ],
    )
    def test_rejects_injection_attacks(self, name):
        with pytest.raises(ValidationError):
            validate_resource_name(name)

    # Invalid patterns should be rejected
    @pytest.mark.parametrize(
        "name",
        [
            # Invalid starting characters
            " leading-space",  # starts with space
            "-leading-hyphen",  # starts with hyphen
            ".leading-dot",  # starts with dot
            "@leading-at",  # starts with @
            # Whitespace issues
            "valid-name\n",  # trailing newline
            "line1\nline2",  # embedded newline
            "name\twith\ttabs",  # tab characters
        ],
    )
    def test_rejects_invalid_patterns(self, name):
        with pytest.raises(ValidationError):
            validate_resource_name(name)

    def test_rejects_empty_string(self):
        with pytest.raises(ValidationError):
            validate_resource_name("")

    def test_rejects_too_long_name(self):
        # 513 characters (1 over the 512 limit)
        long_name = "a" * 513
        with pytest.raises(ValidationError):
            validate_resource_name(long_name)

    @pytest.mark.parametrize("value", [None, 42, 3.14, [], {}])
    def test_rejects_non_string_values(self, value):
        with pytest.raises(ValidationError, match="valid name"):
            validate_resource_name(value)

    # Error handling tests
    def test_error_message_is_descriptive(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_resource_name("<script>")
        message = str(exc_info.value.detail[0])
        assert "valid name" in message
        assert "letter, number, or underscore" in message

    @pytest.mark.parametrize(
        "name,script",
        [
            ("राम", "Devanagari (Ram)"),
            ("कृष्ण", "Devanagari (Krishna)"),
            ("तमिऴ्", "Tamil (Tamil)"),
            ("বাংলা", "Bengali (Bangla)"),
            ("तेलुगु", "Telugu (Telugu)"),
            ("ಕನ್ನಡ", "Kannada (Kannada)"),
            ("മലയാളം", "Malayalam (Malayalam)"),
            ("ਪੰਜਾਬੀ", "Gurmukhi (Punjabi)"),
            ("ଓଡ଼ିଆ", "Odia (Odia)"),
        ],
    )
    def test_valid_indic_names(self, name, script):
        validate_resource_name(name)

    def test_rejects_zalgo_text(self):
        zalgo_5 = "x\u0300\u0301\u0302\u0303\u0304"
        with pytest.raises(ValidationError, match="combining marks"):
            validate_resource_name(zalgo_5)
        zalgo_7 = "x\u0300\u0301\u0302\u0303\u0304\u0305\u0306"
        with pytest.raises(ValidationError, match="combining marks"):
            validate_resource_name(zalgo_7)

    def test_rejects_interleaved_zalgo_text(self):
        interleaved = "x\u0300\u0301\u0302\u0303 \u0304\u0305\u0306\u0307"
        with pytest.raises(ValidationError, match="combining marks"):
            validate_resource_name(interleaved)

    def test_accepts_normal_combining_marks(self):
        validate_resource_name("\u0915\u0943\u0937\u094d\u0923")
        validate_resource_name("x\u0300\u0301\u0302\u0303")

    @pytest.mark.parametrize(
        "name,description",
        [
            ("a\u034f", "Combining Grapheme Joiner"),
            ("a\ufe00", "Variation Selector 1"),
            ("a\ufe0f", "Variation Selector 16"),
            ("a\u17b4", "Khmer invisible vowel 1"),
            ("a\u17b5", "Khmer invisible vowel 2"),
            ("a\u180b", "Mongolian free variation selector 1"),
            ("a\u00ad", "Soft hyphen"),
            ("a\u200b", "Zero-width space"),
            ("a\u2060", "Word joiner"),
            ("a\ufeff", "Zero-width no-break space / BOM"),
        ],
    )
    def test_rejects_invisible_characters(self, name, description):
        with pytest.raises(ValidationError, match="invisible characters"):
            validate_resource_name(name)

    def test_nfc_normalization(self):
        composed = "équipe"
        decomposed = "équipe"
        validate_resource_name(composed)
        validate_resource_name(decomposed)

    # Import path verification
    def test_importable_from_utils_validation(self):
        from ansible_base.lib.utils.validation import validate_resource_name as validator

        assert validator is not None
        assert callable(validator)
