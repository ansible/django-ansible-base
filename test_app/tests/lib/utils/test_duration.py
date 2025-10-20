"""
Tests for ansible_base.lib.utils.duration module.
"""

import pytest

from ansible_base.lib.utils.duration import convert_to_seconds


@pytest.mark.parametrize(
    "duration_input,expected_seconds",
    [
        # Positive seconds
        pytest.param("15s", 15, id="positive_15_seconds"),
        pytest.param("0s", 0, id="zero_seconds"),
        pytest.param("1s", 1, id="one_second"),
        pytest.param("100s", 100, id="positive_100_seconds"),
        # Positive minutes
        pytest.param("5m", 300, id="positive_5_minutes"),
        pytest.param("0m", 0, id="zero_minutes"),
        pytest.param("1m", 60, id="one_minute"),
        pytest.param("10m", 600, id="positive_10_minutes"),
        # Positive hours
        pytest.param("1h", 3600, id="one_hour"),
        pytest.param("0h", 0, id="zero_hours"),
        pytest.param("2h", 7200, id="positive_2_hours"),
        pytest.param("24h", 86400, id="positive_24_hours"),
        # Positive days
        pytest.param("2d", 172800, id="positive_2_days"),
        pytest.param("0d", 0, id="zero_days"),
        pytest.param("1d", 86400, id="one_day"),
        pytest.param("7d", 604800, id="positive_7_days"),
        # Positive weeks
        pytest.param("1w", 604800, id="one_week"),
        pytest.param("0w", 0, id="zero_weeks"),
        pytest.param("2w", 1209600, id="positive_2_weeks"),
        pytest.param("4w", 2419200, id="positive_4_weeks"),
        # Plain integers (treated as seconds)
        pytest.param("30", 30, id="plain_integer_30"),
        pytest.param("0", 0, id="plain_integer_zero"),
        pytest.param("100", 100, id="plain_integer_100"),
        pytest.param("1", 1, id="plain_integer_1"),
        # Negative seconds
        pytest.param("-5s", -5, id="negative_5_seconds"),
        pytest.param("-1s", -1, id="negative_1_second"),
        pytest.param("-100s", -100, id="negative_100_seconds"),
        # Negative minutes
        pytest.param("-5m", -300, id="negative_5_minutes"),
        pytest.param("-1m", -60, id="negative_1_minute"),
        pytest.param("-10m", -600, id="negative_10_minutes"),
        # Negative hours
        pytest.param("-1h", -3600, id="negative_1_hour"),
        pytest.param("-2h", -7200, id="negative_2_hours"),
        pytest.param("-24h", -86400, id="negative_24_hours"),
        # Negative days
        pytest.param("-1d", -86400, id="negative_1_day"),
        pytest.param("-2d", -172800, id="negative_2_days"),
        pytest.param("-7d", -604800, id="negative_7_days"),
        # Negative weeks
        pytest.param("-1w", -604800, id="negative_1_week"),
        pytest.param("-2w", -1209600, id="negative_2_weeks"),
        # Negative plain integers
        pytest.param("-30", -30, id="negative_plain_integer_30"),
        pytest.param("-1", -1, id="negative_plain_integer_1"),
        pytest.param("-100", -100, id="negative_plain_integer_100"),
        # Case-insensitive units
        pytest.param("15S", 15, id="uppercase_S_seconds"),
        pytest.param("5M", 300, id="uppercase_M_minutes"),
        pytest.param("1H", 3600, id="uppercase_H_hours"),
        pytest.param("2D", 172800, id="uppercase_D_days"),
        pytest.param("1W", 604800, id="uppercase_W_weeks"),
        # Large numbers
        pytest.param("999s", 999, id="large_999_seconds"),
        pytest.param("999m", 59940, id="large_999_minutes"),
        pytest.param("999h", 3596400, id="large_999_hours"),
        pytest.param("365d", 31536000, id="large_365_days"),
        pytest.param("52w", 31449600, id="large_52_weeks"),
    ],
)
def test_convert_to_seconds_valid_inputs(duration_input, expected_seconds):
    """Test convert_to_seconds with valid duration strings."""
    assert convert_to_seconds(duration_input) == expected_seconds


@pytest.mark.parametrize(
    "invalid_input,default_value,expected_result",
    [
        # Invalid string inputs
        pytest.param("invalid", 10, 10, id="invalid_string_with_default_10"),
        pytest.param("", 10, 10, id="empty_string_with_default_10"),
        pytest.param("-", 10, 10, id="lone_minus_sign_with_default_10"),
        pytest.param("s", 10, 10, id="unit_only_s_with_default_10"),
        pytest.param("abc", 10, 10, id="alphabetic_string_with_default_10"),
        pytest.param("15x", 10, 10, id="invalid_unit_x_with_default_10"),
        pytest.param("m", 10, 10, id="unit_only_m_with_default_10"),
        pytest.param("12.5s", 10, 10, id="float_not_supported_with_default_10"),
        pytest.param("1h30m", 10, 10, id="multiple_units_not_supported_with_default_10"),
        pytest.param(None, 10, 10, id="none_input_with_default_10"),
        # Custom default values
        pytest.param("invalid", 0, 0, id="invalid_string_with_default_0"),
        pytest.param("invalid", 100, 100, id="invalid_string_with_default_100"),
        pytest.param("invalid", -1, -1, id="invalid_string_with_default_negative_1"),
        # Empty value with unit and custom default
        pytest.param("s", 42, 42, id="unit_only_s_with_default_42"),
        pytest.param("m", 42, 42, id="unit_only_m_with_default_42"),
        # Lone minus sign with various defaults
        pytest.param("-", 42, 42, id="lone_minus_with_default_42"),
        pytest.param("-", 0, 0, id="lone_minus_with_default_0"),
        pytest.param("-", -1, -1, id="lone_minus_with_default_negative_1"),
    ],
)
def test_convert_to_seconds_invalid_inputs(invalid_input, default_value, expected_result):
    """Test convert_to_seconds with invalid inputs returns the specified default value."""
    assert convert_to_seconds(invalid_input, default=default_value) == expected_result


@pytest.mark.parametrize(
    "duration_input,expected_seconds",
    [
        pytest.param("15s", 15, id="consistency_15_seconds"),
        pytest.param("5m", 300, id="consistency_5_minutes"),
        pytest.param("1h", 3600, id="consistency_1_hour"),
        pytest.param("2d", 172800, id="consistency_2_days"),
        pytest.param("1w", 604800, id="consistency_1_week"),
        pytest.param("-5s", -5, id="consistency_negative_5_seconds"),
        pytest.param("-1h", -3600, id="consistency_negative_1_hour"),
        pytest.param("30", 30, id="consistency_plain_integer_30"),
        pytest.param("0s", 0, id="consistency_zero_seconds"),
        pytest.param("0m", 0, id="consistency_zero_minutes"),
        pytest.param("0h", 0, id="consistency_zero_hours"),
        pytest.param("0d", 0, id="consistency_zero_days"),
        pytest.param("0w", 0, id="consistency_zero_weeks"),
        pytest.param("0", 0, id="consistency_plain_integer_zero"),
    ],
)
def test_convert_to_seconds_consistency(duration_input, expected_seconds):
    """Test that convert_to_seconds returns consistent results across multiple calls."""
    result1 = convert_to_seconds(duration_input)
    result2 = convert_to_seconds(duration_input)
    result3 = convert_to_seconds(duration_input)
    assert result1 == result2 == result3 == expected_seconds
