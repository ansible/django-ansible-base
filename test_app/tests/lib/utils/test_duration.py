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
    ],
)
def test_convert_to_seconds_invalid_inputs(invalid_input, default_value, expected_result):
    """Test convert_to_seconds with invalid inputs returns the specified default value."""
    assert convert_to_seconds(invalid_input, default=default_value) == expected_result


@pytest.mark.parametrize(
    "duration_input,default_value,expected_result",
    [
        # Test 1: Invalid input, no custom default → returns function default (10)
        pytest.param("invalid", 10, 10, id="invalid_no_custom_default_returns_10"),
        pytest.param("", 10, 10, id="empty_no_custom_default_returns_10"),
        pytest.param(None, 10, 10, id="none_no_custom_default_returns_10"),
        # Test 2: Invalid input, custom default → returns custom default (not 10)
        pytest.param("invalid", 0, 0, id="invalid_custom_default_0"),
        pytest.param("invalid", 42, 42, id="invalid_custom_default_42"),
        pytest.param("invalid", 100, 100, id="invalid_custom_default_100"),
        pytest.param("invalid", -1, -1, id="invalid_custom_default_negative_1"),
        pytest.param("-", 42, 42, id="lone_minus_custom_default_42"),
        pytest.param("s", 99, 99, id="unit_only_custom_default_99"),
        # Test 3: Valid input, no custom default → returns converted value (ignores implicit 10)
        pytest.param("15s", 10, 15, id="valid_15s_no_custom_default"),
        pytest.param("5m", 10, 300, id="valid_5m_no_custom_default"),
        pytest.param("0", 10, 0, id="valid_0_no_custom_default"),
        # Test 4: Valid input, custom default → returns converted value (ignores custom default)
        pytest.param("15s", 999, 15, id="valid_15s_ignores_custom_default_999"),
        pytest.param("5m", 42, 300, id="valid_5m_ignores_custom_default_42"),
        pytest.param("1h", 0, 3600, id="valid_1h_ignores_custom_default_0"),
        pytest.param("2d", -1, 172800, id="valid_2d_ignores_custom_default_negative_1"),
        pytest.param("30", 100, 30, id="valid_plain_30_ignores_custom_default_100"),
        pytest.param("-5s", 999, -5, id="valid_negative_5s_ignores_custom_default_999"),
        pytest.param("0s", 42, 0, id="valid_0s_ignores_custom_default_42"),
    ],
)
def test_convert_to_seconds_default_behavior(duration_input, default_value, expected_result):
    """
    Test all default parameter scenarios in one comprehensive test.

    This test covers four key scenarios:
    1. Invalid input with function's default (10) → returns 10
    2. Invalid input with custom default → returns custom default
    3. Valid input with function's default (10) → returns converted value, ignores 10
    4. Valid input with custom default → returns converted value, ignores custom default
    """
    assert convert_to_seconds(duration_input, default=default_value) == expected_result


@pytest.mark.parametrize(
    "invalid_default_value,expected_result",
    [
        # Boolean defaults (bool is subclass of int in Python, so needs explicit check)
        pytest.param(True, 10, id="bool_true_logs_warning_returns_10"),
        pytest.param(False, 10, id="bool_false_logs_warning_returns_10"),
    ],
)
def test_convert_to_seconds_invalid_default_type(invalid_default_value, expected_result, caplog):
    """
    Test that non-integer default values log a warning with stack trace and use 10 instead.

    Note: Only booleans are tested here because bool is a subclass of int in Python,
    so it passes isinstance(x, int) checks but should not be accepted as defaults.

    The stack_info=True in the logger call provides developers with a full stack trace
    showing exactly where convert_to_seconds was called with an invalid default.
    """
    import logging

    with caplog.at_level(logging.WARNING):
        result = convert_to_seconds("invalid", default=invalid_default_value)

    assert result == expected_result
    assert "Invalid default value" in caplog.text
    assert "Must be an integer" in caplog.text
    assert "Using default of 10" in caplog.text
    # Verify stack trace is included
    assert "Stack (most recent call last)" in caplog.text
