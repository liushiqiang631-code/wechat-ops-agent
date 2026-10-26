import pytest
from pydantic import ValidationError

from app.domain.models import ArticleDocument, ArticleSection
from app.services.formatting.renderer import (
    article_to_markdown,
    render_markdown_to_wechat_html,
    render_wechat_html,
)
from app.services.formatting.sentinels import check_html_sentinels


def article(section):
    return ArticleDocument(
        titles=["产品原理"],
        selected_title="产品原理",
        digest="说明",
        audience="种植户",
        sections=[section],
        ending="按标签使用。",
    )


@pytest.mark.parametrize("content", ["核心思想 green", "%pill 核心思想 green"])
def test_captured_pill_section_becomes_a_valid_content_marker_without_losing_evidence(content):
    section = ArticleSection.model_validate(
        {"type": "pill", "content": content, "claim_refs": ["snapshot-hash"]}
    )
    assert section.type == "paragraph"
    assert section.content == "%pill 核心思想 green"
    assert section.claim_refs == ["snapshot-hash"]


def test_unknown_sections_and_invalid_pill_shapes_remain_rejected():
    for payload in [
        {"type": "execute", "content": "anything"},
        {"type": "pill", "content": "bad unknowncolor"},
        {"type": "pill", "content": ""},
    ]:
        with pytest.raises(ValidationError):
            ArticleSection.model_validate(payload)


def test_style_marker_renders_safely_in_structured_and_editable_paths():
    value = article(ArticleSection(type="paragraph", content="%pill 核心思想 green"))
    markdown = article_to_markdown(value)
    assert "%pill 核心思想 green" in markdown
    for html in [render_wechat_html(value), render_markdown_to_wechat_html(markdown)]:
        assert "%pill" not in html
        assert "核心思想" in html
        assert "border-radius" in html
        assert "background" in html
    unsafe = render_wechat_html(
        article(ArticleSection(type="paragraph", content="%pill <img src=x onerror=alert(1)> red"))
    )
    assert "<img src=x" not in unsafe
    assert "<script" not in unsafe


def test_formula_marker_is_a_callout_and_code_examples_remain_code():
    html = render_markdown_to_wechat_html(
        "%formula 有机组分 + 有益微生物\n\n```text\n%pill 代码示例 blue\n```"
    )
    assert "%formula" not in html
    assert "有机组分 + 有益微生物" in html
    assert "%pill" in html


def test_visible_text_sentinels_compare_marker_labels_instead_of_internal_syntax():
    value = article(ArticleSection(type="paragraph", content="%pill 核心思想 green"))
    value.sections.append(ArticleSection(type="paragraph", content="%formula 组分 + 观察"))
    html = render_wechat_html(value)
    assert check_html_sentinels(value, html).passed
    assert not check_html_sentinels(value, html.replace("核心思想", "")).passed
