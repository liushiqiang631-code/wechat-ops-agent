from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.domain.enums import Channel, ChannelPostStatus
from app.domain.models import ActivityLog, ChannelAccount, ChannelPost, ChannelPostCreate

router = APIRouter(tags=["omni-channel"])
account_router = APIRouter(prefix="/channels", tags=["omni-channel"])
post_router = APIRouter(prefix="/channel-posts", tags=["omni-channel"])
activity_router = APIRouter(prefix="/activity", tags=["omni-channel"])

CHANNEL_LABELS = {
    Channel.XIAOHONGSHU: "小红书",
    Channel.SHIPINHAO: "视频号",
    Channel.DOUYIN: "抖音",
    Channel.KUAISHOU: "快手",
    Channel.WECHAT: "公众号",
}

STATUS_LABELS = {
    ChannelPostStatus.DRAFT: "草稿",
    ChannelPostStatus.PENDING_REVIEW: "待审核",
    ChannelPostStatus.SCHEDULED: "待发布",
    ChannelPostStatus.PUBLISHED: "已发布",
    ChannelPostStatus.FAILED: "发布失败",
}


class AccountUpdateRequest(BaseModel):
    display_name: str | None = None
    handle: str | None = None
    status: str | None = None
    followers: int | None = Field(default=None, ge=0)


class MetricsUpdateRequest(BaseModel):
    views: int = Field(ge=0)
    likes: int = Field(ge=0)
    comments: int = Field(ge=0)
    shares: int = Field(default=0, ge=0)
    favorites: int = Field(default=0, ge=0)


def _parse_channel(value: str | None) -> Channel | None:
    if not value or value == "all":
        return None
    try:
        return Channel(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知渠道") from exc


def _parse_status(value: str | None) -> ChannelPostStatus | None:
    if not value or value == "all":
        return None
    try:
        return ChannelPostStatus(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "未知状态") from exc


@account_router.get("", response_model=list[ChannelAccount])
def list_accounts(
    container: ApplicationContainer = Depends(get_container),
) -> list[ChannelAccount]:
    return container.channels.list_accounts()


@account_router.patch("/{key}", response_model=ChannelAccount)
def update_account(
    key: str,
    payload: AccountUpdateRequest,
    container: ApplicationContainer = Depends(get_container),
) -> ChannelAccount:
    try:
        channel = Channel(key)
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "渠道不存在") from exc
    # PATCH 是接入动作：账号尚未登记时以此创建，而不是 404。
    account = container.channels.get_account(channel) or ChannelAccount(
        key=channel,
        display_name=CHANNEL_LABELS[channel],
        handle=CHANNEL_LABELS[channel],
        account_type="未设置",
    )
    # 显式校验，避免任意字符串经 model_copy 绕过域校验后污染渠道页。
    if payload.status is not None and payload.status not in {"active", "paused"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "状态仅支持 active/paused")
    updated = account.model_copy(
        update={
            "display_name": payload.display_name or account.display_name,
            "handle": payload.handle or account.handle,
            "status": payload.status or account.status,
            "followers": (
                payload.followers if payload.followers is not None else account.followers
            ),
        }
    )
    saved = container.channels.upsert_account(updated)
    container.activity.log(
        "channel_update",
        f"更新渠道信息：{CHANNEL_LABELS[channel]}",
        channel=channel,
        ref_id=saved.key.value,
    )
    return saved


@post_router.get("", response_model=list[ChannelPost])
def list_posts(
    channel: str | None = None,
    status_filter: str | None = None,
    q: str | None = None,
    days: int | None = None,
    limit: int = 200,
    container: ApplicationContainer = Depends(get_container),
) -> list[ChannelPost]:
    since = None
    if days:
        since = datetime.now().astimezone() - timedelta(days=days)
    return container.channels.list_posts(
        channel=_parse_channel(channel),
        status=_parse_status(status_filter),
        search=q,
        since=since,
        limit=max(1, min(limit, 500)),
    )


