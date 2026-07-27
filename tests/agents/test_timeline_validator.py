"""Tests for TimelineValidatorAgent validation rules."""

from agents.timeline_validator.agent import TimelineValidatorAgent
from config.settings import settings
from schemas.content import (
    Chapter,
    ContentIntelligenceResult,
    SeoContent,
    ShortCandidate,
    SummaryContent,
)


def test_short_clamping_and_discard():
    """Testa que shorts fora do intervalo [min, max] são ajustados ou descartados."""
    agent = TimelineValidatorAgent()
    content = ContentIntelligenceResult(
        video_id="test",
        seo=SeoContent(title="", description="", hashtags=[], chapters=[]),
        shorts=[
            ShortCandidate(start=-5.0, end=2.0, reason="test", score=0.9),  # start <0
            ShortCandidate(
                start=100.0, end=110.0, reason="test", score=0.8
            ),  # beyond video duration (assume 60s)
            ShortCandidate(
                start=10.0, end=12.0, reason="test", score=0.7
            ),  # duration 2s < min 15s -> should be adjusted/clamped or discarded
            ShortCandidate(
                start=20.0, end=100.0, reason="test", score=0.6
            ),  # duration 80s > max 60s -> clamped
        ],
        thumbnail=[],
        summary=SummaryContent(overview="", key_points=[], next_steps=[]),
    )
    # We need a video duration; assume 60 seconds for test
    result = agent.run(content, video_duration_seconds=60.0)
    # Expect shorts adjusted/clamped:
    # 1. (-5,2) -> start<0 -> clamped to 0, then duration 2<15 -> discarded
    # 2. (100,110) -> clamped to 60, duration 0 -> discarded
    # 3. (10,12) -> duration 2<15 -> try extending s=0, e=12 -> still 12<15 -> discarded
    # 4. (20,100) -> end clamped to 60, duration 40 -> kept

    # Let's just assert that no short has negative timestamps or end>video_duration
    for short in result.shorts:
        assert 0 <= short.start < short.end <= 60.0
        assert (
            settings.shorts_min_duration_seconds
            <= (short.end - short.start)
            <= settings.shorts_max_duration_seconds
        )


def test_chapter_order_and_bounds():
    """Testa que capítulos são colocados em ordem crescente e dentro da duração do vídeo."""
    agent = TimelineValidatorAgent()
    content = ContentIntelligenceResult(
        video_id="test",
        seo=SeoContent(title="", description="", hashtags=[], chapters=[]),
        shorts=[],
        thumbnail=[],
        summary=SummaryContent(overview="", key_points=[], next_steps=[]),
    )
    seo = SeoContent(
        title="Test",
        description="Test",
        hashtags=[],
        chapters=[
            Chapter(timestamp_seconds=30.0, title="First"),
            Chapter(timestamp_seconds=10.0, title="Second"),  # out of order
            Chapter(timestamp_seconds=-5.0, title="Negative"),  # out of bounds
            Chapter(timestamp_seconds=70.0, title="Beyond"),  # beyond video duration (assume 60s)
            Chapter(timestamp_seconds=50.0, title="Valid"),
        ],
    )
    content.seo = seo
    result = agent.run(content, video_duration_seconds=60.0)
    chapters = result.seo.chapters
    timestamps = [ch.timestamp_seconds for ch in chapters]
    assert timestamps == sorted(timestamps)
    for ts in timestamps:
        assert 0.0 <= ts <= 60.0


def test_no_change_when_valid():
    """Testa que entradas válidas não são alteradas."""
    agent = TimelineValidatorAgent()
    content = ContentIntelligenceResult(
        video_id="test",
        seo=SeoContent(title="", description="", hashtags=[], chapters=[]),
        shorts=[
            ShortCandidate(start=10.0, end=25.0, reason="ok", score=0.9),
            ShortCandidate(start=55.0, end=75.0, reason="ok", score=0.8),
        ],
        thumbnail=[],
        summary=SummaryContent(overview="", key_points=[], next_steps=[]),
    )
    seo = SeoContent(
        title="Test",
        description="Test",
        hashtags=[],
        chapters=[
            Chapter(timestamp_seconds=5.0, title="First"),
            Chapter(timestamp_seconds=20.0, title="Second"),
            Chapter(timestamp_seconds=40.0, title="Third"),
        ],
    )
    content.seo = seo
    result = agent.run(content, video_duration_seconds=90.0)
    assert len(result.shorts) == 2
    assert result.shorts[0].start == 10.0 and result.shorts[0].end == 25.0
    assert result.shorts[1].start == 55.0 and result.shorts[1].end == 75.0
    assert len(result.seo.chapters) == 3
    assert result.seo.chapters[0].timestamp_seconds == 5.0
    assert result.seo.chapters[1].timestamp_seconds == 20.0
    assert result.seo.chapters[2].timestamp_seconds == 40.0
