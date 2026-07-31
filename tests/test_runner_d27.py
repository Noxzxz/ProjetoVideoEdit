"""Testes de invalidao por fingerprint (D27) no PipelineRunner."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from config.settings import Settings
from pipeline.fingerprint import compute_stage_fingerprints
from pipeline.runner import PipelineRunner
from schemas.state import PipelineState, StageResult


def _state_with_stages(stage_names: list[str]) -> PipelineState:
    now = datetime.now()
    stages = [
        StageResult(
            stage=name,
            status="success",
            started_at=now,
            finished_at=now,
            duration_seconds=1.0,
        )
        for name in stage_names
    ]
    return PipelineState(
        video_hash="abc123",
        video_path=Path("/fake/video.mp4"),
        created_at=now,
        updated_at=now,
        stages=stages,
    )


def _runner() -> PipelineRunner:
    return PipelineRunner(Settings())


def test_no_invalidation_when_fingerprints_match():
    runner = _runner()
    state = _state_with_stages(["VIDEO_PROCESSING", "SPEECH_RECOGNITION"])
    state.stage_fingerprints = compute_stage_fingerprints(runner.config)

    with patch.object(runner, "_save_state"):
        runner._invalidate_stale_stages(state)

    assert len(state.stages) == 2


def test_stale_stage_cascades_invalidation():
    runner = _runner()
    state = _state_with_stages(
        ["VIDEO_PROCESSING", "SPEECH_RECOGNITION", "CONTENT_INTELLIGENCE", "TIMELINE_VALIDATION"]
    )
    current = compute_stage_fingerprints(runner.config)
    state.stage_fingerprints = {
        "VIDEO_PROCESSING": current["VIDEO_PROCESSING"],
        "SPEECH_RECOGNITION": current["SPEECH_RECOGNITION"],
        "CONTENT_INTELLIGENCE": "fingerprint-antigo",
        "TIMELINE_VALIDATION": current["TIMELINE_VALIDATION"],
    }

    with patch.object(runner, "_save_state"):
        runner._invalidate_stale_stages(state)

    remaining = {s.stage for s in state.stages}
    assert remaining == {"VIDEO_PROCESSING", "SPEECH_RECOGNITION"}
    assert "CONTENT_INTELLIGENCE" not in state.stage_fingerprints
    assert "TIMELINE_VALIDATION" not in state.stage_fingerprints


def test_successful_stage_records_fingerprint():
    runner = _runner()
    now = datetime.now()
    state = PipelineState(
        video_hash="abc123",
        video_path=Path("/fake/video.mp4"),
        created_at=now,
        updated_at=now,
    )
    started = datetime.now()
    with patch.object(runner, "_save_state"):
        runner._record_stage_result(
            state, "VIDEO_PROCESSING", "success", started, started
        )
    assert "VIDEO_PROCESSING" in state.stage_fingerprints
    from pipeline.fingerprint import compute_stage_fingerprint

    assert state.stage_fingerprints["VIDEO_PROCESSING"] == compute_stage_fingerprint(
        "VIDEO_PROCESSING", runner.config
    )


def test_failed_stage_does_not_record_fingerprint():
    runner = _runner()
    now = datetime.now()
    state = PipelineState(
        video_hash="abc123",
        video_path=Path("/fake/video.mp4"),
        created_at=now,
        updated_at=now,
    )
    started = datetime.now()
    with patch.object(runner, "_save_state"):
        runner._record_stage_result(
            state, "VIDEO_PROCESSING", "failed", started, started, "boom"
        )
    assert "VIDEO_PROCESSING" not in state.stage_fingerprints
