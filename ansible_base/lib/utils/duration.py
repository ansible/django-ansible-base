"""
Utility functions for parsing and converting duration/time strings.
"""

import logging
from typing import Optional

logger = logging.getLogger('ansible_base.lib.utils.duration')


def convert_to_seconds(duration_string: Optional[str], default: int = 10) -> int:
    """
    Converts a duration string like '15s', '5m', '1h', '2d', '3w' to seconds.

    This function parses duration strings and converts them to seconds. It allows
    negative values, leaving validation to the caller based on their use case.

    Args:
        duration_string: A string representing a duration with a unit suffix.
                        Supported units: s (seconds), m (minutes), h (hours),
                        d (days), w (weeks). Can also be a plain integer string
                        for seconds. Negative values are supported. Case-insensitive.
        default: The default value to return if the input is invalid or cannot
                be parsed. Defaults to 10 seconds.

    Returns:
        int: The duration in seconds (can be negative), or the default value if invalid.

    Examples:
        >>> convert_to_seconds('15s')
        15
        >>> convert_to_seconds('5m')
        300
        >>> convert_to_seconds('1h')
        3600
        >>> convert_to_seconds('2d')
        172800
        >>> convert_to_seconds('1w')
        604800
        >>> convert_to_seconds('30')
        30
        >>> convert_to_seconds('-5s')
        -5
        >>> convert_to_seconds('-1d')
        -86400
        >>> convert_to_seconds('invalid')
        10
    """
    try:
        unit = duration_string[-1].lower()

        # Check if last character is a valid unit
        if unit == '-':
            return default
        elif unit in ('s', 'm', 'h', 'd', 'w'):
            # Parse the value before the unit
            value = int(duration_string[:-1])
            if unit == 's':
                return value
            elif unit == 'm':
                return value * 60
            elif unit == 'h':
                return value * 3600  # 60 * 60
            elif unit == 'd':
                return value * 86400  # 60 * 60 * 24
            elif unit == 'w':
                return value * 604800  # 60 * 60 * 24 * 7
        else:
            # No valid unit found, try to parse the entire string as an integer
            return int(duration_string)
    except Exception:
        logger.warning(f"Invalid duration format: '{duration_string}'")
        return default
