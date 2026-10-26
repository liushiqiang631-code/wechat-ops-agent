from datetime import UTC, datetime

from app.domain.models import ResearchClaim, ResearchPack
from app.skills.common import canonical_claim_refs


def research():
    return ResearchPack(
        topic="鱼教授",
        sources=["https://kb.example/documents.html?source=document-id"],
        claims=[
            ResearchClaim(
                claim="产品为双源营养剂",
                source_url="https://kb.example/documents.html?source=document-id",
                source_title="产品",
                publisher="知识库",
                retrieved_at=datetime.now(UTC),
                source_type="knowledge_base",
                confidence=0.9,
                source_snapshot_hash="actual-snapshot",
            )
        ],
    )


def test_document_id_in_a_known_source_url_resolves_to_the_actual_snapshot():
    assert canonical_claim_refs(["document-id", "actual-snapshot", "unknown"], research()) == [
        "actual-snapshot",
        "unknown",
    ]


def test_unknown_or_ambiguous_aliases_are_not_silently_given_another_source():
    pack = research()
    pack.claims.append(pack.claims[0].model_copy(update={"source_snapshot_hash": "other-snapshot"}))
    assert canonical_claim_refs(["document-id", "unknown"], pack) == ["document-id", "unknown"]
