from __future__ import annotations

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.channels import CHANNEL_LABELS
from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.domain.enums import Channel, ChannelPostStatus, TaskMode
from app.domain.models import (
    ChannelPost,
    ChannelPostCreate,
    ScriptBeat,
    ScriptGenerateRequest,
    TaskSpec,
    VideoScript,
)
from app.services.analytics.topic_feedback import sync_topic_record

router = APIRouter(prefix="/scripts", tags=["scripts"])

CONTENT_TYPE_BY_CHANNEL = {
    Channel.XIAOHONGSHU: "图文笔记",
    Channel.SHIPINHAO: "产品视频",
    Channel.DOUYIN: "短视频",
    Channel.KUAISHOU: "短视频",
    Channel.WECHAT: "深度文章",
}


class ManualScriptRequest(BaseModel):
    title: str
    topic: str
    channel: Channel
    duration_seconds: int = Field(default=60, ge=15, le=600)
    audience: str = "关注 AI 效率的职场人"
    hook: str
    beats: list[ScriptBeat]
    ending: str
    cover_idea: str | None = None
    hashtags: list[str] = []
    article_angle: str | None = None


class ConvertToPostRequest(BaseModel):
    channel: Channel
    # 脚本转内容先落为草稿/待审核；定时排期请在发布中心「创建发布」中设置时间。
    status: Literal[ChannelPostStatus.DRAFT, ChannelPostStatus.PENDING_REVIEW] = (
        ChannelPostStatus.DRAFT
    )


@router.get("", response_model=list[VideoScript])
def list_scripts(
    container: ApplicationContainer = Depends(get_container),
) -> list[VideoScript]:
    return container.scripts.list()


@router.post("/generate", response_model=VideoScript, status_code=status.HTTP_201_CREATED)
async def generate_script(
    payload: ScriptGenerateRequest,
    container: ApplicationContainer = Depends(get_container),
) -> VideoScript:
    if container.settings.deepseek_api_key is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "写作模型未配置：请在 .env 中填写 DEEPSEEK_API_KEY 后重启服务，"
            "或使用「手动录入脚本」。",
        )
    script = await container.script_writing.run(payload)
    saved = container.scripts.create(script)
    container.activity.log(
        "script_generate",
        f"生成视频脚本：《{saved.title[:40]}》（{CHANNEL_LABELS[saved.channel]}）",
        channel=saved.channel,
        ref_id=saved.id,
    )
    return saved


@router.post("", response_model=VideoScript, status_code=status.HTTP_201_CREATED)
def create_manual_script(
    payload: ManualScriptRequest,
    container: ApplicationContainer = Depends(get_container),
) -> VideoScript:
    script = VideoScript(
        id=str(uuid4()),
        title=payload.title,
        topic=payload.topic,
        channel=payload.channel,
        duration_seconds=payload.duration_seconds,
        audience=payload.audience,
        hook=payload.hook,
        beats=payload.beats,
        ending=payload.ending,
        cover_idea=payload.cover_idea,
        hashtags=payload.hashtags,
        article_angle=payload.article_angle,
        source="manual",
    )
    saved = container.scripts.create(script)
    container.activity.log(
        "script_manual",
        f"录入视频脚本：《{saved.title[:40]}》",
        channel=saved.channel,
        ref_id=saved.id,
    )
    return saved


def _script_article_request(script: VideoScript) -> str:
    lines = [
        f"把下面的视频脚本扩写成一篇公众号文章。脚本主题：{script.topic}。",
        f"目标读者：{script.audience}。",
        "要求：保留脚本的核心观点与口语化开头，先联网或检索证据补足事实依据，"
        "再扩写成结构完整、有案例的图文；不得虚构数据或引用来源。",
        "—— 视频脚本开始 ——",
        f"标题：{script.title}",
        f"开场钩子：{script.hook}",
    ]
    for beat in script.beats:
        lines.append(f"[{beat.time_range}] 画面：{beat.shot}")
        lines.append(f"口播：{beat.voiceover}")
        if beat.on_screen_text:
            lines.append(f"字幕：{beat.on_screen_text}")
    lines.append(f"结尾：{script.ending}")
    if script.article_angle:
        lines.append(f"文章化建议：{script.article_angle}")
    lines.append("—— 视频脚本结束 ——")
    return "\n".join(lines)


@router.post("/{script_id}/to-article", status_code=status.HTTP_201_CREATED)
def convert_to_article(
    script_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    script = container.scripts.get(script_id)
    if script is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "脚本不存在")
    if script.task_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "该脚本已转写过公众号文章")
    spec = TaskSpec(
        id=str(uuid4()),
        mode=TaskMode.FIXED_TOPIC,
        request=_script_article_request(script),
        topic=script.topic,
        title_hint=script.title[:100],
    )
    created = container.tasks.create(spec)
    sync_topic_record(container, created)
    container.scripts.mark_converted(script_id, created.id)
    container.activity.log(
        "script_to_article",
        f"脚本转公众号文章：《{script.title[:40]}》→ 写稿任务 {created.id[:8].upper()}",
        channel=Channel.WECHAT,
        ref_id=created.id,
    )
    return {"task_id": created.id, "script": container.scripts.get(script_id)}


@router.post(
    "/{script_id}/to-post",
    response_model=ChannelPost,
    status_code=status.HTTP_201_CREATED,
)
def convert_to_post(
    script_id: str,
    payload: ConvertToPostRequest,
    container: ApplicationContainer = Depends(get_container),
) -> ChannelPost:
    script = container.scripts.get(script_id)
    if script is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "脚本不存在")
    post = container.channels.create_post(
        ChannelPostCreate(
            channel=payload.channel,
            content_type=CONTENT_TYPE_BY_CHANNEL[payload.channel],
            title=script.title,
            excerpt=script.hook,
            category="脚本改编",
            status=payload.status,
        ),
        script_id=script.id,
        source="agent",
    )
    container.activity.log(
        "script_to_post",
        f"脚本转为{CHANNEL_LABELS[payload.channel]}内容：《{script.title[:40]}》",
        channel=payload.channel,
        ref_id=post.id,
    )
    return post


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_script(
    script_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> Response:
    script = container.scripts.get(script_id)
    if script is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    container.scripts.delete(script_id)
    container.activity.log("script_delete", f"删除视频脚本：《{script.title[:40]}》")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
