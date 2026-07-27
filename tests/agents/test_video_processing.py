from unittest.mock import patch

import pytest

from agents.video_processing.agent import VideoProcessingAgent
from shared.exceptions import AudioExtractionError, VideoNotFoundError


def test_file_not_found_raises_error():
    agent = VideoProcessingAgent()
    with pytest.raises(VideoNotFoundError):
        agent.run("/caminho/inexistente/video.mp4")


def test_missing_audio_raises_error(tmp_path):
    agent = VideoProcessingAgent()
    video_path = tmp_path / "video.mp4"
    video_path.write_text("fake video content")

    from schemas.video import VideoMetadata

    mock_metadata = VideoMetadata(
        duration_seconds=10.0,
        fps=30.0,
        width=1920,
        height=1080,
        codec="h264",
        has_audio_track=False,
    )

    with (  # noqa: SIM117
        patch("agents.video_processing.agent.compute_video_hash", return_value="abc123"),
        patch("agents.video_processing.agent.load_json", return_value=None),
        patch("agents.video_processing.agent.get_video_metadata", return_value=mock_metadata),
    ):
        with pytest.raises(AudioExtractionError):
            agent.run(str(video_path))


def test_returns_video_ingest_result_on_success(tmp_path):
    agent = VideoProcessingAgent()
    video_path = tmp_path / "video.mp4"
    video_path.write_text("fake video content")

    from schemas.video import VideoMetadata

    mock_metadata = VideoMetadata(
        duration_seconds=10.0,
        fps=30.0,
        width=1920,
        height=1080,
        codec="h264",
        has_audio_track=True,
    )

    with (
        patch("agents.video_processing.agent.compute_video_hash", return_value="abc123"),
        patch("agents.video_processing.agent.load_json", return_value=None),
        patch("agents.video_processing.agent.get_video_metadata", return_value=mock_metadata),
        patch("agents.video_processing.agent.extract_audio"),
        patch("agents.video_processing.agent.save_json"),
    ):
        result = agent.run(str(video_path))
        assert result.video_id is not None
        assert result.metadata.duration_seconds == 10.0
