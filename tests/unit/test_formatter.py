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


def test_structured_markdown_renders_bold_and_does_not_duplicate_heading_prefix():
    article = sample_article()
    article.sections = [
        ArticleSection(type="heading", level=2, content="## 02｜作用机制"),
        ArticleSection(type="paragraph", content="**抗氧化作用**：保护细胞。"),
    ]
    html = render_wechat_html(article)
    assert "<strong>抗氧化作用</strong>" in html
    assert "**" not in html
    assert "##" not in html
    assert check_html_sentinels(article, html).passed


def test_missing_manifest_does_not_render_writer_invented_asset_as_broken_image():
    article = sample_article()
    article.sections.append(
        ArticleSection(type="figure", asset_id="invented-0001", caption="微观机制")
    )
    html = resolve_asset_urls(render_wechat_html(article), "task-1", None)
    assert "<img" not in html
    assert "配图尚未就绪" in html


def test_markdown_emphasis_does_not_enable_raw_html_or_unverified_images():
    article = sample_article()
    article.sections = [ArticleSection(type="paragraph", content=(
        '**重点** <script>alert(1)</script> ![外图](https://example.com/unverified.png) '
        '[危险](javascript:alert(1))'))]
    html = render_wechat_html(article)
    assert '<strong>重点</strong>' in html
    assert '<script' not in html
    assert '<img' not in html
    assert 'href="javascript:' not in html
    assert '&lt;script&gt;' in html


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


def test_formatter_keeps_figures_compact_and_preserves_proportions():
    article = sample_article()
    article.sections.append(ArticleSection(type="figure", asset_id="img-00", caption="架构图"))

    html = render_wechat_html(article)

    assert 'max-height:360px' in html
    assert 'width:auto' in html
    assert 'max-width:100%' in html


def test_asset_resolution_applies_article_image_size_to_existing_html():
    html = '<img data-asset-id="img-00" alt="架构图" />'
    manifest = AssetManifest(
        task_id="task-1",
        items=[AssetRecord(asset_id="img-00", kind="concept")],
    )

    resolved = resolve_asset_urls(html, "task-1", manifest)

    assert 'src="/api/v1/tasks/task-1/assets/img-00"' in resolved
    assert 'max-height:360px' in resolved
    assert 'width:auto' in resolved


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
