from __future__ import annotations

from app.domain.models import ArticleDocument, ArticleSection, AssetManifest, AssetRecord
from app.services.formatting.assets import resolve_asset_urls
from app.services.formatting.renderer import (
    article_to_markdown,
    render_markdown_to_wechat_html,
    render_wechat_html,
)
from app.services.formatting.sentinels import check_html_sentinels


def sample_article() -> ArticleDocument:
    return ArticleDocument(
        titles=["MCP、Tools 与 Skills 的边界"],
        selected_title="MCP、Tools 与 Skills 的边界",
        digest="从职责和生命周期拆解边界。",
        audience="AI 应用开发者",
        sections=[
            ArticleSection(type="paragraph", content="先看一个具体的工程问题。"),
            ArticleSection(type="heading", level=2, content="为什么容易混淆"),
            ArticleSection(
                type="code",
                language="python",
                content='print("<script>alert(1)</script>")',
            ),
            ArticleSection(
                type="table",
                rows=[["组件", "职责"], ["Skill", "判断方法"], ["Tool", "执行动作"]],
            ),
            ArticleSection(type="paragraph", content="边界清楚后，组合才会稳定。"),
        ],
        references=["https://modelcontextprotocol.io/docs"],
        ending="先明确职责，再决定接口。",
    )


def test_formatter_outputs_safe_wechat_html_with_complete_sentinels():
    article = sample_article()

    html = render_wechat_html(article)
    sentinels = check_html_sentinels(article, html)

    assert "<script" not in html.lower()
    assert "&lt;script&gt;" in html
    assert "style=" in html
    assert "MCP、Tools 与 Skills 的边界" in html
    # 来源只用于取材与追溯，不进入成稿：文末不渲染参考资料列表。
    assert "参考资料" not in html
    assert "https://modelcontextprotocol.io/docs" not in html
    assert sentinels.passed is True
    assert all(sentinels.checks.values())


def test_sentinel_fails_when_last_paragraph_is_missing():
    article = sample_article()
    html = render_wechat_html(article).replace("边界清楚后，组合才会稳定。", "")

    sentinels = check_html_sentinels(article, html)

    assert sentinels.passed is False
    assert sentinels.checks["last_paragraph"] is False


def test_formatter_deduplicates_model_supplied_title_heading():
    article = sample_article()
    article.sections.insert(
        0,
        ArticleSection(type="heading", level=1, content=article.selected_title),
    )

    html = render_wechat_html(article)

    assert html.count("<h1") == 1


def test_formatter_limits_figure_width_for_wechat_articles():
    article = sample_article()
    article.sections.append(ArticleSection(type="figure", asset_id="img-00", caption="架构图"))

    html = render_wechat_html(article)

    assert 'max-width:560px' in html


def test_asset_resolution_applies_article_image_size_to_existing_html():
    html = '<img data-asset-id="img-00" alt="架构图" />'
    manifest = AssetManifest(
        task_id="task-1",
        items=[AssetRecord(asset_id="img-00", kind="concept")],
    )

    resolved = resolve_asset_urls(html, "task-1", manifest)

    assert 'src="/api/v1/tasks/task-1/assets/img-00"' in resolved
    assert 'max-width:560px' in resolved


def test_human_markdown_renders_as_safe_wechat_html():
    markdown = "# 人工改过的标题\n\n## 实战步骤\n\n正文。<script>alert(1)</script>\n\n- 第一步"

    html = render_markdown_to_wechat_html(markdown)

    assert "人工改过的标题" in html
    assert "实战步骤" in html
    assert "<script" not in html.lower()
    assert "style=" in html


def test_formatter_keeps_depth_sections_introduced_by_editorial_pipeline():
    article = sample_article()
    article.sections.extend(
        [
            ArticleSection(type="callout", content="关键判断：先保证幂等。"),
            ArticleSection(type="steps", items=["保存状态", "恢复执行"]),
            ArticleSection(type="quote", content="失败恢复应当是正常路径。"),
        ]
    )

    html = render_wechat_html(article)

    assert "关键判断" in html
    assert "保存状态" in html
    assert "失败恢复应当是正常路径" in html


def test_markdown_round_trip_preserves_materialized_article_asset():
    article = sample_article()
    article.sections.append(
        ArticleSection(type="figure", asset_id="img-00", caption="检查点恢复流程")
    )

    markdown = article_to_markdown(article)
    html = render_markdown_to_wechat_html(markdown)

    assert "{{ARTICLE_ASSET:img-00}}" in markdown
    assert 'data-asset-id="img-00"' in html
