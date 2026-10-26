from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ChannelAccountRow, ChannelPostRow
from app.domain.enums import Channel, ChannelPostStatus
from app.domain.models import ChannelAccount, ChannelPost, ChannelPostCreate


def _now() -> datetime:
    return datetime.now().astimezone()


def _account_to_model(row: ChannelAccountRow) -> ChannelAccount:
    return ChannelAccount(
        key=Channel(row.key),
        display_name=row.display_name,
        handle=row.handle,
        account_type=row.account_type,
        status=row.status,  # type: ignore[arg-type]
        followers=row.followers,
        updated_at=row.updated_at,
    )


def _post_to_model(row: ChannelPostRow) -> ChannelPost:
    return ChannelPost(
        id=row.id,
        channel=Channel(row.channel),
        content_type=row.content_type,
        title=row.title,
        excerpt=row.excerpt,
        category=row.category,
        status=ChannelPostStatus(row.status),
        cover_seed=row.cover_seed,
        task_id=row.task_id,
        script_id=row.script_id,
        scheduled_at=row.scheduled_at,
        published_at=row.published_at,
        views=row.views,
        likes=row.likes,
        comments=row.comments,
        shares=row.shares,
        favorites=row.favorites,
        source=row.source,  # type: ignore[arg-type]
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class ChannelRepository:
    """渠道账号与全渠道发布记录的持久化。"""

    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    # -- accounts ----------------------------------------------------------

    def list_accounts(self) -> list[ChannelAccount]:
        with self.sessions() as session:
            rows = session.query(ChannelAccountRow).order_by(ChannelAccountRow.key).all()
            return [_account_to_model(row) for row in rows]

    def get_account(self, key: Channel) -> ChannelAccount | None:
        with self.sessions() as session:
            row = session.get(ChannelAccountRow, key.value)
            return _account_to_model(row) if row else None

    def upsert_account(self, account: ChannelAccount) -> ChannelAccount:
        with self.sessions.begin() as session:
            row = session.get(ChannelAccountRow, account.key.value)
            if row is None:
                row = ChannelAccountRow(key=account.key.value)
            row.display_name = account.display_name
            row.handle = account.handle
            row.account_type = account.account_type
            row.status = account.status
            row.followers = account.followers
            row.updated_at = _now()
            session.add(row)
        return _account_to_model(row)

    def accounts_seeded(self) -> bool:
        with self.sessions() as session:
            return session.query(ChannelAccountRow.key).first() is not None

    # -- posts -------------------------------------------------------------

    def create_post(
        self,
        post: ChannelPostCreate | ChannelPost,
        *,
        post_id: str | None = None,
        cover_seed: str = "",
        task_id: str | None = None,
        script_id: str | None = None,
        source: str = "manual",
    ) -> ChannelPost:
        row = self._post_row(
            post,
            post_id=post_id,
            cover_seed=cover_seed,
            task_id=task_id,
            script_id=script_id,
            source=source,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return _post_to_model(row)

    def create_posts_bulk(self, posts: list[ChannelPost], *, source: str = "demo") -> None:
        """批量写入发布记录（单个事务），供首启种子使用。"""
        rows = [self._post_row(post, source=source) for post in posts]
        with self.sessions.begin() as session:
            session.add_all(rows)

    @staticmethod
    def _post_row(
        post: ChannelPostCreate | ChannelPost,
        *,
        post_id: str | None = None,
        cover_seed: str = "",
        task_id: str | None = None,
        script_id: str | None = None,
        source: str = "manual",
    ) -> ChannelPostRow:
        now = _now()
        row_id = post_id or getattr(post, "id", None) or str(uuid4())
        return ChannelPostRow(
            id=row_id,
            channel=post.channel.value,
            content_type=post.content_type,
            title=post.title,
            excerpt=post.excerpt,
            category=post.category,
            status=post.status.value,
            cover_seed=cover_seed
            or getattr(post, "cover_seed", "")
            or row_id[:8],
            task_id=task_id or getattr(post, "task_id", None),
            script_id=script_id or getattr(post, "script_id", None),
            scheduled_at=post.scheduled_at,
            published_at=post.published_at,
            views=post.views,
            likes=post.likes,
            comments=post.comments,
            shares=post.shares,
            favorites=post.favorites,
            source=source,
            last_error=getattr(post, "last_error", None),
            created_at=getattr(post, "created_at", None) or now,
            updated_at=getattr(post, "updated_at", None) or now,
        )

    def get_post(self, post_id: str) -> ChannelPost | None:
        with self.sessions() as session:
            row = session.get(ChannelPostRow, post_id)
            return _post_to_model(row) if row else None

    def list_posts(
        self,
        *,
        channel: Channel | None = None,
        status: ChannelPostStatus | None = None,
        search: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
    ) -> list[ChannelPost]:
        with self.sessions() as session:
            query = session.query(ChannelPostRow)
            if channel is not None:
                query = query.filter(ChannelPostRow.channel == channel.value)
            if status is not None:
                query = query.filter(ChannelPostRow.status == status.value)
            if search:
                like = f"%{search}%"
                query = query.filter(
                    ChannelPostRow.title.like(like) | ChannelPostRow.excerpt.like(like)
                )
            if since is not None:
                query = query.filter(ChannelPostRow.published_at >= since)
            if until is not None:
                query = query.filter(ChannelPostRow.published_at < until)
            rows = (
                query.order_by(ChannelPostRow.published_at.desc(), ChannelPostRow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_post_to_model(row) for row in rows]

    def update_status(self, post_id: str, status: ChannelPostStatus) -> ChannelPost:
        with self.sessions.begin() as session:
            row = session.get(ChannelPostRow, post_id)
            if row is None:
                raise KeyError(post_id)
            row.status = status.value
            if status == ChannelPostStatus.PUBLISHED and row.published_at is None:
                row.published_at = _now()
            if status == ChannelPostStatus.FAILED and not row.last_error:
                row.last_error = "发布未成功，等待人工重试"
            row.updated_at = _now()
            session.add(row)
        return _post_to_model(row)

    def update_metrics(
        self,
        post_id: str,
        *,
        views: int,
        likes: int,
        comments: int,
        shares: int = 0,
        favorites: int = 0,
    ) -> ChannelPost:
        with self.sessions.begin() as session:
            row = session.get(ChannelPostRow, post_id)
            if row is None:
                raise KeyError(post_id)
            row.views = views
            row.likes = likes
            row.comments = comments
            row.shares = shares
            row.favorites = favorites
            row.updated_at = _now()
            session.add(row)
        return _post_to_model(row)

    def delete_post(self, post_id: str) -> bool:
        with self.sessions.begin() as session:
            row = session.get(ChannelPostRow, post_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def count_by_status(self) -> dict[str, int]:
        with self.sessions() as session:
            rows = session.query(ChannelPostRow.status, ChannelPostRow.id).all()
        counts: dict[str, int] = {}
        for status, _ in rows:
            counts[status] = counts.get(status, 0) + 1
        return counts
