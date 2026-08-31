from __future__ import annotations

import re

from app.domain.models import ArticleDocument, ArticleSection
from app.services.formatting.renderer import render_wechat_html
from app.services.formatting.sentinels import check_html_sentinels


def strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


def article_with_code(language: str = "python") -> ArticleDocument:
    return ArticleDocument(
        titles=["代码高亮"],
        selected_title="代码高亮",
        digest="检查高亮。",
        audience="AI 应用开发者",
        sections=[
            ArticleSection(type="paragraph", content="先看一段代码。"),
            ArticleSection(
                type="code",
                language=language,
                content='def hello(name):\n    print(f"hi {name}")\n    return True',
            ),
            ArticleSection(type="paragraph", content="代码高亮后更易读。"),
        ],
        references=[],
        ending="高亮结束。",
    )


def test_code_sections_are_highlighted_with_inline_spans():
    html = render_wechat_html(article_with_code())

    assert "<span" in html
    assert 'data-language="python"' in html
    assert "<script" not in html.lower()
    assert "def hello(name):" in strip_tags(html)
    # token colors are inline styles (WeChat strips stylesheets/scripts)
    assert "color:" in html


def test_unknown_language_falls_back_to_plain_escaped_code():
    html = render_wechat_html(article_with_code(language="not-a-real-language"))

    assert "<span" not in html
    assert "&lt;script&gt;" not in html
    assert "def hello(name):" in html


def test_highlighted_article_still_passes_sentinels():
    article = article_with_code()
    html = render_wechat_html(article)

    sentinels = check_html_sentinels(article, html)

    assert sentinels.passed is True
    assert all(sentinels.checks.values())
