from __future__ import annotations

from app.services.analytics.topics import TopicSignal, score_topics


def test_topic_scoring_returns_five_ranked_candidates_with_cold_start_limit():
    signals = [
        TopicSignal(
            topic=f"Topic {index}",
            historical_performance=0.6,
            positioning_fit=0.9 - index * 0.03,
            timeliness=0.7,
            content_gap=0.8,
            executability=0.9,
            evidence=[f"signal-{index}"],
        )
        for index in range(6)
    ]

    candidates = score_topics(signals, historical_article_count=8)

    assert len(candidates) >= 5
    assert candidates == sorted(candidates, key=lambda item: item.score, reverse=True)
    assert all("历史文章不足 20 篇" in item.limitations for item in candidates)
    assert all(item.score_breakdown.historical_performance <= 10 for item in candidates)
    assert all(item.evidence for item in candidates)
