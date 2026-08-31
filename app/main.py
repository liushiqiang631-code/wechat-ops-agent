from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.router import api_router
from app.config.logging import configure_logging
from app.config.settings import Settings, get_settings
from app.container import ApplicationContainer, build_container
from app.web.routes import router as web_router


def create_app(
    settings: Settings | None = None,
    container: ApplicationContainer | None = None,
) -> FastAPI:
    active = settings or get_settings()
    configure_logging()
    application = FastAPI(
        title=active.app_name,
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )
    application.state.container = container or build_container(active)

    @application.get("/health", tags=["system"])
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "service": active.app_name,
            "version": __version__,
            "environment": active.app_env,
            "model": {
                "provider": active.text_model_provider,
                "name": active.deepseek_model,
                "configured": active.deepseek_api_key is not None,
            },
            "wechat": {
                "account": active.wechat_account_name,
                "configured": bool(active.wechat_app_id and active.wechat_app_secret),
                "draft_enabled": active.wechat_draft_enabled,
                "auto_publish": False,
            },
        }

    application.include_router(api_router)
    application.include_router(web_router)
    static_dir = Path(__file__).parent / "web" / "static"
    application.mount("/static", StaticFiles(directory=static_dir), name="static")
    return application


app = create_app()
