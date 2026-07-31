"""Tests for PipelineRunner regressao (US-12.5)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.runner import PARALLEL_GROUP, PipelineRunner, PipelineStage


@pytest.fixture
def runner():
    from config.settings import Settings

    return PipelineRunner(Settings())


def test_register_and_run_single_stage(runner):
    video_path = Path("/fake/video.mp4")
    handler_called = False

    def handler(vp, vh, config, state):
        nonlocal handler_called
        handler_called = True

    runner.register(PipelineStage.VIDEO_PROCESSING, handler)

    with (
        patch.object(runner, "_compute_hash", return_value="abc123"),
        patch.object(runner, "_load_or_create_state") as mock_load,
        patch.object(runner, "_save_state"),
        patch("shared.preflight.PreFlightCheck.run"),
    ):
        mock_state = mock_load.return_value
        mock_state.stages = []
        mock_state.is_stage_done.return_value = False
        mock_state.video_hash = "abc123"
        mock_state.video_path = video_path

        runner.run(video_path)
        assert handler_called


def test_unique_stage_result_per_stage(runner):
    """US-12.5: Confirmar que state.stages tem exatamente 1 entrada por etapa apos run()."""
    video_path = Path("/fake/video.mp4")
    call_count = 0

    def handler(vp, vh, config, state):
        nonlocal call_count
        call_count += 1

    runner.register(PipelineStage.VIDEO_PROCESSING, handler)

    with (
        patch.object(runner, "_compute_hash", return_value="abc123"),
        patch.object(runner, "_load_or_create_state") as mock_load,
        patch.object(runner, "_save_state"),
        patch("shared.preflight.PreFlightCheck.run"),
    ):
        mock_state = mock_load.return_value
        mock_state.stages = []
        mock_state.is_stage_done.return_value = False
        mock_state.video_hash = "abc123"
        mock_state.video_path = video_path

        result = runner.run(video_path)
        video_stages = [s for s in result.stages if s.stage == "VIDEO_PROCESSING"]
        assert len(video_stages) == 1


def test_force_resets_state(runner):
    video_path = Path("/fake/video.mp4")

    def handler(vp, vh, config, state):
        pass

    runner.register(PipelineStage.VIDEO_PROCESSING, handler)

    with (
        patch.object(runner, "_compute_hash", return_value="abc123"),
        patch.object(runner, "_load_or_create_state") as mock_load,
        patch.object(runner, "_save_state"),
        patch("shared.preflight.PreFlightCheck.run"),
    ):
        mock_state = mock_load.return_value
        mock_state.stages = [MagicMock(stage="VIDEO_PROCESSING", status="success")]
        mock_state.completed = True
        mock_state.is_stage_done.return_value = True
        mock_state.video_hash = "abc123"
        mock_state.video_path = video_path

        result = runner.run(video_path, force=True)
        video_stages = [s for s in result.stages if s.status == "success"]
        assert len(video_stages) == 1  # reprocessou, logo tem 1 StageResult


def test_skip_done_stages(runner):
    video_path = Path("/fake/video.mp4")

    def handler(vp, vh, config, state):
        pass

    runner.register(PipelineStage.VIDEO_PROCESSING, handler)

    with (
        patch.object(runner, "_compute_hash", return_value="abc123"),
        patch.object(runner, "_load_or_create_state") as mock_load,
        patch.object(runner, "_save_state"),
        patch("shared.preflight.PreFlightCheck.run"),
    ):
        mock_state = mock_load.return_value
        mock_state.stages = [MagicMock(stage="VIDEO_PROCESSING", status="success")]
        mock_state.is_stage_done.return_value = True
        mock_state.video_hash = "abc123"
        mock_state.video_path = video_path

        result = runner.run(video_path)
        video_stages = [s for s in result.stages if s.stage == "VIDEO_PROCESSING"]
        assert len(video_stages) == 1


def test_parallel_group_definition():
    assert PipelineStage.SUBTITLE_STYLING in PARALLEL_GROUP
    assert PipelineStage.SHORTS_EXTRACTION in PARALLEL_GROUP
    assert len(PARALLEL_GROUP) == 2


def test_ordered_stages():
    ordered = PipelineStage.ordered()
    names = [s.name for s in ordered]
    assert names[0] == "VIDEO_PROCESSING"
    assert names[-1] == "PACKAGING"
    assert "PRE_FLIGHT" not in names
