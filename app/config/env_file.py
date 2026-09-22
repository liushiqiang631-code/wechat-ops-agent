from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from tempfile import NamedTemporaryFile


def format_env_value(value: str) -> str:
    """Serialize one value using the python-dotenv quoting conventions."""
    if any(char in value for char in ("\r", "\n", "\x00")):
        raise ValueError("environment values cannot contain CR, LF, or NUL characters")
    if value == "":
        return ""
    needs_quotes = any(char in value for char in (" ", "\t", '"', "'", "#")) or (
        value != value.strip()
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def update_env_file(path: Path, updates: Mapping[str, str]) -> Path:
    """Rewrite the given keys in an .env file, preserving all other lines.

    Keys are replaced in place when present and appended when missing, so
    existing comments and ordering survive a save. Parent directories are
    created on demand; the file is created when absent.
    """
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)

    def _key_of(line: str) -> str | None:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            return None
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        key, separator, _ = stripped.partition("=")
        if not separator:
            return None
        return key.strip()

    updated: list[str] = []
    for line in lines:
        key = _key_of(line)
        if key is not None and key in updates:
            value = updates[key]
            pending.pop(key, None)
            updated.append(f"{key}={format_env_value(value)}")
        else:
            updated.append(line)

    if pending:
        if updated and updated[-1].strip():
            updated.append("")
        for key, value in pending.items():
            updated.append(f"{key}={format_env_value(value)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(updated) + "\n"
    temporary_name: str | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(body)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_name = temporary.name
        os.replace(temporary_name, path)
    except OSError:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
        raise
    return path
