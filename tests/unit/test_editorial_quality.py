from __future__ import annotations

from app.domain.models import (
    ArticleDocument,
    ArticleSection,
    EditorialBlueprint,
    EditorialSectionPlan,
    ResearchClaim,
    ResearchPack,
    TaskConstraints,
)
from app.services.editorial.quality import evaluate_article


def _research() -> ResearchPack:
    return ResearchPack(
        topic="LangGraph 恢复",
        claims=[
            ResearchClaim(
                claim="LangGraph 支持持久化检查点。",
                source_url="https://docs.example.com/persistence",
                source_title="Persistence",
                publisher="Example",
                retrieved_at="2026-08-23T00:00:00+08:00",
                source_type="official_doc",
                confidence=0.9,
                source_snapshot_hash="hash-persistence",
            )
        ],
        sources=["https://docs.example.com/persistence"],
    )


def _blueprint() -> EditorialBlueprint:
    return EditorialBlueprint(
        topic="LangGraph 恢复",
        reader_problem="工作流中断后只能从头执行，成本高且难以定位失败节点。",
        reader_outcome="能够设计并验证一个跨进程恢复的检查点方案。",
        thesis="恢复能力来自持久状态、幂等节点和明确重试边界的组合。",
        opening_hook="服务重启后，已经完成的研究和写作是否必须再跑一遍？",
        structure="结论-证据-实战",
        sections=[
            EditorialSectionPlan(
                heading=f"章节 {index}",
                purpose="解释机制并给出可执行判断",
                key_question=f"问题 {index}",
                claim_refs=["hash-persistence"] if index < 4 else [],
                takeaway="读者能完成一个具体检查动作",
                kind={
                    0: "context",
                    1: "mechanism",
                    2: "practice",
                    3: "boundary",
                    4: "action",
                }[index],
            )
            for index in range(5)
        ],
        boundaries=["外部副作用节点仍需独立幂等键。"],
        action_checklist=["持久化检查点", "为副作用节点增加幂等键"],
    )


def test_quality_gate_rejects_shallow_article() -> None:
    """Removing the depth and structure checks must make this test fail."""
    article = ArticleDocument(
        titles=["LangGraph 恢复机制"],
        selected_title="LangGraph 恢复机制",
        digest="解释检查点。",
        audience="AI 应用开发者",
        sections=[ArticleSection(type="paragraph", content="LangGraph 可以保存状态。")],
        references=["https://docs.example.com/persistence"],
        ending="完成。",
    )

    report = evaluate_article(
        article,
        _research(),
        TaskConstraints(target_words=2500, need_code=True),
        _blueprint(),
    )

    assert report.passed is False
    assert {issue.code for issue in report.issues} >= {
        "article_too_short",
        "too_few_sections",
        "missing_verified_code",
        "missing_action_section",
        "missing_evidence_bindings",
    }


def test_quality_gate_accepts_deep_evidence_bound_article() -> None:
    """Breaking evidence, section-kind, or code-status handling must fail this test."""
    body = "恢复并不是重新运行全部节点，而是读取持久状态后从明确边界继续。" * 45
    sections: list[ArticleSection] = [
        ArticleSection(type="paragraph", content="服务重启后，最贵的错误是把成功节点全部重跑。"),
    ]
    kinds = ["机制解释", "持久化实战", "失败边界", "排查清单", "落地步骤"]
    for index, heading in enumerate(kinds):
        sections.extend(
            [
                ArticleSection(type="heading", level=2, content=heading),
                ArticleSection(
                    type="paragraph",
                    content=body,
                    claim_refs=["hash-persistence"] if index < 2 else [],
                ),
            ]
        )
    sections.append(
        ArticleSection(
            type="code",
            language="python",
            content="print('checkpoint verified')",
            code_status="verified",
        )
    )
    sections.append(
        ArticleSection(type="steps", items=["配置检查点", "验证恢复", "检查幂等性"])
    )
    article = ArticleDocument(
        titles=["LangGraph 恢复机制"],
        selected_title="LangGraph 恢复机制",
        digest="从检查点、幂等与重试边界解释恢复。",
        audience="AI 应用开发者",
        sections=sections,
        references=["https://docs.example.com/persistence"],
        ending="按清单验证一次真实中断，恢复能力才算成立。",
    )

    report = evaluate_article(
        article,
        _research(),
        TaskConstraints(target_words=1800, need_code=True),
        _blueprint(),
    )

    assert report.passed is True
    assert report.word_count >= report.minimum_word_count
    assert report.invalid_claim_refs == []


def test_quality_gate_rejects_unknown_claim_reference() -> None:
    """Allowing article claims that have no source snapshot must fail this test."""
    article = ArticleDocument(
        titles=["证据链"],
        selected_title="证据链",
        digest="证据链",
        audience="开发者",
        sections=[
            ArticleSection(
                type="paragraph",
                content="这是一个有事实含义的段落。" * 300,
                claim_refs=["invented-hash"],
            ),
            *[
                ArticleSection(type="heading", level=2, content=f"章节 {index}")
                for index in range(5)
            ],
            ArticleSection(
                type="code", content="pass", language="python", code_status="pseudocode"
            ),
            ArticleSection(type="steps", items=["检查来源", "执行"]),
        ],
        references=["https://docs.example.com/persistence"],
        ending="检查证据。",
    )

    report = evaluate_article(
        article,
        _research(),
        TaskConstraints(target_words=1800),
        _blueprint(),
    )

    assert report.passed is False
    assert report.invalid_claim_refs == ["invented-hash"]


def test_quality_gate_reports_too_many_headings_as_a_reduction_problem() -> None:
    article = ArticleDocument(
        titles=["章节过多"],
        selected_title="章节过多",
        digest="检查结构。",
        audience="开发者",
        sections=[
            *[
                ArticleSection(type="heading", level=2, content=f"章节 {index}")
                for index in range(9)
            ],
            ArticleSection(type="paragraph", content="正文。" * 1_000),
        ],
        references=["https://docs.example.com/persistence"],
        ending="合并重复章节。",
    )

    report = evaluate_article(
        article,
        _research(),
        TaskConstraints(target_words=1800),
        _blueprint(),
    )

    issue_codes = {issue.code for issue in report.issues}
    assert "too_many_sections" in issue_codes
    assert "too_few_sections" not in issue_codes
