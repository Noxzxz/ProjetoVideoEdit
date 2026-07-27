from datetime import datetime
from pathlib import Path

from agents.packaging.agent import PackagingAgent
from schemas.state import PipelineState, StageResult


def test_build_analytics_format():
    agent = PackagingAgent()
    now = datetime.now()
    state = PipelineState(
        video_hash="abc123",
        video_path=Path("/fake/video.mp4"),
        created_at=now,
        updated_at=now,
        stages=[
            StageResult(
                stage="VIDEO_PROCESSING", status="success",
                started_at=now, finished_at=now, duration_seconds=5.0,
            ),
            StageResult(
                stage="SPEECH_RECOGNITION", status="success",
                started_at=now, finished_at=now, duration_seconds=30.0,
            ),
        ],
        completed=True,
    )
    analytics = agent._build_analytics(state, Path("/fake/output"), "abc123")
    assert analytics.video_hash == "abc123"
    assert analytics.video_name == "video.mp4"
    assert len(analytics.stages) == 2
    assert analytics.total_processing_time_seconds == 35.0
    assert analytics.stages[0].status == "success"


def test_generate_report_creates_file(tmp_path):
    agent = PackagingAgent()
    now = datetime.now()
    state = PipelineState(
        video_hash="abc123",
        video_path=Path("/fake/video.mp4"),
        created_at=now,
        updated_at=now,
        stages=[
            StageResult(
                stage="TEST_STAGE", status="success",
                started_at=now, finished_at=now, duration_seconds=1.0,
            ),
        ],
        completed=True,
    )
    agent._generate_report(state, tmp_path, "abc123")
    report_path = tmp_path / "report.md"
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "Relatorio de Processamento" in content
    assert "TEST_STAGE" in content
