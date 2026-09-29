from __future__ import annotations

import re
from html import escape

import bleach
import markdown as markdown_lib
from bleach.css_sanitizer import CSSSanitizer
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

from app.domain.models import ArticleDocument, ArticleSection
from app.services.formatting.assets import WECHAT_ARTICLE_IMAGE_STYLE

# Server-side, inline-styled syntax highlighting: WeChat strips <style> and
# <script>, so tokens are rendered as <span style="..."> at build time.
CODE_FORMATTER = HtmlFormatter(nowrap=True, noclasses=True, style="friendly")
_ASSET_MARKER = re.compile(r"\{\{ARTICLE_ASSET:([A-Za-z0-9_-]{1,80})\}\}")

CSS = {
    "article": "max-width:677px;margin:0 auto;color:#1f2937;font-size:16px;line-height:1.85;",
    "h1": "font-size:26px;line-height:1.35;color:#12395b;margin:0 0 24px;font-weight:700;",
    "h2": "font-size:21px;line-height:1.45;color:#12395b;margin:32px 0 12px;font-weight:700;",
    "h3": "font-size:18px;line-height:1.5;color:#1c5c71;margin:24px 0 10px;font-weight:700;",
    "p": "margin:0 0 18px;text-align:justify;",
    "codeblock": (
        "margin:18px 0;background:#f6f8fa;border:1px solid #e1e4e8;"
        "border-radius:8px;overflow:hidden;"
    ),
    "codelabel": (
        "margin:0;padding:6px 14px;background:#eef1f4;color:#57606a;font-size:12px;"
        "font-weight:600;letter-spacing:0.5px;text-transform:uppercase;"
        "font-family:Consolas,Menlo,monospace;border-bottom:1px solid #e1e4e8;"
    ),
    "pre": (
        "margin:0;padding:14px 16px;background:#f6f8fa;overflow-x:auto;"
        "white-space:pre-wrap;word-break:break-word;"
    ),
    "code": "font-family:Consolas,Menlo,monospace;font-size:13.5px;line-height:1.7;color:#24292f;",
    "table": "width:100%;border-collapse:collapse;margin:20px 0;font-size:14px;",
    "th": "padding:9px;border:1px solid #cbd5e1;background:#12395b;color:#fff;text-align:left;",
    "td": "padding:9px;border:1px solid #cbd5e1;vertical-align:top;",
    "li": "margin:5px 0;",
    "callout": (
        "margin:20px 0;padding:14px 16px;background:#eef6ff;"
        "border-left:4px solid #1c5c71;color:#20384a;"
    ),
    "quote": (
        "margin:20px 0;padding:4px 0 4px 16px;border-left:3px solid #94a3b8;"
        "color:#475569;font-style:italic;"
    ),
}


def _highlight_code(language: str | None, content: str | None) -> str:
    """Highlight code server-side; fall back to plain escaping for any failure."""
    language = (language or "text").strip().lower() or "text"
    try:
        lexer = get_lexer_by_name(language, stripnl=False)
        return highlight(content or "", lexer, CODE_FORMATTER)
    except (ClassNotFound, ValueError):
        return escape(content or "")


def _render_section(section: ArticleSection) -> str:
    if section.type == "paragraph":
        return f'<p style="{CSS["p"]}">{escape(section.content or "")}</p>'
    if section.type == "heading":
        tag = f"h{section.level}"
        return f'<{tag} style="{CSS[tag]}">{escape(section.content or "")}</{tag}>'
    if section.type == "code":
        language = escape(section.language or "text")
        body = _highlight_code(section.language, section.content)
        return (
            f'<section style="{CSS["codeblock"]}">'
            f'<p style="{CSS["codelabel"]}">{language}</p>'
            f'<pre style="{CSS["pre"]}"><code data-language="{language}" '
            f'style="{CSS["code"]}">{body}</code></pre>'
            f"</section>"
        )
    if section.type == "table":
        rows: list[str] = []
        for index, row in enumerate(section.rows):
            tag = "th" if index == 0 else "td"
            rows.append(
                "<tr>"
                + "".join(f'<{tag} style="{CSS[tag]}">{escape(cell)}</{tag}>' for cell in row)
                + "</tr>"
            )
        return f'<table style="{CSS["table"]}"><tbody>{"".join(rows)}</tbody></table>'
    if section.type == "list":
        items = "".join(f'<li style="{CSS["li"]}">{escape(item)}</li>' for item in section.items)
        return f"<ul>{items}</ul>"
    if section.type == "steps":
        items = "".join(f'<li style="{CSS["li"]}">{escape(item)}</li>' for item in section.items)
        return f"<ol>{items}</ol>"
    if section.type == "callout":
        return f'<section style="{CSS["callout"]}">{escape(section.content or "")}</section>'
    if section.type == "quote":
        return f'<blockquote style="{CSS["quote"]}">{escape(section.content or "")}</blockquote>'
    if section.type == "figure":
        return (
            f'<p style="{CSS["p"]}"><img data-asset-id="{escape(section.asset_id or "")}" '
            f'alt="{escape(section.caption or "文章配图")}" '
            f'style="{WECHAT_ARTICLE_IMAGE_STYLE}" /></p>'
        )
    return ""


