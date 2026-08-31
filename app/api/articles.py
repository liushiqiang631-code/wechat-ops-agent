from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.domain.enums import TaskStatus
from app.domain.models import (
    ArticleDocument,
    EditDiffReport,
    GenUiDocument,
    PublicationRecord,
    RepurposedContent,
    TaskRecord,
    TopicRecord,
)
from app.services.analytics.topic_feedback import backfill_published_metrics
from app.services.feedback.diff import diff_final_version
from app.services.formatting.renderer import (
    article_to_markdown,
    markdown_title,
    render_markdown_to_wechat_html,
)
from app.services.genui.renderer import render_genui_static_html

router = APIRouter(prefix="/articles", tags=["articles"])


class FinalVersionRequest(BaseModel):
    generated_markdown: str = Field(max_length=1_000_000)
    final_markdown: str = Field(min_length=3, max_length=1_000_000)


@router.post("/{task_id}/final-version", response_model=EditDiffReport)
def import_final_version(
    task_id: str,
    payload: FinalVersionRequest,
    container: ApplicationContainer = Depends(get_container),
) -> EditDiffReport:
    try:
        task = container.tasks.get(task_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc
    if task.status not in {TaskStatus.FORMATTED, TaskStatus.NEEDS_HUMAN}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "只有待人工审阅的任务可以保存终稿；已审阅后如需改稿，请创建新任务",
        )
    diff = diff_final_version(payload.generated_markdown, payload.final_markdown)
    container.artifacts.write_json(task_id, "final_version", {"markdown": payload.final_markdown})
    supplemental_html = ""
    try:
        supplemental_html = render_genui_static_html(
            GenUiDocument.model_validate(container.artifacts.read_json(task_id, "genui"))
        )
    except (FileNotFoundError, ValueError):
        pass
    final_html = render_markdown_to_wechat_html(payload.final_markdown)
    if supplemental_html:
        final_html = f"{final_html}{supplemental_html}"
    container.artifacts.write_json(
        task_id,
        "final_wechat_html",
        {"html": final_html, "title": markdown_title(payload.final_markdown)},
    )
    container.artifacts.write_json(task_id, "human_edit_diff", diff.model_dump(mode="json"))
    return diff


@router.get("/{task_id}/editorial-diff", response_model=EditDiffReport)
def editorial_diff(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> EditDiffReport:
    try:
        return EditDiffReport.model_validate(
            container.artifacts.read_json(task_id, "human_edit_diff")
        )
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "尚未导入人工终稿") from exc


@router.get("/{task_id}/draft-markdown")
def draft_markdown(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    try:
        article_payload = container.artifacts.read_json(task_id, "article")
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务尚无文章") from exc
    markdown = article_to_markdown(ArticleDocument.model_validate(article_payload))
    try:
        final_version = container.artifacts.read_json(task_id, "final_version")
        markdown = str(final_version.get("markdown", markdown))
    except FileNotFoundError:
        pass
    return {"markdown": markdown}


@router.post("/{task_id}/repurpose", response_model=RepurposedContent)
async def repurpose_article(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> RepurposedContent:
    try:
        article_payload = container.artifacts.read_json(task_id, "article")
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务尚无文章") from exc
    article = ArticleDocument.model_validate(article_payload)
    content = await container.repurpose.run(task_id, article)
    container.artifacts.write_json(task_id, "repurposed", content.model_dump(mode="json"))
    return content


@router.post("/{task_id}/mark-reviewed", response_model=TaskRecord)
def mark_reviewed(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> TaskRecord:
    try:
        current = container.tasks.get(task_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc
    if current.status not in {
        TaskStatus.NEEDS_HUMAN,
        TaskStatus.FORMATTED,
        TaskStatus.WECHAT_DRAFTED,
    }:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "只有 FORMATTED / NEEDS_HUMAN / WECHAT_DRAFTED 任务可以标记已审阅"
            f"（当前 {current.status.value}）",
        )
    return container.tasks.transition(task_id, TaskStatus.HUMAN_REVIEWED)


@router.post("/{task_id}/mark-published", response_model=PublicationRecord)
def mark_published(
    task_id: str,
    publication: PublicationRecord,
    container: ApplicationContainer = Depends(get_container),
) -> PublicationRecord:
    if publication.task_id != task_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "task_id 不一致")
    try:
        current = container.tasks.get(task_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc
    if current.status != TaskStatus.HUMAN_REVIEWED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"只有 HUMAN_REVIEWED 任务可以登记发布（当前 {current.status.value}）",
        )
    try:
        return container.publications.register_published(publication)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/{task_id}/backfill-metrics", response_model=TopicRecord)
def backfill_metrics(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> TopicRecord:
    """按标题匹配导入指标，回填已发布文章的实测表现。"""
    try:
        return backfill_published_metrics(container, task_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
