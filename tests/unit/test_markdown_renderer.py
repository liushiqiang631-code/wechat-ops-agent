from __future__ import annotations

from app.domain.models import ArticleDocument, ArticleSection
from app.services.formatting.renderer import article_to_markdown


def build_article() -> ArticleDocument:
    return ArticleDocument(
        titles=["LangGraph 检查点"],
        selected_title="LangGraph 检查点",
        digest="失败恢复设计。",
        audience="AI 应用开发者",
        sections=[
            ArticleSection(type="paragraph", content="先看进程中断。"),
            ArticleSection(type="heading", level=2, content="检查点机制"),
            ArticleSection(type="code", language="python", content="state = checkpointer.get()"),
            ArticleSection(type="list", items=["可恢复", "幂等"]),
            ArticleSection(
                type="table",
                rows=[["方案", "成本"], ["检查点", "低"], ["重跑", "高"]],
            ),
        ],
        references=["https://docs.langchain.com/oss/python/langgraph/persistence"],
        ending="把失败恢复设计成正常路径。",
    )


def test_article_to_markdown_renders_all_section_types():
    markdown = article_to_markdown(build_article())

    assert markdown.startswith("# LangGraph 检查点")
    assert "## 检查点机制" in markdown
    assert "```python" in markdown
    assert "- 可恢复" in markdown
    assert "| 方案 | 成本 |" in markdown
    assert "| --- | --- |" in markdown
    assert "**参考资料：**" in markdown
    assert "https://docs.langchain.com" in markdown


def test_article_to_markdown_roundtrips_to_editable_text():
    markdown = article_to_markdown(build_article())

    # The generated markdown must be editable text (no HTML escaping noise).
    assert "<p" not in markdown
    assert markdown.strip()