def article_to_markdown(article: ArticleDocument) -> str:
    """Render a structured article back to editable Markdown for human review."""
    parts: list[str] = [f"# {article.selected_title}", "", article.digest, ""]
    for section in article.sections:
        if section.type == "heading":
            parts.append(f"{'#' * (section.level or 2)} {section.content}")
        elif section.type == "paragraph":
            parts.append(section.content or "")
        elif section.type == "code":
            parts.append(f"```{section.language or 'text'}\n{section.content}\n```")
        elif section.type == "list":
            parts.extend(f"- {item}" for item in section.items)
        elif section.type == "steps":
            parts.extend(f"{index}. {item}" for index, item in enumerate(section.items, 1))
        elif section.type == "callout":
            parts.append(f"> **关键提示：** {section.content}")
        elif section.type == "quote":
            parts.append(f"> {section.content}")
        elif section.type == "table":
            rows = section.rows
            if rows:
                header = rows[0]
                parts.append("| " + " | ".join(header) + " |")
                parts.append("| " + " | ".join(["---"] * len(header)) + " |")
                for row in rows[1:]:
                    parts.append("| " + " | ".join(row) + " |")
        elif section.type == "figure":
            parts.append(f"[配图：{section.caption or '待生成'}]")
            if section.asset_id:
                parts.append(f"{{{{ARTICLE_ASSET:{section.asset_id}}}}}")
        parts.append("")
    parts.extend(["", f"**结尾：**{article.ending}"])
    return "\n".join(parts).strip() + "\n"


def render_markdown_to_wechat_html(markdown_text: str) -> str:
    """Render an operator-edited Markdown final version into WeChat-safe HTML."""

    markdown_text = _ASSET_MARKER.sub(
        lambda match: (
            f'<img data-asset-id="{match.group(1)}" alt="文章配图" '
            f'style="{WECHAT_ARTICLE_IMAGE_STYLE}" />'
        ),
        markdown_text,
    )
    rendered = markdown_lib.markdown(
        markdown_text,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html",
    )
    replacements = {
        "h1": CSS["h1"],
        "h2": CSS["h2"],
        "h3": CSS["h3"],
        "p": CSS["p"],
        "pre": CSS["pre"],
        "code": CSS["code"],
        "table": CSS["table"],
        "th": CSS["th"],
        "td": CSS["td"],
        "li": CSS["li"],
    }
    for tag, style in replacements.items():
        rendered = re.sub(
            rf"<{tag}(?=[ >])",
            f'<{tag} style="{style}"',
            rendered,
        )
    body = f'<section style="{CSS["article"]}">{rendered}</section>'
    return bleach.clean(
        body,
        tags={
            "section",
            "h1",
            "h2",
            "h3",
            "p",
            "pre",
            "code",
            "table",
            "thead",
            "tbody",
            "tr",
            "th",
            "td",
            "ul",
            "ol",
            "li",
            "strong",
            "em",
            "blockquote",
            "a",
            "img",
        },
        attributes={
            "*": ["style"],
            "a": ["href"],
            "img": ["alt", "data-asset-id"],
        },
        protocols={"http", "https"},
        css_sanitizer=CSSSanitizer(
            allowed_css_properties={
                "max-width",
                "margin",
                "color",
                "background",
                "font-size",
                "line-height",
                "font-weight",
                "text-align",
                "padding",
                "border",
                "border-top",
                "border-radius",
                "overflow-x",
                "white-space",
                "word-break",
                "font-family",
                "width",
                "border-collapse",
                "vertical-align",
                "letter-spacing",
            }
        ),
        strip=True,
    )


def markdown_title(markdown_text: str) -> str | None:
    match = re.search(r"(?m)^\s*#\s+(.+?)\s*$", markdown_text)
    return match.group(1).strip() if match else None


def render_wechat_html(article: ArticleDocument, supplemental_html: str = "") -> str:
    normalized_sections: list[ArticleSection] = []
    for section in article.sections:
        if section.type != "heading" or section.level != 1:
            normalized_sections.append(section)
        elif (section.content or "").strip() != article.selected_title.strip():
            normalized_sections.append(section.model_copy(update={"level": 2}))
    sections = "".join(_render_section(section) for section in normalized_sections)
    body = (
        f'<section style="{CSS["article"]}">'
        f'<h1 style="{CSS["h1"]}">{escape(article.selected_title)}</h1>'
        f"{sections}"
        f'<p style="{CSS["p"]}">{escape(article.ending)}</p>'
        f"{supplemental_html}"
        "</section>"
    )
    return bleach.clean(
        body,
        tags={
            "section",
            "h1",
            "h2",
            "h3",
            "p",
            "pre",
            "code",
            "span",
            "table",
            "tbody",
            "tr",
            "th",
            "td",
            "ul",
            "ol",
            "li",
            "strong",
            "a",
            "img",
            "small",
            "blockquote",
        },
        attributes={
            "*": ["style"],
            "a": ["href"],
            "code": ["data-language"],
            "img": ["src", "alt", "data-asset-id"],
        },
        protocols={"http", "https"},
        css_sanitizer=CSSSanitizer(
            allowed_css_properties={
                "max-width",
                "margin",
                "color",
                "background-color",
                "font-size",
                "line-height",
                "font-weight",
                "font-style",
                "text-align",
                "text-decoration",
                "padding",
                "background",
                "border",
                "border-left",
                "border-top",
                "border-radius",
                "overflow-x",
                "white-space",
                "word-break",
                "font-family",
                "width",
                "border-collapse",
                "vertical-align",
                "display",
                "letter-spacing",
            }
        ),
        strip=True,
    )
