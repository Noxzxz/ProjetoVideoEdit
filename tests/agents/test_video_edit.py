import pytest

from agents.video_edit.agent import build_cut_list
from shared.exceptions import EditingError


def _mock_config(**kwargs):
    defaults = {
        "min_gap_seconds": 0.6,
        "silence_pre_padding_ms": 100,
        "silence_post_padding_ms": 150,
    }
    defaults.update(kwargs)
    return type("Settings", (), defaults)()


def test_empty_segments_raises_error():
    with pytest.raises(EditingError):
        build_cut_list(
            {"video_id": "test", "original_path": "/fake/video.mp4"},
            {"segments": []},
            _mock_config(),
        )


def test_build_cut_list_keeps_speech_intervals():
    config = _mock_config()
    video = {"video_id": "test", "original_path": "/fake/video.mp4"}
    transcript = {
        "segments": [
            {"start": 0.0, "end": 2.5, "text": "fala 1"},
            {"start": 3.0, "end": 5.0, "text": "fala 2"},
        ],
    }
    cut_list = build_cut_list(video, transcript, config)
    assert len(cut_list.segments_to_keep) == 1  # merged due to gap <= 0.6
    assert cut_list.video_id == "test"
    assert cut_list.total_duration_kept > 0


def test_build_cut_list_separates_distant_intervals():
    config = _mock_config()
    video = {"video_id": "test", "original_path": "/fake/video.mp4"}
    transcript = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "fala 1"},
            {"start": 10.0, "end": 12.0, "text": "fala 2"},
        ],
    }
    cut_list = build_cut_list(video, transcript, config)
    assert len(cut_list.segments_to_keep) == 2  # not merged, gap > 0.6


def test_no_valid_intervals_raises_error():
    config = _mock_config()
    video = {"video_id": "test", "original_path": "/fake/video.mp4"}
    transcript = {"segments": []}
    with pytest.raises(EditingError):
        build_cut_list(video, transcript, config)
