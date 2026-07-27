import pytest

from agents.content_intelligence.agent import ContentIntelligenceAgent
from shared.exceptions import ContentGenerationError


def test_prompt_not_found_raises_error(monkeypatch):
    agent = ContentIntelligenceAgent()
    monkeypatch.setattr(
        "agents.content_intelligence.agent.settings.prompts_dir", "/inexistente/prompts"
    )
    with pytest.raises(ContentGenerationError):
        agent.run({"video_id": "test", "segments": []}, 60.0)


def test_format_transcript_capped_at_400_segments():
    agent = ContentIntelligenceAgent()
    transcript = {
        "video_id": "test",
        "segments": [{"start": i, "end": i + 1, "text": f"seg {i}"} for i in range(500)],
    }
    formatted = agent._format_transcript(transcript, max_segments=10)
    lines = formatted.strip().split("\n")
    assert len(lines) == 10
