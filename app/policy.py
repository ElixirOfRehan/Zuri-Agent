from __future__ import annotations

import re

DEFAULT_FORBIDDEN = [
    (r"\bsteal\b.*\b(password|credential|token|api key)\b", "credential theft"),
    (r"\b(exfiltrate|phish|keylogger|ransomware|malware)\b", "malicious software"),
    (r"\bbypass\b.*\b(license|licensing|drm|paywall|authentication)\b", "license/auth bypass"),
    (r"\bcrack\b.*\b(software|app|game|license)\b", "cracking"),
    (r"\bunauthorized\b.*\b(access|entry|login)\b", "unauthorized access"),
    (r"\bformat\b.*\b(disk|drive|windows)\b", "destructive disk operation"),
    (r"\bdelete\b.*\b(everything|all files|whole drive|system32)\b", "destructive deletion"),
]


class Policy:
    """Hard blocks for disallowed goals and alternatives. Not a security sandbox."""

    def __init__(self, extra_patterns: list[tuple[str, str]] | None = None):
        patterns = list(DEFAULT_FORBIDDEN)
        patterns.extend(extra_patterns or [])
        self._patterns = [
            (re.compile(pattern, re.IGNORECASE | re.DOTALL), label)
            for pattern, label in patterns
        ]

    def forbidden_reason(self, text: str) -> str | None:
        value = text or ""
        for pattern, label in self._patterns:
            if pattern.search(value):
                return f"{label}: matched /{pattern.pattern}/"
        return None

    def alternative_allowed(self, alternative) -> tuple[bool, str | None]:
        text = alternative.approach + " " + " ".join(alternative.steps)
        reason = self.forbidden_reason(text)
        return (reason is None, reason)
