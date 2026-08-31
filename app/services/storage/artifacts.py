from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.domain.models import ArtifactRef


class ArtifactStore:
    _SAFE_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")

    def __init__(self, root: Path):
        self.root = Path(root)

    def _task_dir(self, task_id: str) -> Path:
        if not self._SAFE_TASK_ID.fullmatch(task_id):
            raise ValueError("invalid artifact task id")
        root = self.root.resolve()
        path = (root / task_id).resolve()
        if path.parent != root:
            raise ValueError("invalid artifact task id")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _versions(self, task_id: str, name: str) -> list[int]:
        prefix = f"{name}.v"
        versions: list[int] = []
        for path in self._task_dir(task_id).glob(f"{name}.v*.json"):
            raw = path.name.removeprefix(prefix).removesuffix(".json")
            if raw.isdigit():
                versions.append(int(raw))
        return sorted(versions)

    def write_json(self, task_id: str, name: str, payload: object) -> ArtifactRef:
        task_dir = self._task_dir(task_id)
        version = (self._versions(task_id, name)[-1] + 1) if self._versions(task_id, name) else 1
        destination = task_dir / f"{name}.v{version}.json"
        body = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        self._atomic_write(task_dir, destination, body)
        latest = task_dir / f"{name}.latest.json"
        self._atomic_write(task_dir, latest, body)
        return ArtifactRef(
            task_id=task_id,
            name=name,
            version=version,
            path=str(destination),
            sha256=hashlib.sha256(body).hexdigest(),
        )

    @staticmethod
    def _atomic_write(task_dir: Path, destination: Path, body: bytes) -> None:
        """Write via temp file + os.replace, retrying transient OS denials.

        On some Windows machines (and slow drives with real-time scanning) the
        final ``os.replace`` can intermittently fail with WinError 5 even though
        the directory is writable; a short retry keeps artifact persistence
        reliable without masking real permission problems.
        """
        last_error: OSError | None = None
        for attempt in range(3):
            temp_name: str | None = None
            try:
                with NamedTemporaryFile(dir=task_dir, delete=False) as temporary:
                    temporary.write(body)
                    temp_name = temporary.name
                os.replace(temp_name, destination)
                return
            except OSError as error:
                last_error = error
                if temp_name is not None:
                    try:
                        os.unlink(temp_name)
                    except OSError:
                        pass
                time.sleep(0.15 * (attempt + 1))
        raise last_error if last_error is not None else OSError("artifact write failed")

    def read_json(self, task_id: str, name: str, version: int | None = None) -> object:
        task_dir = self._task_dir(task_id)
        path = (
            task_dir / f"{name}.v{version}.json"
            if version is not None
            else task_dir / f"{name}.latest.json"
        )
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self, task_id: str) -> list[Path]:
        return sorted(self._task_dir(task_id).glob("*.v*.json"))

    def delete_task(self, task_id: str) -> None:
        root = self.root.resolve()
        task_dir = (root / task_id).resolve()
        if task_dir.parent != root:
            raise ValueError("invalid artifact task path")
        if task_dir.exists():
            shutil.rmtree(task_dir)
