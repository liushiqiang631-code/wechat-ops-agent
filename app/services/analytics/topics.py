from __future__ import annotations

from pydantic import BaseModel, Field

from app.domain.models import TopicCandidate, TopicScoreBreakdown


class TopicSignal(BaseModel):
    topic: str
    historical_performance: float = Field(ge=0, le=1)
    positioning_fit: float = Field(ge=0, le=1)
    timeliness: float = Field(ge=0, le=1)
    content_gap: float = Field(ge=0, le=1)
    executability: float = Field(ge=0, le=1)
    evidence: list[str]


def score_topics(
    signals: list[TopicSignal], *, historical_article_count: int
) -> list[TopicCandidate]:
    cold_start = historical_article_count < 20
    weights = (
        {
            "historical_performance": 10,
            "positioning_fit": 35,
            "timeliness": 25,
            "content_gap": 20,
            "executability": 10,
        }
        if cold_start
        else {
            "historical_performance": 30,
            "positioning_fit": 25,
            "timeliness": 20,
            "content_gap": 15,
            "executability": 10,
        }
    )
    candidates: list[TopicCandidate] = []
    for signal in signals:
        breakdown = TopicScoreBreakdown(
            **{
                field: round(getattr(signal, field) * weight, 2)
                for field, weight in weights.items()
            }
        )
        limitations = ["历史文章不足 20 篇", "历史表现权重已降至 10%"] if cold_start else []
        candidates.append(
            TopicCandidate(
                topic=signal.topic,
                score=round(breakdown.total, 2),
                score_breakdown=breakdown,
                reasons=[
                    f"定位匹配 {signal.positioning_fit:.0%}",
                    f"内容缺口 {signal.content_gap:.0%}",
                    f"可执行性 {signal.executability:.0%}",
                ],
                evidence=signal.evidence,
                confidence=min(
                    0.95,
                    0.45 + historical_article_count / 100 + len(signal.evidence) * 0.05,
                ),
                limitations=limitations,
            )
        )
    return sorted(candidates, key=lambda item: item.score, reverse=True)
