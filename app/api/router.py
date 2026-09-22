from __future__ import annotations

from fastapi import APIRouter

from app.api import articles, capabilities, mcp, media, metrics, settings, skills, tasks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(tasks.router)
api_router.include_router(metrics.router)
api_router.include_router(articles.router)
api_router.include_router(capabilities.router)
api_router.include_router(media.router)
api_router.include_router(skills.router)
api_router.include_router(mcp.router)
api_router.include_router(settings.router)
