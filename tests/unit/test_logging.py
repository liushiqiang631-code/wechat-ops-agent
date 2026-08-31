from __future__ import annotations

import logging

from app.config.logging import SecretRedactionFilter, redact_secrets


def test_log_filter_redacts_known_secret_shapes():
    record = logging.LogRecord(
        "test",
        logging.INFO,
        __file__,
        1,
        "Authorization: Bearer abc123 access_token=token-value AppSecret=wx-secret "
        "api_key=sk-example",
        (),
        None,
    )

    allowed = SecretRedactionFilter().filter(record)

    assert allowed is True
    assert "abc123" not in record.getMessage()
    assert "token-value" not in record.getMessage()
    assert "wx-secret" not in record.getMessage()
    assert "sk-example" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()


def test_redact_secrets_is_reusable_for_persisted_diagnostics():
    value = "rewrite failed: api_key=top-secret Authorization: Bearer abc123"

    redacted = redact_secrets(value)

    assert "top-secret" not in redacted
    assert "abc123" not in redacted
    assert redacted.count("[REDACTED]") == 2
