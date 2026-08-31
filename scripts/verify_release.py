from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _console_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2)


def _run(name: str, command: list[str]) -> dict:
    process = subprocess.run(  # noqa: S603 - command vectors are fixed by this module
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "name": name,
        "command": command,
        "exit_code": process.returncode,
        "stdout_tail": process.stdout[-4000:],
        "stderr_tail": process.stderr[-4000:],
        "passed": process.returncode == 0,
    }


def _secret_scan() -> dict:
    pattern = re.compile(r"\bsk-[0-9a-fA-F]{24,}\b")
    files = [
        *ROOT.glob("*.toml"),
        *ROOT.glob("*.yml"),
        *ROOT.glob("*.yaml"),
        *ROOT.glob("*.md"),
        *ROOT.glob(".env.example"),
        *(ROOT / "app").rglob("*"),
        *(ROOT / "scripts").rglob("*.py"),
    ]
    leaks: list[str] = []
    for path in files:
        if not path.is_file() or path.suffix in {".pyc", ".png", ".db"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if pattern.search(text):
            leaks.append(str(path.relative_to(ROOT)))
    return {
        "name": "secret_scan",
        "passed": not leaks,
        "exit_code": 0 if not leaks else 1,
        "leaks": leaks,
    }


def main() -> int:
    python = sys.executable
    checks = [
        _run("pytest", [python, "-m", "pytest", "-q"]),
        _run("ruff", [python, "-m", "ruff", "check", "app", "tests", "scripts"]),
        _run("compileall", [python, "-m", "compileall", "-q", "app", "scripts"]),
        _secret_scan(),
    ]
    report = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "python": sys.version,
        "passed": all(check["passed"] for check in checks),
        "checks": checks,
    }
    output = ROOT / "outputs" / "verification" / "release_verification.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(_console_json(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
