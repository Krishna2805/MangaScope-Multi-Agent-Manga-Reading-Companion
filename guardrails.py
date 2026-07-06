"""
MangaScope — Input validation and sanitization.

Runs before the Coordinator starts. Both fields are validated and sanitized
so that malformed inputs never reach the GraphQL query builder or Gemini prompts.
"""

import re

BLOCKED_SERIES_KEYWORDS = ["hentai", "explicit", "adult"]
USERNAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')
MAX_FIELD_LENGTH = 50
MIN_FIELD_LENGTH = 2


def validate_and_sanitize(
    username: str, series_name: str
) -> tuple[bool, str, str, str]:
    """
    Validate and sanitize user inputs.

    Returns:
        (is_valid, error_message, sanitized_username, sanitized_series)
    """
    # Step 1 — trim whitespace
    username = username.strip()
    series_name = series_name.strip()

    # Step 2 — empty checks
    if not username:
        return False, "Username is required.", username, series_name
    if not series_name:
        return False, "Series name is required.", username, series_name

    # Step 3 — length checks
    if len(username) < MIN_FIELD_LENGTH or len(username) > MAX_FIELD_LENGTH:
        return (
            False,
            f"Username must be between {MIN_FIELD_LENGTH} and {MAX_FIELD_LENGTH} characters.",
            username,
            series_name,
        )
    if len(series_name) < MIN_FIELD_LENGTH or len(series_name) > MAX_FIELD_LENGTH:
        return (
            False,
            f"Series name must be between {MIN_FIELD_LENGTH} and {MAX_FIELD_LENGTH} characters.",
            username,
            series_name,
        )

    # Step 4 — username format (AniList: alphanumeric + underscore)
    if not USERNAME_PATTERN.match(username):
        return (
            False,
            "Username can only contain letters, numbers, and underscores.",
            username,
            series_name,
        )

    # Step 5 — blocked content
    for keyword in BLOCKED_SERIES_KEYWORDS:
        if keyword.lower() in series_name.lower():
            return False, "This series cannot be processed.", username, series_name

    return True, "", username, series_name
