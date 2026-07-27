import pytest

from agents.thumbnail_frames.agent import ThumbnailFramesAgent


def test_agent_instantiation():
    agent = ThumbnailFramesAgent()
    assert agent is not None


def test_inexistent_video_raises_error():
    """Video inexistente deve levantar VideoNotFoundError."""
    agent = ThumbnailFramesAgent()
    from config.settings import Settings
    from shared.exceptions import VideoNotFoundError

    config = Settings()
    with pytest.raises(VideoNotFoundError):
        agent.run("test-video", "/inexistente/video.mp4", config)
