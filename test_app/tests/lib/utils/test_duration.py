import pytest

from ansible_base.lib.utils.duration import convert_to_seconds


@pytest.mark.parametrize(
    "duration_string, expected",
    [
        # Test Seconds
        ('15s', 15),
        ('1s', 1),
        ('0s', 0),  # Zero is now allowed
        # Test minutes
        ('5m', 300),  # 5 * 60
        ('1m', 60),
        ('10m', 600),
        # Test hours
        ('1h', 3600),  # 1 * 3600
        ('2h', 7200),  # 2 * 3600
        ('24h', 86400),  # 24 * 3600
        # Test days
        ('1d', 86400),  # 1 * 86400
        ('7d', 604800),  # 7 * 86400
        ('30d', 2592000),  # 30 * 86400
        # Test weeks
        ('1w', 604800),  # 1 * 604800
        ('2w', 1209600),  # 2 * 604800
        ('4w', 2419200),  # 4 * 604800
        # Test without unit
        ('30', 30),
        ('120', 120),
        ('0', 0),  # Zero is now allowed
        # Test uppercase
        ('15S', 15),
        ('5M', 300),
        ('1H', 3600),
        ('1D', 86400),
        ('1W', 604800),
        # Test negative values (now supported)
        ('-5s', -5),
        ('-10m', -600),
        ('-1h', -3600),
        ('-2d', -172800),
        ('-1w', -604800),
        ('-10', -10),
        ('-1s', -1),
        ('-3d', -259200),
        ('-2w', -1209600),
        ('-100', -100),
        # Test very large numbers
        ('999999s', 999999),
        ('100000m', 6000000),
        ('1000h', 3600000),
        # Test with spaces (int() strips whitespace from numbers)
        ('15 s', 15),  # int('15 ') succeeds
        (' 15s', 15),  # int(' 15') succeeds
        # Test invalid values that return default
        ('invalid', 10),
        ('xs', 10),
        ('', 10),
        ('15s ', 10),  # Trailing space after unit fails
        (' ', 10),  # Just spaces
        ('s', 10),  # Single unit character
        ('m', 10),
        ('h', 10),
        ('d', 10),
        ('w', 10),
        ('-', 10),  # Just minus
        ('10-', 10),  # Ends with minus
        ('100-', 10),
        ('1.5s', 10),  # Float values
        ('2.5m', 10),
        ('0.5h', 10),
        ('15@', 10),  # Special characters
        ('10#s', 10),
        ('!@#$', 10),
        ('5*m', 10),
    ],
)
def test_convert_to_seconds(duration_string, expected):
    """Test convert_to_seconds with various inputs including edge cases."""
    assert convert_to_seconds(duration_string) == expected


def test_convert_to_seconds_with_none():
    """Test convert_to_seconds with None value."""
    assert convert_to_seconds(None) == 10


@pytest.mark.parametrize(
    "duration_string, default, expected",
    [
        # Test custom default with invalid inputs
        ('invalid', 30, 30),
        ('', 30, 30),
        (None, 30, 30),
        ('xyz', 30, 30),
        ('10-', 20, 20),  # String ending with minus
        ('0s', 5, 0),  # Valid input ignores custom default
        ('5m', 100, 300),  # Valid input ignores custom default
    ],
)
def test_convert_to_seconds_custom_default(duration_string, default, expected):
    """Test convert_to_seconds with custom default values."""
    assert convert_to_seconds(duration_string, default=default) == expected
