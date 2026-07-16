"""Classify leaf-tool failures so fallback routing can be smarter than blind rotation."""

from __future__ import annotations

import re
from typing import Tuple

# category -> regex over the (lowercased) error text. First match wins.
_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("auth", r"unauthor|forbidden|\b401\b|\b403\b|invalid[ _-]?api|api[ _-]?key|login|consent|"
             r"token (?:expired|invalid)|credential|not authenticated|permission denied"),
    ("rate_limit", r"rate.?limit|\b429\b|quota|capacity|overload|too many request|throttl"),
    ("timeout", r"timeout|timed out|deadline exceeded|read timed"),
    ("transient", r"\b5\d\d\b|temporarily|connection (?:reset|refused|error)|network|"
                  r"unavailable|try again|econnreset"),
    ("bad_request", r"\b400\b|invalid (?:argument|parameter|request)|schema|unknown property|"
                    r"required|validation"),
)

# Categories where rotating to another provider is worth trying.
ROTATABLE = frozenset({"auth", "rate_limit", "timeout", "transient", "unknown"})


def classify(text: str) -> str:
    t = (text or "").lower()
    for category, pattern in _PATTERNS:
        if re.search(pattern, t):
            return category
    return "unknown"


def should_rotate(category: str) -> bool:
    """A malformed request (bad_request) won't be fixed by a different provider."""
    return category in ROTATABLE
