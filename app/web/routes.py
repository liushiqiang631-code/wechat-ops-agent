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
    build_review_context,
    build_tasks_context,
)

router = APIRouter(tags=["console"])
templates = Jinja2Templates(directory="app/web/templates")


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_dashboard_context(container)
    context["request"] = request
    context["active_nav"] = "workbench"
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=context,
    )


@router.get("/tasks", response_class=HTMLResponse)
def tasks_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_tasks_context(container)
    context["request"] = request
    context["active_nav"] = "tasks"
    return templates.TemplateResponse(
        request=request,
        name="tasks.html",
        context=context,
    )


@router.get("/data", response_class=HTMLResponse)
def data_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_data_context(container)
    context["request"] = request
    context["active_nav"] = "data"
    return templates.TemplateResponse(
        request=request,
        name="data.html",
        context=context,
    )


@router.get("/calendar", response_class=HTMLResponse)
def calendar_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_calendar_context(container)
    context["request"] = request
    context["active_nav"] = "calendar"
    return templates.TemplateResponse(
        request=request,
        name="calendar.html",
        context=context,
    )


@router.get("/agent", response_class=HTMLResponse)
def agent_page(
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_agent_context(container)
    context["request"] = request
    context["active_nav"] = "agent"
    return templates.TemplateResponse(
        request=request,
        name="agent.html",
        context=context,
    )


@router.get("/review/{task_id}", response_class=HTMLResponse)
def review_page(
    task_id: str,
    request: Request,
    container: ApplicationContainer = Depends(get_container),
):
    context = build_review_context(container, task_id)
    context["request"] = request
    context["active_nav"] = "tasks"
    return templates.TemplateResponse(
        request=request,
        name="review.html",
        context=context,
    )
