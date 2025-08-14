import uuid

import pytest

from ansible_base.lib.utils.converters import IntOrUUIDConverter


class TestIntOrUUIDConverter:
    """Test cases for the IntOrUUIDConverter class."""

    def test_regex_pattern(self):
        """Test that the regex pattern is correctly defined."""
        converter = IntOrUUIDConverter()
        assert converter.regex == "([0-9]+|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"

    @pytest.mark.parametrize(
        "value,expected_type,expected_value",
        [
            # Integer cases
            ("1", int, 1),
            ("123", int, 123),
            ("999999", int, 999999),
            ("0", int, 0),
            # UUID cases
            ("550e8400-e29b-41d4-a716-446655440000", uuid.UUID, uuid.UUID("550e8400-e29b-41d4-a716-446655440000")),
            ("6ba7b810-9dad-11d1-80b4-00c04fd430c8", uuid.UUID, uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")),
            ("6ba7b811-9dad-11d1-80b4-00c04fd430c8", uuid.UUID, uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")),
            # UUID without dashes (valid format for uuid.UUID)
            ("550e8400e29b41d4a716446655440000", uuid.UUID, uuid.UUID("550e8400e29b41d4a716446655440000")),
        ],
    )
    def test_to_python_valid_values(self, value, expected_type, expected_value):
        """Test that valid integers and UUIDs are correctly converted."""
        converter = IntOrUUIDConverter()
        result = converter.to_python(value)
        assert isinstance(result, expected_type)
        assert result == expected_value

    @pytest.mark.parametrize(
        "invalid_value",
        [
            # Invalid integers (negative or with non-digits)
            "-1",
            "12.34",
            "1.0",
            "12a",
            "a12",
            # Invalid UUIDs
            "not-a-uuid",
            "550e8400-e29b-41d4-a716",  # Too short
            "550e8400-e29b-41d4-a716-446655440000-extra",  # Too long
            "550e8400-e29b-41d4-a716-44665544000z",  # Invalid character
            # Note: "550e8400e29b41d4a716446655440000" (missing dashes) is actually valid for uuid.UUID()
            # Empty/None cases
            "",
            "   ",
            # Mixed invalid cases
            "name",
            "name surname",
            "123-456",
            "uuid-like-string",
            "12345-67890-abcde",
        ],
    )
    def test_to_python_invalid_values(self, invalid_value):
        """Test that invalid values raise ValueError."""
        converter = IntOrUUIDConverter()
        with pytest.raises(ValueError) as exc_info:
            converter.to_python(invalid_value)
        assert f"'{invalid_value}' is not a valid integer or UUID" in str(exc_info.value)

    def test_to_python_large_integer(self):
        """Test that very large integers are handled correctly."""
        converter = IntOrUUIDConverter()
        large_int_str = "999999999999999999999"
        result = converter.to_python(large_int_str)
        assert isinstance(result, int)
        assert result == int(large_int_str)

    @pytest.mark.parametrize(
        "input_value,expected_output",
        [
            # Integer inputs
            (1, "1"),
            (123, "123"),
            (0, "0"),
            (999999, "999999"),
            # UUID inputs
            (uuid.UUID("550e8400-e29b-41d4-a716-446655440000"), "550e8400-e29b-41d4-a716-446655440000"),
            (uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"), "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
            # String inputs (should work with str() call)
            ("test", "test"),
            ("123", "123"),
        ],
    )
    def test_to_url(self, input_value, expected_output):
        """Test that various types are correctly converted to URL strings."""
        converter = IntOrUUIDConverter()
        result = converter.to_url(input_value)
        assert result == expected_output
        assert isinstance(result, str)

    def test_to_python_int_priority(self):
        """Test that numeric strings are treated as integers, not UUIDs."""
        converter = IntOrUUIDConverter()
        # This string could theoretically be interpreted as a UUID segment,
        # but should be treated as an integer since it's all digits
        result = converter.to_python("12345678")
        assert isinstance(result, int)
        assert result == 12345678

    def test_uuid_case_handling(self):
        """Test UUID case handling - uppercase UUIDs are actually valid in uuid.UUID()."""
        converter = IntOrUUIDConverter()

        # Test with uppercase UUID - uuid.UUID() accepts uppercase
        uppercase_uuid = "550E8400-E29B-41D4-A716-446655440000"
        result = converter.to_python(uppercase_uuid)
        assert isinstance(result, uuid.UUID)
        # UUID string representation is always lowercase
        assert str(result) == "550e8400-e29b-41d4-a716-446655440000"

        # Test with lowercase UUID (should work)
        lowercase_uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = converter.to_python(lowercase_uuid)
        assert isinstance(result, uuid.UUID)
        assert str(result) == lowercase_uuid

    def test_uuid_validation_error_handling(self):
        """Test that UUID validation errors are properly caught and re-raised."""
        converter = IntOrUUIDConverter()

        # Test with a string that's not digits but also not a valid UUID
        invalid_uuid = "this-is-not-a-uuid-at-all"
        with pytest.raises(ValueError) as exc_info:
            converter.to_python(invalid_uuid)
        assert f"'{invalid_uuid}' is not a valid integer or UUID" in str(exc_info.value)

    def test_roundtrip_conversion(self):
        """Test that to_python and to_url work correctly together."""
        converter = IntOrUUIDConverter()

        # Test integer roundtrip
        int_str = "12345"
        int_val = converter.to_python(int_str)
        url_str = converter.to_url(int_val)
        assert url_str == int_str

        # Test UUID roundtrip
        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        uuid_val = converter.to_python(uuid_str)
        url_str = converter.to_url(uuid_val)
        assert url_str == uuid_str
