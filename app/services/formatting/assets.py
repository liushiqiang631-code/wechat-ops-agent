from __future__ import annotations

import re

from app.domain.models import AssetManifest

WECHAT_ARTICLE_IMAGE_STYLE = (
    "display:block;width:auto;max-width:100%;height:auto;max-height:360px;"
    "object-fit:contain;margin:18px auto 8px;border-radius:8px;"
)
_ASSET_TAG = re.compile(
    r'<img\b(?P<attrs>[^>]*\bdata-asset-id="(?P<asset_id>[^"]+)"[^>]*)/?>'
)
_IMAGE_STYLE_OR_SOURCE = re.compile(r'\s+(?:src|style)="[^"]*"')


def resolve_asset_urls(html: str, task_id: str, manifest: AssetManifest | None) -> str:
    """Point figure images at the local asset endpoint when the file exists.

    The renderer keeps images abstract (``data-asset-id`` only) because the
    renderer itself is task-agnostic; this helper is applied where a concrete
    task context is available (preview, review page, draft push).
    """
    ready = (
        {item.asset_id for item in manifest.items if item.status == "ready"} if manifest else set()
    )

    def replace(match: re.Match[str]) -> str:
        asset_id = match.group("asset_id")
        if asset_id not in ready:
            return '<span style="color:#6b7280;font-size:13px;">配图尚未就绪</span>'
        attrs = _IMAGE_STYLE_OR_SOURCE.sub("", match.group("attrs"))
        return (
            f'<img{attrs} src="/api/v1/tasks/{task_id}/assets/{asset_id}" '
            f'style="{WECHAT_ARTICLE_IMAGE_STYLE}" />'
        )

    return _ASSET_TAG.sub(replace, html)
