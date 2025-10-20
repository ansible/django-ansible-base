"""
Tests for ansible_base.lib.utils.duration module.
"""

import pytest

from ansible_base.lib.utils.duration import convert_to_seconds


@pytest.mark.parametrize(
    "duration_string,expected",
    [
        # Positive seconds
        ("15s", 15),
        ("0s", 0),
        ("1s", 1),
        ("100s", 100),
        # Positive minutes
        ("5m", 300),
        ("0m", 0),
        ("1m", 60),
        ("10m", 600),
        # Positive hours
        ("1h", 3600),
        ("0h", 0),
        ("2h", 7200),
        ("24h", 86400),
        # Positive days
        ("2d", 172800),
        ("0d", 0),
        ("1d", 86400),
        ("7d", 604800),
        # Positive weeks
        ("1w", 604800),
        ("0w", 0),
        ("2w", 1209600),
        ("4w", 2419200),
        # Plain integers (treated as seconds)
        ("30", 30),
        ("0", 0),
        ("100", 100),
        ("1", 1),
        # Negative seconds
        ("-5s", -5),
        ("-1s", -1),
        ("-100s", -100),
        # Negative minutes
        ("-5m", -300),
        ("-1m", -60),
        ("-10m", -600),
        # Negative hours
        ("-1h", -3600),
        ("-2h", -7200),
        ("-24h", -86400),
        # Negative days
        ("-1d", -86400),
        ("-2d", -172800),
        ("-7d", -604800),
        # Negative weeks
        ("-1w", -604800),
        ("-2w", -1209600),
        # Negative plain integers
        ("-30", -30),
        ("-1", -1),
        ("-100", -100),
        # Case-insensitive units
        ("15S", 15),
        ("5M", 300),
        ("1H", 3600),
        ("2D", 172800),
        ("1W", 604800),
        # Large numbers
        ("999s", 999),
        ("999m", 59940),
        ("999h", 3596400),
        ("365d", 31536000),
        ("52w", 31449600),
    ],
)
def test_convert_to_seconds_valid(duration_string, expected):
    """Test convert_to_seconds with valid duration strings."""
    assert convert_to_seconds(duration_string) == expected


@pytest.mark.parametrize(
    "duration_string,default,expected",
    [
        # Invalid inputs should return default
        ("invalid", 10, 10),
        ("", 10, 10),
        ("-", 10, 10),
        ("s", 10, 10),
        ("abc", 10, 10),
        ("15x", 10, 10),
        ("m", 10, 10),
        ("12.5s", 10, 10),  # Float not supported
        ("1h30m", 10, 10),  # Multiple units not supported
        (None, 10, 10),
        # Custom defaults
        ("invalid", 0, 0),
        ("invalid", 100, 100),
        ("invalid", -1, -1),
        # Empty value with unit
        ("s", 42, 42),
        ("m", 42, 42),
    ],
)
def test_convert_to_seconds_invalid(duration_string, default, expected):
    """Test convert_to_seconds with invalid inputs returns default."""
    assert convert_to_seconds(duration_string, default=default) == expected


@pytest.mark.parametrize(
    "default,expected",
    [
        (10, 10),  # Default value when not specified
        (0, 0),  # Zero as default
        (-5, -5),  # Negative default
        (100, 100),  # Large default
        (-1, -1),  # Negative one default
    ],
)
def test_convert_to_seconds_with_defaults(default, expected):
    """Test that default parameter works correctly with various values."""
    assert convert_to_seconds("invalid", default=default) == expected


@pytest.mark.parametrize(
    "duration_string",
    [
        "15s",
        "5m",
        "1h",
        "2d",
        "1w",
        "-5s",
        "-1h",
        "30",
    ],
)
def test_convert_to_seconds_consistency(duration_string):
    """Test that convert_to_seconds returns consistent results."""
    # Call multiple times to ensure consistency
    result1 = convert_to_seconds(duration_string)
    result2 = convert_to_seconds(duration_string)
    result3 = convert_to_seconds(duration_string)
    assert result1 == result2 == result3


@pytest.mark.parametrize(
    "default,expected",
    [
        (10, 10),
        (42, 42),
        (0, 0),
        (-1, -1),
    ],
)
def test_convert_to_seconds_edge_case_just_minus(default, expected):
    """Test that a lone minus sign returns default."""
    assert convert_to_seconds("-", default=default) == expected


@pytest.mark.parametrize(
    "duration_string",
    [
        "0s",
        "0m",
        "0h",
        "0d",
        "0w",
        "0",
    ],
)
def test_convert_to_seconds_edge_case_zero_values(duration_string):
    """Test that zero values work correctly for all units."""
    assert convert_to_seconds(duration_string) == 0
