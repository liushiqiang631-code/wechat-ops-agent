from __future__ import annotations

from app.domain.models import GenUiDocument, GenUiNode
from app.services.genui.renderer import render_genui_static_html
from app.services.genui.validator import validate_genui


def test_safe_genui_document_passes_and_renders_static_html() -> None:
    document = GenUiDocument(
        title="这篇文章准备好了吗？",
        summary="用证据、结构和行动性解释当前质量。",
        nodes=[
            GenUiNode(
                type="metric_row",
                items=[
                    GenUiNode(type="metric", label="质量分", value="92", tone="good"),
                    GenUiNode(type="metric", label="引用", value="8"),
                ],
            ),
            GenUiNode(
                type="checklist",
                title="发布前检查",
                items=[
                    GenUiNode(type="check", label="事实有来源", checked=True),
                    GenUiNode(type="check", label="人工审阅", checked=False),
                ],
            ),
            GenUiNode(
                type="action",
                label="打开人工审阅",
                action="open_review",
            ),
        ],
    )

    report = validate_genui(document)
    html = render_genui_static_html(document)

    assert report.passed is True
    assert "这篇文章准备好了吗" in html
    assert "打开人工审阅" in html
    assert "script" not in html.lower()


def test_genui_rejects_unapproved_action_and_secret_like_content() -> None:
    document = GenUiDocument(
        title="风险内容",
        nodes=[
            GenUiNode(type="action", label="执行", action="delete_everything"),
            # Explicitly fictional fixture: validate credential-field blocking,
            # without including a provider-specific key-shaped token.
            GenUiNode(type="text", content="api_key=invalid-test-placeholder"),
        ],
    )

    report = validate_genui(document)

    assert report.passed is False
    assert {issue.code for issue in report.issues} == {
        "unapproved_action",
        "secret_like_content",
    }


def test_genui_depth_and_node_count_are_bounded() -> None:
    node = GenUiNode(type="group", items=[])
    for _ in range(7):
        node = GenUiNode(type="group", items=[node])
    document = GenUiDocument(title="过深", nodes=[node])

    report = validate_genui(document, max_depth=5)

    assert report.passed is False
    assert any(issue.code == "tree_too_deep" for issue in report.issues)
