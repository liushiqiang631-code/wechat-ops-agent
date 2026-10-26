"""Anonymous bearer credentials select a complete, isolated application container.

The original database is accessible only through the provisioned owner's space.
New visitors never inherit its data, WeChat credentials, MCP tools or knowledge base.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import time
from collections import OrderedDict
from contextlib import closing
from pathlib import Path
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
from fastapi import HTTPException, Request
from pydantic import SecretStr
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, RedirectResponse, Response

from app.config.settings import Settings
from app.container import ApplicationContainer, build_container

COOKIE_MAX_AGE = 365 * 24 * 60 * 60
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PAGE_PATHS = {
    "/",
    "/tasks",
    "/topics",
    "/media",
    "/drafts",
    "/schedule",
    "/data",
    "/fans",
    "/calendar",
    "/workflow",
    "/agent",
    "/settings",
    "/space",
    "/docs",
    "/redoc",
}
TASK_PATH = re.compile(r"^/(?:api/v1/(?:tasks|articles)|review)/([^/]+)(?:/|$)")
SESSION_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
RECOVERY_PATTERN = re.compile(r"^wxspace_[A-Za-z0-9_-]{43}$")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SpaceManager:
    def __init__(self, settings: Settings):
        if settings.app_env == "production" and not settings.anonymous_cookie_secure:
            raise ValueError("production spaces require Secure cookies")
        self.settings = settings
        self.root = settings.anonymous_spaces_path.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.registry = self.root / "registry.sqlite"
        self.cookie_name = (
            "__Host-wechat_space" if settings.anonymous_cookie_secure else "wechat_space"
        )
        self._lock = RLock()
        self._containers: OrderedDict[str, ApplicationContainer] = OrderedDict()
        with closing(self._connect()) as db, db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS spaces (
                    id TEXT PRIMARY KEY,
                    legacy INTEGER NOT NULL DEFAULT 0,
                    recovery_hash TEXT UNIQUE,
                    created_at REAL NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_legacy_space
                    ON spaces(legacy) WHERE legacy = 1;
                CREATE TABLE IF NOT EXISTS space_sessions (
                    digest TEXT PRIMARY KEY,
                    space_id TEXT NOT NULL REFERENCES spaces(id),
                    expires_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS session_spaces ON space_sessions(space_id);
                CREATE TABLE IF NOT EXISTS space_rate_limits (
                    bucket TEXT PRIMARY KEY,
                    hits INTEGER NOT NULL,
                    expires_at REAL NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.registry, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    def provision_owner(self) -> str:
        """Called once by the operator; the secret is returned only to that caller.

        Never exposed by an HTTP route, and never assigned to the first visitor.
        """
        code = "wxspace_" + secrets.token_urlsafe(32)
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO spaces(id, legacy, recovery_hash, created_at) VALUES (?, 1, ?, ?)",
                (uuid4().hex, _digest(code), time.time()),
            )
        return code

    def require_owner(self) -> None:
        with closing(self._connect()) as db:
            if db.execute("SELECT 1 FROM spaces WHERE legacy = 1").fetchone() is None:
                raise RuntimeError("provision the private owner space before enabling HTTP access")

    def rate_limit(self, kind: str, client: str, maximum: int, period: int) -> None:
        # Hash IPs; they are used only to limit attempts, never to identify a space.
        now = time.time()
        bucket = _digest(f"{kind}:{client}")
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM space_rate_limits WHERE expires_at < ?", (now,))
            db.execute("DELETE FROM space_sessions WHERE expires_at < ?", (now,))
            db.execute(
                "INSERT INTO space_rate_limits VALUES (?, 1, ?) "
                "ON CONFLICT(bucket) DO UPDATE SET hits = hits + 1",
                (bucket, now + period),
            )
            hits = db.execute(
                "SELECT hits FROM space_rate_limits WHERE bucket = ?", (bucket,)
            ).fetchone()[0]
        if hits > maximum:
            raise HTTPException(
                429, "尝试次数较多，请稍后再试", headers={"Retry-After": str(period)}
            )

    def _session(self, db: sqlite3.Connection, space_id: str) -> str:
        token = secrets.token_urlsafe(32)
        db.execute(
            "INSERT INTO space_sessions VALUES (?, ?, ?)",
            (_digest(token), space_id, time.time() + COOKIE_MAX_AGE),
        )
        return token

    def create(self) -> tuple[str, str]:
        space_id = uuid4().hex
        with closing(self._connect()) as db, db:
            db.execute("INSERT INTO spaces(id, created_at) VALUES (?, ?)", (space_id, time.time()))
            token = self._session(db, space_id)
        return space_id, token

    def resolve(self, token: str | None) -> str | None:
        if not token or not SESSION_PATTERN.fullmatch(token):
            return None
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT space_id FROM space_sessions WHERE digest = ? AND expires_at > ?",
                (_digest(token), time.time()),
            ).fetchone()
        return row[0] if row else None

    def restore(self, code: str) -> tuple[str, str]:
        if not RECOVERY_PATTERN.fullmatch(code):
            raise HTTPException(400, "恢复码无效，请检查是否完整复制")
        with closing(self._connect()) as db, db:
            row = db.execute(
                "SELECT id FROM spaces WHERE recovery_hash = ?", (_digest(code),)
            ).fetchone()
            if row is None:
                raise HTTPException(400, "恢复码无效或已被更换")
            token = self._session(db, row[0])
        return row[0], token

    def rotate_recovery(self, space_id: str, current_token: str) -> str:
        code = "wxspace_" + secrets.token_urlsafe(32)
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE spaces SET recovery_hash = ? WHERE id = ?", (_digest(code), space_id)
            )
            # A lost code can be revoked without leaving old restored devices connected.
            db.execute(
                "DELETE FROM space_sessions WHERE space_id = ? AND digest != ?",
                (space_id, _digest(current_token)),
            )
        return code

    def recovery_saved(self, space_id: str) -> bool:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT recovery_hash FROM spaces WHERE id = ?", (space_id,)
            ).fetchone()
        return bool(row and row[0])

    def _space_settings(self, space_id: str, legacy: bool) -> tuple[Settings, Path]:
        directory = self.root / space_id
        directory.mkdir(mode=0o700, exist_ok=True)
        settings_file = directory / "wechat.env"
        updates: dict = {"anonymous_spaces_enabled": True}
        if not legacy:
            updates.update(
                database_url=f"sqlite:///{(directory / 'data.sqlite').as_posix()}",
                object_storage_path=directory / "outputs",
                workflow_checkpoint_path=directory / "checkpoints.sqlite",
                mcp_servers_path=directory / "mcp_servers.json",
                wechat_account_name="",
                wechat_app_id=None,
                wechat_app_secret=None,
                wechat_original_id=None,
                wechat_draft_enabled=False,
                knowledge_base_enabled=False,
                knowledge_base_token=None,
                operator_name="运营者",
                scheduler_enabled=False,
            )
        # Explicit overrides avoid process EnvironmentFile values overriding a space's settings.
        mapping = {
            "WECHAT_ACCOUNT_NAME": "wechat_account_name",
            "WECHAT_APP_ID": "wechat_app_id",
            "WECHAT_APP_SECRET": "wechat_app_secret",
            "WECHAT_ORIGINAL_ID": "wechat_original_id",
            "WECHAT_DRAFT_ENABLED": "wechat_draft_enabled",
        }
        if settings_file.exists():
            for key, value in dotenv_values(settings_file).items():
                if key not in mapping:
                    continue
                field = mapping[key]
                if field == "wechat_app_secret":
                    updates[field] = SecretStr(value) if value else None
                elif field == "wechat_draft_enabled":
                    updates[field] = value == "true"
                else:
                    updates[field] = value or ("" if field == "wechat_account_name" else None)
        return self.settings.model_copy(deep=True, update=updates), settings_file

    def container(self, space_id: str) -> ApplicationContainer:
        with self._lock:
            if space_id in self._containers:
                self._containers.move_to_end(space_id)
                return self._containers[space_id]
            with closing(self._connect()) as db:
                row = db.execute("SELECT legacy FROM spaces WHERE id = ?", (space_id,)).fetchone()
            if row is None:
                raise HTTPException(401, "空间不存在，请恢复已有空间")
            settings, settings_file = self._space_settings(space_id, bool(row[0]))
            container = build_container(settings)
            container.workspace_id = space_id
            container.settings_file = settings_file
            self._containers[space_id] = container
            if len(self._containers) > 64:
                _, previous = self._containers.popitem(last=False)
                previous.database.engine.dispose()
            return container

    def set_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            self.cookie_name,
            token,
            max_age=COOKIE_MAX_AGE,
            path="/",
            secure=self.settings.anonymous_cookie_secure,
            httponly=True,
            samesite="lax",
        )


def _same_origin(request: Request) -> bool:
    if request.headers.get("sec-fetch-site") == "cross-site":
        return False
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        return origin != "null" and (parsed.scheme, parsed.netloc) == (
            request.url.scheme,
            request.url.netloc,
        )
    return True


def install_space_middleware(application, manager: SpaceManager) -> None:
    @application.middleware("http")
    async def private_space(request: Request, call_next):
        path = request.url.path
        if path == "/health" or path.startswith("/static/"):
            return await call_next(request)
        try:
            if request.method not in SAFE_METHODS and not _same_origin(request):
                raise HTTPException(403, "请从本站页面发起操作")
            token = request.cookies.get(manager.cookie_name)
            space_id = await run_in_threadpool(manager.resolve, token)
            new_token = None
            # Restoring is the only unauthenticated write endpoint.
            if path == "/api/v1/space/restore" and request.method == "POST":
                response = await call_next(request)
            else:
                if space_id is None:
                    if request.method == "GET" and path in PAGE_PATHS:
                        if token and path != "/space":
                            return RedirectResponse("/space?expired=1", status_code=303)
                        client = request.client.host if request.client else "unknown"
                        await run_in_threadpool(manager.rate_limit, "create", client, 30, 3600)
                        space_id, new_token = await run_in_threadpool(manager.create)
                        request.state.new_space = True
                    else:
                        raise HTTPException(401, "请先打开网页创建空间，或使用恢复码恢复已有空间")
                container = await run_in_threadpool(manager.container, space_id)
                request.state.space_container = container
                request.state.space_id = space_id
                request.state.space_manager = manager
                request.state.space_token = new_token or token
                match = TASK_PATH.match(path)
                if match:
                    try:
                        await run_in_threadpool(container.tasks.get, match[1])
                    except KeyError as exc:
                        raise HTTPException(404, "任务不存在或不属于当前空间") from exc
                response = await call_next(request)
                if new_token:
                    manager.set_cookie(response, new_token)
        except HTTPException as exc:
            response = JSONResponse(
                {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
            )
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Cookie"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
