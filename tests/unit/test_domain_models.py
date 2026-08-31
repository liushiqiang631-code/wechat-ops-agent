from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.enums import TaskMode, TaskStatus
from app.domain.models import (
    ArticleDocument,
    ArticleSection,
    ResearchClaim,
    ResearchPack,
    TaskConstraints,
    TaskSpec,
)


def test_task_spec_forbids_formal_auto_publish():
    with pytest.raises(ValidationError, match="formal publishing"):
        TaskSpec(
            mode=TaskMode.FIXED_TOPIC,
            request="写一篇 Agent 工程文章",
            constraints=TaskConstraints(auto_publish=True),
        )


def test_task_state_allows_only_declared_transitions():
    assert TaskStatus.CREATED.can_transition_to(TaskStatus.PLANNED)
    assert TaskStatus.CREATED.can_transition_to(TaskStatus.DATA_SYNCED)
    assert TaskStatus.CREATED.can_transition_to(TaskStatus.FAILED)
    assert not TaskStatus.CREATED.can_transition_to(TaskStatus.PUBLISHED)


def test_research_pack_requires_claim_source_mapping():
    with pytest.raises(ValidationError, match="at least one claim"):
        ResearchPack(topic="MCP", claims=[], sources=[])

    pack = ResearchPack(
        topic="MCP",
        claims=[
            ResearchClaim(
                claim="MCP 使用客户端-服务器架构。",
                source_url="https://modelcontextprotocol.io/docs",
                source_title="MCP Documentation",
                publisher="Model Context Protocol",
                retrieved_at="2026-07-18T00:00:00+08:00",
                source_type="official_doc",
                confidence=0.9,
            )
        ],
        sources=["https://modelcontextprotocol.io/docs"],
    )
    assert pack.claims[0].confidence == 0.9


def test_article_document_has_structured_sections_and_no_intentional_errors():
    article = ArticleDocument(
        titles=["Agent Skills 与 Tools 的边界"],
        selected_title="Agent Skills 与 Tools 的边界",
        digest="从工程职责看清边界。",
        audience="AI 应用开发者",
        sections=[
            ArticleSection(type="paragraph", content="先从一个具体问题开始。"),
            ArticleSection(type="heading", level=2, content="边界"),
        ],
        references=["https://example.com/official"],
        ending="先把职责边界画清楚，再选择技术。",
    )

    assert article.intentional_error_count == 0
    assert article.sections[1].level == 2
