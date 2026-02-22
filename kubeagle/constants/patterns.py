"""Regex patterns for data parsing."""

import re

TEAM_PATTERN = re.compile(r"#\s*(?:TEAM:\s*)?([A-Za-z][A-Za-z0-9_-]+)", re.IGNORECASE)
GITHUB_TEAM_PATTERN = re.compile(r"@([A-Za-z][A-Za-z0-9_-]+(?:/[A-Za-z][A-Za-z0-9_-]+)?)")
EMAIL_TEAM_PATTERN = re.compile(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")

__all__ = [
    "EMAIL_TEAM_PATTERN",
    "GITHUB_TEAM_PATTERN",
    "TEAM_PATTERN",
]
