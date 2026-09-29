from __future__ import annotations

from html import escape

from app.domain.models import ArticleDocument, HtmlSentinelReport


def check_html_sentinels(article: ArticleDocument, html: str) -> HtmlSentinelReport:
    paragraphs = [
        section.content
        for section in article.sections
        if section.type == "paragraph" and section.content
    ]
    checks = {
        # The renderer HTML-escapes text, so compare the escaped source strings.
        "title": escape(article.selected_title) in html,
        "first_paragraph": bool(paragraphs and escape(paragraphs[0]) in html),
        "last_paragraph": bool(paragraphs and escape(paragraphs[-1]) in html),
        "ending": escape(article.ending) in html,
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
