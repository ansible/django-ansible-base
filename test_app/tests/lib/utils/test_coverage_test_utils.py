"""
Tests for coverage_test_utils module.
"""

import pytest

from ansible_base.lib.utils.coverage_test_utils import validate_quality_gate


class TestValidateQualityGate:
    """Test suite for validate_quality_gate function."""

    def test_coverage_passes_at_threshold(self):
        """Test coverage exactly at 80% threshold passes."""
        result = validate_quality_gate(80.0)

        assert result["passes_gate"] is True
        assert result["current_coverage"] == 80.0
        assert result["required_coverage"] == 80.0
        assert result["coverage_gap"] == 0.0
        assert "meets the 80.0% threshold" in result["message"]

    def test_coverage_above_threshold(self):
        """Test coverage above threshold passes."""
        result = validate_quality_gate(90.0)

        assert result["passes_gate"] is True
        assert result["current_coverage"] == 90.0
        assert result["coverage_gap"] == 0.0

    def test_coverage_below_threshold(self):
        """Test coverage below threshold fails."""
        result = validate_quality_gate(70.0)

        assert result["passes_gate"] is False
        assert result["current_coverage"] == 70.0
        assert result["coverage_gap"] == 10.0
        assert "below the 80.0% threshold by 10.00%" in result["message"]

    def test_zero_coverage(self):
        """Test 0% coverage fails."""
        result = validate_quality_gate(0.0)

        assert result["passes_gate"] is False
        assert result["coverage_gap"] == 80.0

    def test_perfect_coverage(self):
        """Test 100% coverage passes."""
        result = validate_quality_gate(100.0)

        assert result["passes_gate"] is True
        assert result["coverage_gap"] == 0.0

    def test_custom_threshold(self):
        """Test with custom threshold."""
        result = validate_quality_gate(75.0, threshold=70.0)

        assert result["passes_gate"] is True
        assert result["required_coverage"] == 70.0
        assert result["coverage_gap"] == 0.0

    def test_custom_threshold_fails(self):
        """Test failing with custom threshold."""
        result = validate_quality_gate(65.0, threshold=70.0)

        assert result["passes_gate"] is False
        assert result["required_coverage"] == 70.0
        assert result["coverage_gap"] == 5.0

    def test_invalid_coverage_negative(self):
        """Test that negative coverage raises ValueError."""
        with pytest.raises(ValueError, match="Coverage percentage must be between 0 and 100"):
            validate_quality_gate(-5.0)

    def test_invalid_coverage_over_100(self):
        """Test that coverage over 100 raises ValueError."""
        with pytest.raises(ValueError, match="Coverage percentage must be between 0 and 100"):
            validate_quality_gate(105.0)

    def test_invalid_threshold_negative(self):
        """Test that negative threshold raises ValueError."""
        with pytest.raises(ValueError, match="Threshold must be between 0 and 100"):
            validate_quality_gate(80.0, threshold=-5.0)

    def test_invalid_threshold_over_100(self):
        """Test that threshold over 100 raises ValueError."""
        with pytest.raises(ValueError, match="Threshold must be between 0 and 100"):
            validate_quality_gate(80.0, threshold=105.0)

    def test_edge_case_at_boundary(self):
        """Test edge case at exact threshold boundary."""
        result = validate_quality_gate(80.0, threshold=80.0)

        assert result["passes_gate"] is True
        assert result["coverage_gap"] == 0.0

    def test_just_below_threshold(self):
        """Test coverage just below threshold."""
        result = validate_quality_gate(79.99, threshold=80.0)

        assert result["passes_gate"] is False
        assert result["coverage_gap"] == 0.01

    def test_message_format_passing(self):
        """Test message format when passing."""
        result = validate_quality_gate(85.5, threshold=80.0)

        assert result["message"] == "Coverage of 85.5% meets the 80.0% threshold"

    def test_message_format_failing(self):
        """Test message format when failing."""
        result = validate_quality_gate(75.5, threshold=80.0)

        assert result["message"] == "Coverage of 75.5% is below the 80.0% threshold by 4.50%"
