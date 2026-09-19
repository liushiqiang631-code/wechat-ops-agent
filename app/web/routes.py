from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.dependencies import get_container
from app.container import ApplicationContainer
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
) -> HTMLResponse:
    context["request"] = request
    context["active_nav"] = active_nav
    return templates.TemplateResponse(request=request, name=name, context=context)


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_dashboard_context(container)
    return _render(request, "dashboard.html", context, "overview")


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


@router.get("/data", response_class=HTMLResponse)
def data_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_data_context(container)
    return _render(request, "data.html", context, "data")


@router.get("/fans", response_class=HTMLResponse)
def fans_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_fans_context(container)
    return _render(request, "fans.html", context, "fans")


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_calendar_context(container)
    return _render(request, "calendar.html", context, "calendar")


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
