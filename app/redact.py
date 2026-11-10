from __future__ import annotations

import re

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{6,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
]


def redact(text: str) -> str:
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("***REDACTED***", result)
    return result


def preview(text: str, limit: int = 400) -> str:
    value = text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"
    return redact(value)
