from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import get_container
from app.container import ApplicationContainer
from app.web.omni import (
    build_approvals_context,
    build_channel_detail_context,
    build_channels_context,
    build_compare_context,
    build_logs_context,
    build_performance_context,
    build_publish_context,
    build_scripts_context,
    build_team_context,
)
from app.web.view_models import (
    build_agent_context,
    build_calendar_context,
    build_dashboard_context,
    build_data_context,
    build_drafts_context,
    build_fans_context,
    build_media_context,
    build_review_context,
    build_schedule_context,
    build_settings_context,
    build_tasks_context,
    build_topics_context,
)

router = APIRouter(tags=["console"])
templates = Jinja2Templates(directory="app/web/templates")


def _render(
    request: Request,
    name: str,
    context: dict,
    active_nav: str,
    breadcrumb: list[tuple[str, str | None]] | None = None,
) -> HTMLResponse:
    context["request"] = request
    context["active_nav"] = active_nav
    context["breadcrumb"] = breadcrumb or [("首页", None)]
    return templates.TemplateResponse(request=request, name=name, context=context)


@router.get("/", response_class=HTMLResponse)
def publish_center(
    request: Request,
    channel: str | None = None,
    status: str | None = None,
    q: str | None = None,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_publish_context(container, channel=channel, status=status, q=q)
    return _render(
        request,
        "publish.html",
        context,
        "home",
        [("首页", "/"), ("发布中心", None)],
    )


@router.get("/overview", response_class=HTMLResponse)
def overview_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_dashboard_context(container)
    return _render(
        request,
        "overview.html",
        context,
        "overview",
        [("首页", "/"), ("运营总览", None)],
    )


@router.get("/topics", response_class=HTMLResponse)
def topics_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_topics_context(container)
    return _render(request, "topics.html", context, "topics")


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_tasks_context(container)
    return _render(request, "tasks.html", context, "tasks")


@router.get("/media", response_class=HTMLResponse)
def media_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_media_context(container)
    return _render(request, "media.html", context, "media")


@router.get("/drafts", response_class=HTMLResponse)
def drafts_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_drafts_context(container)
    return _render(request, "drafts.html", context, "drafts")


@router.get("/schedule", response_class=HTMLResponse)
def schedule_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_schedule_context(container)
    return _render(request, "schedule.html", context, "schedule")


@router.get("/scripts", response_class=HTMLResponse)
def scripts_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_scripts_context(container)
    return _render(request, "scripts.html", context, "scripts", [("首页", "/"), ("脚本生成", None)])


@router.get("/data", response_class=HTMLResponse)
def data_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_data_context(container)
    return _render(request, "data.html", context, "data")


@router.get("/performance", response_class=HTMLResponse)
def performance_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_performance_context(container)
    return _render(
        request,
        "performance.html",
        context,
        "performance",
        [("首页", "/"), ("内容表现", None)],
    )


@router.get("/fans", response_class=HTMLResponse)
def fans_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_fans_context(container)
    return _render(request, "fans.html", context, "fans")


@router.get("/compare", response_class=HTMLResponse)
def compare_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_compare_context(container)
    return _render(request, "compare.html", context, "compare", [("首页", "/"), ("平台对比", None)])


@router.get("/team", response_class=HTMLResponse)
def team_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_team_context(container)
    return _render(request, "team.html", context, "team", [("首页", "/"), ("团队成员", None)])


@router.get("/approvals", response_class=HTMLResponse)
def approvals_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_approvals_context(container)
    return _render(
        request,
        "approvals.html",
        context,
        "approvals",
        [("首页", "/"), ("审批流程", None)],
    )


@router.get("/logs", response_class=HTMLResponse)
def logs_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_logs_context(container)
    return _render(request, "logs.html", context, "logs", [("首页", "/"), ("操作日志", None)])


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_calendar_context(container)
    return _render(request, "calendar.html", context, "calendar")


@router.get("/channels", response_class=HTMLResponse)
def channels_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_channels_context(container)
    return _render(
        request,
        "channels.html",
        context,
        "channels",
        [("首页", "/"), ("渠道管理", None)],
    )


@router.get("/channels/{key}", response_class=HTMLResponse)
def channel_detail_page(
    key: str,
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_channel_detail_context(container, key)
    if context is None:
        raise HTTPException(status_code=404, detail="渠道不存在")
    return _render(
        request,
        "channel_detail.html",
        context,
        f"channel-{key}",
        [("首页", "/"), ("渠道管理", "/channels"), (context["channel_page"]["label"], None)],
    )


@router.get("/workflow", response_class=HTMLResponse)
def workflow_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_agent_context(container)
    return _render(request, "workflow.html", context, "workflow")


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_settings_context(container)
    return _render(request, "settings.html", context, "settings")


@router.get("/agent", response_class=HTMLResponse)
def agent_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    """旧地址兼容：跳转到新的工作流页。"""
    context = build_agent_context(container)
    return _render(request, "workflow.html", context, "workflow")


@router.get("/review/{task_id}", response_class=HTMLResponse)
def review_page(
    task_id: str,
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_review_context(container, task_id)
    return _render(request, "review.html", context, "tasks")
