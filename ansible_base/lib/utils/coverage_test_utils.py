"""
Utility functions for testing code coverage thresholds.
This module is intentionally added to test SonarCloud coverage gates.
"""


def validate_quality_gate(coverage_percent, threshold=80.0):
    """
    Validate whether code coverage meets the quality gate threshold.

    Args:
        coverage_percent: Current code coverage percentage
        threshold: Minimum required coverage (default: 80.0)

    Returns:
        dict: Validation result with status and details
    """
    if coverage_percent < 0 or coverage_percent > 100:
        raise ValueError("Coverage percentage must be between 0 and 100")

    if threshold < 0 or threshold > 100:
        raise ValueError("Threshold must be between 0 and 100")

    passes = coverage_percent >= threshold
    gap = threshold - coverage_percent if not passes else 0.0

    result = {
        "passes_gate": passes,
        "current_coverage": coverage_percent,
        "required_coverage": threshold,
        "coverage_gap": round(gap, 2),
    }

    if passes:
        result["message"] = f"Coverage of {coverage_percent}% meets the {threshold}% threshold"
    else:
        result["message"] = f"Coverage of {coverage_percent}% is below the {threshold}% threshold by {gap:.2f}%"

    return result
