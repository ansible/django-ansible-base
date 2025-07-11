from ansible_base.lib.utils.collection import dict_cartesian_product


class TestDictCartesianProduct:
    """
    Test the main dict_cartesian_product function.

    AI assisted
    """

    def test_basic_functionality(self):
        """Test basic cartesian product generation."""
        data = {"role": ["a", "b"], "organization": ["z", "y", "x"], "team": ["1", "2", "3"]}

        result = dict_cartesian_product(data)

        # Should have 2 * 3 * 3 = 18 combinations
        assert len(result) == 18

        # First combination should be first element of each list
        expected_first = {"role": "a", "organization": "z", "team": "1"}
        assert result[0] == expected_first

        # Last combination should be last element of each list
        expected_last = {"role": "b", "organization": "x", "team": "3"}
        assert result[-1] == expected_last

    def test_single_key(self):
        """Test with a single key."""
        data = {"role": ["admin", "user"]}
        result = dict_cartesian_product(data)

        expected = [{"role": "admin"}, {"role": "user"}]
        assert result == expected

    def test_single_value_per_key(self):
        """Test with single values in each list."""
        data = {"role": ["admin"], "team": ["dev"], "org": ["company"]}
        result = dict_cartesian_product(data)

        expected = [{"role": "admin", "team": "dev", "org": "company"}]
        assert result == expected

    def test_empty_dictionary(self):
        """Test with empty dictionary."""
        result = dict_cartesian_product({})
        assert result == []

    def test_empty_list_value(self):
        """Test with an empty list as a value."""
        data = {"role": ["admin"], "team": [], "org": ["company"]}  # Empty list
        result = dict_cartesian_product(data)
        assert result == []

    def test_mixed_data_types(self):
        """Test with mixed data types in values."""
        data = {"role": ["admin", "user"], "active": [True, False], "priority": [1, 2, 3], "score": [0.5, 1.0]}

        result = dict_cartesian_product(data)

        # Should have 2 * 2 * 3 * 2 = 24 combinations
        assert len(result) == 24

        # Check that types are preserved
        first_combo = result[0]
        assert isinstance(first_combo["role"], str)
        assert isinstance(first_combo["active"], bool)
        assert isinstance(first_combo["priority"], int)
        assert isinstance(first_combo["score"], float)
