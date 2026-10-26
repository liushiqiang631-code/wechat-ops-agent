from __future__ import annotations

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)
        if url.startswith("sqlite"):
            # WAL + NORMAL 同步：本地演示库在机械盘上的高频小事务（种子、状态流转）
            # 从每条数秒降到毫秒级；崩溃只可能丢失最后一个事务，可接受。
            @event.listens_for(self.engine, "connect")
            def _tune_sqlite(dbapi_connection, _record):  # pragma: no cover - pragma hook
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            autoflush=False,
        )

    def create_all(self) -> None:
        from app.db import models  # noqa: F401

        Base.metadata.create_all(self.engine)
