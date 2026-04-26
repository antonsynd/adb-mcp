"""
Path validator for curated MCP tools that accept file paths.

Validates that paths don't contain null bytes and resolve to a location
under the user's home directory (configurable via ADB_MCP_ALLOWED_PATH_PREFIX),
catching both directory-traversal attacks and symlinks that escape the boundary.

REPL / execute_script tools are intentionally exempt.
"""

import os
from pathlib import Path


def _get_allowed_prefix() -> Path:
    """Return the root under which all validated paths must fall."""
    env_val = os.environ.get("ADB_MCP_ALLOWED_PATH_PREFIX")
    if env_val:
        return Path(env_val).resolve()
    return Path.home().resolve()


def validate_path(path: str, must_exist: bool = False) -> str:
    """Validate a file-system path accepted by a curated MCP tool.

    Checks performed:
    1. The value is a non-empty string.
    2. No null bytes (guard against null-byte injection).
    3. Resolved (absolute, symlinks followed) path is under the allowed prefix.
    4. If ``must_exist`` is True, the path must already exist on disk.

    Args:
        path: The file-system path to validate.
        must_exist: If True, raise ValueError if the path does not exist.

    Returns:
        The original (unmodified) path string on success.

    Raises:
        ValueError: If any check fails.
    """
    if not isinstance(path, str) or not path:
        raise ValueError(
            f"'path' must be a non-empty string, got {type(path).__name__}"
        )

    if "\x00" in path:
        raise ValueError("'path' must not contain null bytes")

    resolved = Path(path).resolve()
    allowed_prefix = _get_allowed_prefix()

    try:
        resolved.relative_to(allowed_prefix)
    except ValueError:
        raise ValueError(
            f"Path '{path}' resolves to '{resolved}', which is outside the "
            f"allowed directory '{allowed_prefix}'. "
            "Set ADB_MCP_ALLOWED_PATH_PREFIX to override."
        )

    if must_exist and not resolved.exists():
        raise ValueError(f"Path '{path}' does not exist")

    return path
