"""Witness output redaction for chimera-memory.

Applied at capture time before stdout/stderr excerpts are stored in claims.
Masks common secret patterns. Does not alter non-sensitive output.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Patterns — ordered from most specific to most generic
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, str]] = [
    # Private key blocks
    (r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----.*?-----END [^-]+-----",
     "[REDACTED:private_key]"),
    # Bearer tokens in HTTP headers
    (r"(?i)(Authorization\s*:\s*Bearer\s+)\S+", r"\1[REDACTED:bearer_token]"),
    # GitHub tokens
    (r"gh[poas]_[A-Za-z0-9_]{20,}", "[REDACTED:github_token]"),
    (r"github_pat_[A-Za-z0-9_]{20,}", "[REDACTED:github_token]"),
    # OpenAI / Anthropic sk- keys
    (r"sk-(?:ant-|proj-)?[A-Za-z0-9_\-]{20,}", "[REDACTED:api_key]"),
    # AWS access key IDs
    (r"AKIA[A-Z0-9]{16}", "[REDACTED:aws_access_key]"),
    # AWS secret-looking values (40-char alphanumeric)
    (r"(?i)(aws.{0,20}secret.{0,20}[=:\s]+)[A-Za-z0-9/+]{40}", r"\1[REDACTED:aws_secret]"),
    # Slack tokens
    (r"xox[bpas]-[A-Za-z0-9\-]{10,}", "[REDACTED:slack_token]"),
    # Database URLs  postgres://user:pass@host
    (
        r"(?i)((?:postgres|postgresql|mysql|mongodb|redis)://[^:]+:)[^@\s]+(@)",
        r"\1[REDACTED:db_password]\2",
    ),
    # password= / api_key= / token= / secret= assignments
    (r"(?i)((?:password|passwd|api_key|apikey|token|secret|auth_token)\s*[=:]\s*)['\"]?[A-Za-z0-9_\-./+]{8,}['\"]?",
     r"\1[REDACTED]"),
    # Long hex strings (32+ chars) that look like secrets
    (r"\b[0-9a-f]{32,64}\b", "[REDACTED:hex_secret]"),
    # Long base64-ish strings (40+ chars)  — only if they look like encoded secrets
    (r"(?<![A-Za-z])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9])", "[REDACTED:encoded_secret]"),
]

_COMPILED: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.DOTALL), r) for p, r in _PATTERNS
]

_REDACTED_MARKER = "[REDACTED]"


def redact(text: str | None) -> str:
    """Apply redaction to a witness excerpt string.

    Returns the text with secret patterns replaced. Empty/None input returns empty string.
    """
    if not text:
        return text or ""
    result = text
    for pattern, replacement in _COMPILED:
        result = pattern.sub(replacement, result)
    return result
