from __future__ import annotations

from html.parser import HTMLParser

from app.domain.models import ArticleDocument, HtmlSentinelReport
from app.services.formatting.renderer import _render_style_marker, heading_text, render_inline_text


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def _visible_text(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())


def check_html_sentinels(article: ArticleDocument, html: str) -> HtmlSentinelReport:
    visible = _visible_text(html)
    def contains(text: str) -> bool:
        expected = _visible_text(_render_style_marker(text) or render_inline_text(text))
        return bool(expected) and expected in visible
    paragraphs = [
        section.content
        for section in article.sections
        if section.type == "paragraph" and section.content
    ]
    checks = {
        # Compare actual visible text so emphasis markup does not look like lost copy.
        "title": contains(heading_text(article.selected_title)),
        "first_paragraph": bool(paragraphs and contains(paragraphs[0])),
        "last_paragraph": bool(paragraphs and contains(paragraphs[-1])),
        "ending": contains(article.ending),
        "code": (
            "<code" in html if any(section.type == "code" for section in article.sections) else True
        ),
        "table": (
            "<table" in html
            if any(section.type == "table" for section in article.sections)
            else True
        ),
        # 来源只用于取材与追溯，不进入成稿：HTML 里不应出现参考资料列表。
        "no_references": "参考资料" not in html,
        "no_script": "<script" not in html.lower(),
    }
    missing = [name for name, passed in checks.items() if not passed]
    return HtmlSentinelReport(passed=not missing, checks=checks, missing=missing)
