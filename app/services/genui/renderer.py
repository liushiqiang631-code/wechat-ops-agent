from __future__ import annotations

from html import escape

from app.domain.models import GenUiDocument, GenUiNode
from app.services.genui.validator import validate_genui


def _render_node(node: GenUiNode) -> str:
    tone = escape(node.tone)
    if node.type == "divider":
        return '<hr style="border:0;border-top:1px solid #dfe4ea;margin:18px 0">'
    if node.type in {"group", "metric_row", "checklist"}:
        heading = f"<h3>{escape(node.title)}</h3>" if node.title else ""
        children = "".join(_render_node(item) for item in node.items)
        return f'<section data-genui-type="{node.type}">{heading}{children}</section>'
    if node.type == "metric":
        return (
            f'<p data-genui-type="metric" data-tone="{tone}">'
            f'<small>{escape(node.label or "指标")}</small><br>'
            f'<strong>{escape(node.value or "—")}</strong></p>'
        )
    if node.type == "check":
        marker = "✓" if node.checked else "○"
        return f'<p data-genui-type="check">{marker} {escape(node.label or "检查项")}</p>'
    if node.type == "action":
        return (
            '<p data-genui-type="action"><strong>'
            f'{escape(node.label or "在运营台继续操作")}</strong></p>'
        )
    body = node.content or node.label or ""
    heading = f"<h3>{escape(node.title)}</h3>" if node.title else ""
    return (
        f'<section data-genui-type="{node.type}" data-tone="{tone}">'
        f"{heading}<p>{escape(body)}</p></section>"
    )


def render_genui_static_html(document: GenUiDocument) -> str:
    """Render a safe static downgrade suitable for WeChat's no-JS environment."""

    report = validate_genui(document)
    if not report.passed:
        raise ValueError("unsafe GenUI document")
    summary = f"<p>{escape(document.summary)}</p>" if document.summary else ""
    nodes = "".join(_render_node(node) for node in document.nodes)
    return (
        '<section data-genui-version="1.0" '
        'style="margin:24px 0;padding:18px;border:1px solid #dfe4ea;">'
        f"<h2>{escape(document.title)}</h2>{summary}{nodes}</section>"
    )
