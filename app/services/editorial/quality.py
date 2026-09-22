from __future__ import annotations

import re

from app.domain.models import (
    ArticleDocument,
    ArticleQualityIssue,
    ArticleQualityReport,
    EditorialBlueprint,
    ResearchPack,
    TaskConstraints,
)

_CJK = re.compile(r"[\u3400-\u9fff]")
_LATIN_WORD = re.compile(r"\b[A-Za-z0-9][A-Za-z0-9_+.-]*\b")


def _word_count(article: ArticleDocument) -> int:
    text = "\n".join(
        [
            article.selected_title,
            article.digest,
            *(section.content or "" for section in article.sections),
            *(" ".join(section.items) for section in article.sections),
            article.ending,
        ]
    )
    return len(_CJK.findall(text)) + len(_LATIN_WORD.findall(text))


def evaluate_article(
    article: ArticleDocument,
    research: ResearchPack,
    constraints: TaskConstraints,
    blueprint: EditorialBlueprint,
) -> ArticleQualityReport:
    issues: list[ArticleQualityIssue] = []
    word_count = _word_count(article)
    minimum = max(1_800, int(constraints.target_words * 0.8))
    headings = [section for section in article.sections if section.type == "heading"]
    allowed_claim_refs = {
        claim.source_snapshot_hash
        for claim in research.claims
        if claim.source_snapshot_hash is not None
    }
    used_claim_refs = {
        ref for section in article.sections for ref in section.claim_refs
    }
    invalid_claim_refs = sorted(used_claim_refs - allowed_claim_refs)
    blueprint_claim_refs = {
        ref for section in blueprint.sections for ref in section.claim_refs
    }
    missing_blueprint_refs = sorted(blueprint_claim_refs - used_claim_refs)

    if word_count < minimum:
        issues.append(
            ArticleQualityIssue(
                code="article_too_short",
                message=f"正文信息量不足：{word_count}，最低要求 {minimum}",
            )
        )
    if len(headings) < 5:
        issues.append(
            ArticleQualityIssue(
                code="too_few_sections",
                message="文章至少需要 5 个有效二/三级章节",
            )
        )
    elif len(headings) > 8:
        issues.append(
            ArticleQualityIssue(
                code="too_many_sections",
                message="文章最多保留 8 个有效二/三级章节，请合并重复内容",
            )
        )
    if invalid_claim_refs:
        issues.append(
            ArticleQualityIssue(
                code="unknown_claim_ref",
                message=f"文章引用了不存在的来源快照：{', '.join(invalid_claim_refs)}",
            )
        )
    if research.claims and not used_claim_refs:
        issues.append(
            ArticleQualityIssue(
                code="missing_evidence_bindings",
                message="文章没有把事实段落绑定到任何来源快照",
            )
        )
    if missing_blueprint_refs:
        issues.append(
            ArticleQualityIssue(
                code="blueprint_evidence_not_used",
                message=f"文章未兑现策划中的来源绑定：{', '.join(missing_blueprint_refs)}",
            )
        )

    heading_text = "\n".join(section.content or "" for section in headings)
    if not re.search(r"机制|原理|为什么|内部", heading_text):
        issues.append(
            ArticleQualityIssue(code="missing_mechanism_section", message="缺少机制解释章节")
        )
    if not re.search(r"实战|案例|代码|落地|演示", heading_text):
        issues.append(
            ArticleQualityIssue(code="missing_practice_section", message="缺少实战或案例章节")
        )
    if not re.search(r"边界|限制|误区|失败|不适用", heading_text):
        issues.append(
            ArticleQualityIssue(code="missing_boundary_section", message="缺少适用边界或反例")
        )
    has_action = any(section.type == "steps" for section in article.sections) or bool(
        re.search(r"清单|步骤|行动|落地", heading_text)
    )
    if not has_action:
        issues.append(
            ArticleQualityIssue(code="missing_action_section", message="缺少可执行行动清单")
        )
    if constraints.need_code and not any(
        section.type == "code" and section.code_status in {"verified", "pseudocode"}
        for section in article.sections
    ):
        issues.append(
            ArticleQualityIssue(
                code="missing_verified_code",
                message="需要代码时必须提供已验证代码或明确标注伪代码",
            )
        )

    return ArticleQualityReport(
        passed=not issues,
        word_count=word_count,
        minimum_word_count=minimum,
        heading_count=len(headings),
        invalid_claim_refs=invalid_claim_refs,
        issues=issues,
    )
