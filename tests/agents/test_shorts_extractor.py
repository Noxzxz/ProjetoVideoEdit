from pathlib import Path

from agents.shorts_extractor.agent import ShortsExtractorAgent
from schemas.content import ContentIntelligenceResult, SeoContent, SummaryContent


def test_empty_shorts_returns_empty_list(tmp_path):
    agent = ShortsExtractorAgent()
    content = ContentIntelligenceResult(
        video_id="test",
        seo=SeoContent(title="T", description="D", hashtags=[], chapters=[]),
        shorts=[],
        thumbnail_suggestions=[],
        summary=SummaryContent(overview="", key_points=[], next_steps=[]),
    )
    config = type("Settings", (), {})()
    result = agent.run(
        video_path=Path("/fake/video.mp4"),
        content=content,
        output_dir=tmp_path / "shorts",
        config=config,
    )
    assert result == []
