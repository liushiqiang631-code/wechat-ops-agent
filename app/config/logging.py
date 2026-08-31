from __future__ import annotations

import logging
import re
from typing import ClassVar


class SecretRedactionFilter(logging.Filter):
    patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
        re.compile(r"(?i)(access_token\s*[=:]\s*)[^\s,;&]+"),
        re.compile(r"(?i)(appsecret\s*[=:]\s*)[^\s,;&]+"),
        re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;&]+"),
        re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    )

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_secrets(record.getMessage())
        record.args = ()
        return True


def redact_secrets(value: str) -> str:
    """Remove secret-shaped values before they enter a log or diagnostic artifact."""
    redacted = value
    for pattern in SecretRedactionFilter.patterns:
        redacted = pattern.sub(
            lambda match: f"{match.group(1) if match.lastindex else ''}[REDACTED]",
            redacted,
        )
    return redacted


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(SecretRedactionFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
