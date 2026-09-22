from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.domain.enums import TASK_RUN_IN_FLIGHT_STATUSES, EvidenceType, TaskStatus
from app.domain.models import (
    AssetManifest,
    GenUiDocument,
    StepRunReport,
    TaskRecord,
    TaskSpec,
    TitleProposal,
)
from app.services.analytics.topic_feedback import sync_topic_record
from app.services.formatting.assets import resolve_asset_urls
from app.services.genui.validator import validate_genui
from app.services.wechat.client import WeChatAPIError
from app.workflows.graph import run_content_task

router = APIRouter(prefix="/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)

ASSET_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


class DraftPushRequest(BaseModel):
    thumb_media_id: str


class ChooseTitleRequest(BaseModel):
    title: str


@router.post("", response_model=TaskRecord, status_code=status.HTTP_201_CREATED)
def create_task(
    task: TaskSpec,
    container: ApplicationContainer = Depends(get_container),
) -> TaskRecord:
    # IDs are a storage boundary. Never trust a client-provided identifier even
    # when it happens to match the safe-character contract.
    task = task.model_copy(update={"id": str(uuid4())})
    created = container.tasks.create(task)
    sync_topic_record(container, created)
    return created


@router.get("", response_model=list[TaskRecord])
def list_tasks(
    container: ApplicationContainer = Depends(get_container),
) -> list[TaskRecord]:
    return container.tasks.list()


@router.get("/{task_id}", response_model=TaskRecord)
def get_task(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> TaskRecord:
    try:
        return container.tasks.get(task_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    background_tasks: BackgroundTasks,
    container: ApplicationContainer = Depends(get_container),
) -> Response:
    try:
        task = container.tasks.get(task_id)
    except KeyError:
        # DELETE is idempotent: a repeated click or a stale browser page has
        # already reached the requested end state.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if task.status in TASK_RUN_IN_FLIGHT_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, "运行中的任务不可删除，请等待任务结束")
    protected_statuses = {
        TaskStatus.PUBLISHED,
        TaskStatus.POST_ANALYZED,
    }
    if task.status in protected_statuses:
        raise HTTPException(status.HTTP_409_CONFLICT, "已推送或发布的任务不可删除")
    container.topic_records.delete(task_id)
    try:
        container.tasks.delete(task_id)
    except KeyError:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    # Large generated-asset directories can take seconds to remove on Windows.
    # The task is already gone from the database, so clean files after the
    # response instead of leaving the button stuck on “删除中…”.
    background_tasks.add_task(container.artifacts.delete_task, task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{task_id}/propose-titles", response_model=TitleProposal)
async def propose_titles(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> TitleProposal:
    try:
        task = container.tasks.get(task_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc
    proposal = await container.titles.run(task.topic or task.request, task.request)
    container.artifacts.write_json(task_id, "title_proposal", proposal.model_dump(mode="json"))
    return proposal


@router.post("/{task_id}/choose-title", response_model=TaskRecord)
def choose_title(
    task_id: str,
    payload: ChooseTitleRequest,
    container: ApplicationContainer = Depends(get_container),
) -> TaskRecord:
    try:
        container.tasks.get(task_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc
    title = payload.title.strip()
    if len(title) < 3:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "标题至少 3 个字")
    updated = container.tasks.set_title_hint(task_id, title[:100])
    sync_topic_record(container, updated)
    return updated


@router.post("/{task_id}/run")
async def run_task(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    try:
        result = await run_content_task(task_id, container.workflow)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"任务运行失败: {exc}") from exc
    return {
        "id": task_id,
        "status": result["status"],
        "revision_round": result["revision_round"],
        "html": result.get("html"),
    }


@router.get("/{task_id}/preview")
def preview_task(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> dict:
    try:
        try:
            payload = container.artifacts.read_json(task_id, "final_wechat_html")
        except FileNotFoundError:
            payload = container.artifacts.read_json(task_id, "wechat_html")
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务尚无 HTML 预览") from exc
    html = str(payload.get("html", ""))
    manifest = _read_manifest(container, task_id)
    payload["html"] = resolve_asset_urls(html, task_id, manifest)
    return payload


@router.get("/{task_id}/steps", response_model=StepRunReport)
def task_steps(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> StepRunReport:
    try:
        return StepRunReport.model_validate(container.artifacts.read_json(task_id, "steps"))
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务尚无运行记录") from exc


@router.get("/{task_id}/genui", response_model=GenUiDocument)
def task_genui(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> GenUiDocument:
    try:
        container.tasks.get(task_id)
        document = GenUiDocument.model_validate(
            container.artifacts.read_json(task_id, "genui")
        )
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务尚无生成式界面") from exc
    report = validate_genui(document)
    if not report.passed:
        raise HTTPException(status.HTTP_409_CONFLICT, "生成式界面未通过安全校验")
    return document


@router.get("/{task_id}/assets", response_model=AssetManifest)
def task_assets(
    task_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> AssetManifest:
    manifest = _read_manifest(container, task_id)
    if manifest is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务尚无配图素材")
    return manifest


@router.get("/{task_id}/assets/{asset_id}")
def task_asset(
    task_id: str,
    asset_id: str,
    container: ApplicationContainer = Depends(get_container),
) -> FileResponse:
    if not ASSET_ID_PATTERN.match(asset_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "素材不存在")
    manifest = _read_manifest(container, task_id)
    asset = next(
        (
            item
            for item in manifest.items
            if item.asset_id == asset_id and item.status == "ready" and item.file_name
        ),
        None,
    ) if manifest is not None else None
    if asset is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "素材不存在")
    root = Path(container.settings.object_storage_path) / task_id / "assets"
    asset_dir = root.resolve()
    if asset_dir.parent != (root.parent).resolve():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "素材不存在")
    path = (root / asset.file_name).resolve()
    if path.parent != asset_dir or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "素材不存在")
    return FileResponse(path, media_type=asset.content_type)


def _read_manifest(container: ApplicationContainer, task_id: str) -> AssetManifest | None:
    try:
        return AssetManifest.model_validate(container.artifacts.read_json(task_id, "assets"))
    except FileNotFoundError:
        return None


async def _upload_inline_assets(
    container: ApplicationContainer,
    task_id: str,
    token: str,
    html: str,
) -> str:
    """Upload ready article assets to WeChat and swap local URLs for CDN URLs.

    Best-effort: a failed upload keeps the local URL (the preview still works)
    and is logged instead of blocking the draft push.
    """
    manifest = _read_manifest(container, task_id)
    if manifest is None:
        return html
    for record in manifest.items:
        if record.status != "ready" or not record.local_path:
            continue
        local_url = f"/api/v1/tasks/{task_id}/assets/{record.asset_id}"
        if local_url not in html:
            continue
        try:
            cdn_url = await container.media.upload_inline(token, Path(record.local_path))
        except Exception as error:  # noqa: BLE001 - best effort by design
            logger.warning(
                "inline asset %s upload failed for task %s: %s",
                record.asset_id,
                task_id,
                error,
            )
            continue
        html = html.replace(local_url, cdn_url)
    return html


@router.post("/{task_id}/push-draft")
async def push_draft(
    task_id: str,
    payload: DraftPushRequest,
    container: ApplicationContainer = Depends(get_container),
):
    if not container.settings.wechat_draft_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "草稿写入未启用")
    task = container.tasks.get(task_id)
    if task.status not in {TaskStatus.FORMATTED, TaskStatus.HUMAN_REVIEWED}:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"只有 FORMATTED 或 HUMAN_REVIEWED 任务可以推送草稿（当前 {task.status.value}）",
        )
    final_payload = None
    try:
        final_payload = container.artifacts.read_json(task_id, "final_wechat_html")
        html = final_payload["html"]
    except FileNotFoundError:
        html = container.artifacts.read_json(task_id, "wechat_html")["html"]
    # Prefer the article's own title/digest over the task request for the draft.
    try:
        article_payload = container.artifacts.read_json(task_id, "article")
        draft_title = str(article_payload.get("selected_title") or task.topic or task.request[:64])
        default_digest = "由微信公众号运营 Agent 生成，等待人工审核。"
        draft_digest = str(article_payload.get("digest") or default_digest)
    except FileNotFoundError:
        draft_title = task.topic or task.request[:64]
        draft_digest = "由微信公众号运营 Agent 生成，等待人工审核。"
    if final_payload and final_payload.get("title"):
        draft_title = str(final_payload["title"])
    try:
        token = await container.token_manager.get()
        html = resolve_asset_urls(html, task_id, _read_manifest(container, task_id))
        html = await _upload_inline_assets(container, task_id, token, html)
        receipt = await container.drafts.create_idempotent(
            token,
            account_id=container.settings.wechat_app_id or "unknown",
            task_id=task_id,
            article={
                "title": draft_title[:64],
                "author": (container.settings.wechat_account_name or "运营")[:8],
                "digest": draft_digest[:120],
                "content": html,
                "thumb_media_id": payload.thumb_media_id,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            },
            evidence_type=EvidenceType.REAL,
        )
    except WeChatAPIError as exc:
        # Surface the actionable guidance (e.g. IP whitelist) instead of a generic 500.
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            exc.guidance(),
        ) from exc
    updated = container.tasks.transition(task_id, TaskStatus.WECHAT_DRAFTED)
    return {"task": updated, "receipt": receipt}
