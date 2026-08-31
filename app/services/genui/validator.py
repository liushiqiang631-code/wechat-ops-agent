from __future__ import annotations

import re

from app.domain.models import (
    GenUiDocument,
    GenUiNode,
    GenUiValidationIssue,
    GenUiValidationReport,
)

ALLOWED_GENUI_ACTIONS = frozenset(
    {"open_review", "copy_article", "show_sources", "show_quality"}
)
_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|authorization|secret)\s*[:=]\s*\S+|sk-[A-Za-z0-9_-]{8,}"
)


def _text_values(node: GenUiNode) -> tuple[str, ...]:
    return tuple(
        value
        for value in (node.title, node.label, node.content, node.value)
        if value is not None
    )


def validate_genui(
    document: GenUiDocument,
    *,
    max_nodes: int = 80,
    max_depth: int = 5,
) -> GenUiValidationReport:
    """Validate a model-generated UI as untrusted data, never as executable code."""

    issues: list[GenUiValidationIssue] = []
    node_count = 0
    max_depth_seen = 0

    def visit(node: GenUiNode, path: str, depth: int) -> None:
        nonlocal node_count, max_depth_seen
        node_count += 1
        max_depth_seen = max(max_depth_seen, depth)
        if depth > max_depth and not any(i.code == "tree_too_deep" for i in issues):
            issues.append(
                GenUiValidationIssue(
                    code="tree_too_deep",
                    message=f"组件树深度不能超过 {max_depth}",
                    path=path,
                )
            )
        if node.type == "action" and node.action not in ALLOWED_GENUI_ACTIONS:
            issues.append(
                GenUiValidationIssue(
                    code="unapproved_action",
                    message="动作不在本地白名单中",
                    path=f"{path}.action",
                )
            )
        for value in _text_values(node):
            if _SECRET_PATTERN.search(value):
                issues.append(
                    GenUiValidationIssue(
                        code="secret_like_content",
                        message="组件包含疑似密钥或令牌",
                        path=path,
                    )
                )
                break
        for index, child in enumerate(node.items):
            visit(child, f"{path}.items[{index}]", depth + 1)

    for index, node in enumerate(document.nodes):
        visit(node, f"nodes[{index}]", 1)
    if node_count > max_nodes:
        issues.append(
            GenUiValidationIssue(
                code="too_many_nodes",
                message=f"组件总数不能超过 {max_nodes}",
                path="nodes",
            )
        )
    return GenUiValidationReport(
        passed=not issues,
        node_count=node_count,
        max_depth_seen=max_depth_seen,
        issues=issues,
    )
