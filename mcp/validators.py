"""
Input validators for curated MCP tools.

These helpers validate parameters at the system boundary (the MCP tool
functions) before they are forwarded to Adobe plugins.  REPL / execute_script
tools are intentionally exempt — they accept arbitrary input by design.
"""

from typing import Union


def validate_string(value: str, max_length: int = 10_000, name: str = "value") -> str:
    """Validate a string parameter.

    Raises ValueError if the value is not a string or exceeds max_length.
    Returns the original string unchanged.
    """
    if not isinstance(value, str):
        raise ValueError(f"'{name}' must be a string, got {type(value).__name__}")
    if len(value) > max_length:
        raise ValueError(
            f"'{name}' is too long ({len(value)} chars). Maximum allowed: {max_length}"
        )
    return value


def validate_number(
    value: Union[int, float],
    min_val: Union[int, float],
    max_val: Union[int, float],
    name: str = "value",
) -> Union[int, float]:
    """Validate a numeric parameter is within [min_val, max_val].

    Raises ValueError if out of range.
    Returns the original value unchanged.
    """
    if not isinstance(value, (int, float)):
        raise ValueError(f"'{name}' must be a number, got {type(value).__name__}")
    if value < min_val or value > max_val:
        raise ValueError(
            f"'{name}' must be between {min_val} and {max_val}, got {value}"
        )
    return value


def validate_list(value: list, max_length: int = 1000, name: str = "value") -> list:
    """Validate a list parameter does not exceed max_length items.

    Raises ValueError if too long.
    Returns the original list unchanged.
    """
    if not isinstance(value, list):
        raise ValueError(f"'{name}' must be a list, got {type(value).__name__}")
    if len(value) > max_length:
        raise ValueError(
            f"'{name}' has too many items ({len(value)}). Maximum allowed: {max_length}"
        )
    return value