@post_router.post("", response_model=ChannelPost, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: ChannelPostCreate,
    container: ApplicationContainer = Depends(get_container),
) -> ChannelPost:
    post = container.channels.create_post(payload, source="manual")
    label = f"登记发布：{CHANNEL_LABELS[payload.channel]}《{payload.title[:40]}》"
    container.activity.log(
        "post_create",
        label,
        channel=payload.channel,
        ref_id=post.id,
    )
    return post


@post_router.post("/{post_id}/publish", response_model=ChannelPost)
def publish_post(
    post_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> ChannelPost:
    post = container.channels.get_post(post_id)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "发布记录不存在")
    if post.status == ChannelPostStatus.PUBLISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "该记录已经是已发布状态")
    updated = container.channels.update_status(post_id, ChannelPostStatus.PUBLISHED)
    container.activity.log(
        "post_publish",
        f"人工确认发布：{CHANNEL_LABELS[post.channel]}《{post.title[:40]}》",
        channel=post.channel,
        ref_id=post.id,
    )
    return updated


@post_router.post("/{post_id}/retry", response_model=ChannelPost)
def retry_post(
    post_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> ChannelPost:
    post = container.channels.get_post(post_id)
    if post is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "发布记录不存在")
    if post.status != ChannelPostStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "只有发布失败的记录可以重试")
    updated = container.channels.update_status(post_id, ChannelPostStatus.PENDING_REVIEW)
    container.activity.log(
        "post_retry",
        f"重试发布：{CHANNEL_LABELS[post.channel]}《{post.title[:40]}》",
        channel=post.channel,
        ref_id=post.id,
    )
    return updated


@post_router.post("/{post_id}/metrics", response_model=ChannelPost)
def update_metrics(
    post_id: str,
    payload: MetricsUpdateRequest,
    container: ApplicationContainer = Depends(get_container),
) -> ChannelPost:
    if container.channels.get_post(post_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "发布记录不存在")
    updated = container.channels.update_metrics(
        post_id,
        views=payload.views,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        favorites=payload.favorites,
    )
    container.activity.log(
        "post_metrics",
        f"回流效果数据：《{updated.title[:40]}》浏览 {payload.views}",
        channel=updated.channel,
        ref_id=post_id,
    )
    return updated


@post_router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> Response:
    post = container.channels.get_post(post_id)
    if post is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    container.channels.delete_post(post_id)
    container.activity.log(
        "post_delete",
        f"删除发布记录：《{post.title[:40]}》",
        channel=post.channel,
        ref_id=post_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/channels/report.csv")
def export_report(
    days: int = 7,
    container: ApplicationContainer = Depends(get_container),
) -> StreamingResponse:
    since = datetime.now().astimezone() - timedelta(days=max(1, min(days, 90)))
    # 报表按创建时间覆盖全部状态：草稿、待审核与已发布都在盘点范围内。
    # SQLite 返回的 created_at 不带时区，用业务时区解释后再比较。
    business_tz = container.settings.timezone
    posts = [
        post
        for post in container.channels.list_posts(limit=500)
        if (
            post.created_at
            if post.created_at.tzinfo
            else post.created_at.replace(tzinfo=business_tz)
        )
        >= since
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "渠道",
            "内容形态",
            "标题",
            "分类",
            "状态",
            "时间",
            "浏览",
            "点赞",
            "评论",
            "分享",
            "收藏",
            "备注",
        ]
    )
    for post in posts:
        moment = post.published_at or post.scheduled_at or post.created_at
        writer.writerow(
            [
                CHANNEL_LABELS[post.channel],
                post.content_type,
                post.title,
                post.category,
                STATUS_LABELS[post.status],
                moment.strftime("%Y-%m-%d %H:%M"),
                post.views,
                post.likes,
                post.comments,
                post.shares,
                post.favorites,
                post.last_error or "",
            ]
        )
    buffer.seek(0)
    filename = f"content-report-{since.strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter(["\ufeff" + buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@activity_router.get("", response_model=list[ActivityLog])
def list_activity(
    limit: int = 60,
    container: ApplicationContainer = Depends(get_container),
) -> list[ActivityLog]:
    return container.activity.list(limit=max(1, min(limit, 200)))
