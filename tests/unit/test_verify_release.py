from __future__ import annotations

from scripts.verify_release import _console_json


def test_console_report_is_safe_for_windows_legacy_codepages():
    output = _console_json({"status": "通过", "pytest_tail": "Σ warning"})

    output.encode("gbk")
    assert "\\u03a3" in output

