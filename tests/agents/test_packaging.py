from datetime import datetime
from pathlib import Path

from agents.packaging.agent import PackagingAgent
from config.settings import Settings
from schemas.state import PipelineState, StageResult


def _make_state() -> PipelineState:
    now = datetime.now()
    return PipelineState(
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


def test_build_analytics_format(tmp_path):
    agent = PackagingAgent()
    cache_dir = tmp_path / "cache" / "abc123"
    cache_dir.mkdir(parents=True)
    (cache_dir / "metadata.json").write_text(
        '{"metadata": {"duration_seconds": 120.0}}', encoding="utf-8"
    )
    analytics = agent._build_analytics(
        _make_state(), Path("/fake/output"), "abc123", Settings(), cache_dir
    )
    assert analytics.video_hash == "abc123"
    assert analytics.video_name == "video.mp4"
    assert len(analytics.stages) == 2
    assert analytics.total_processing_time_seconds == 35.0
    assert analytics.stages[0].status == "success"


def test_build_analytics_populates_duration_and_snapshot(tmp_path):
    """B13: video_duration_seconds vem do metadata e config_snapshot nao expoe segredos."""
    agent = PackagingAgent()
    cache_dir = tmp_path / "cache" / "abc123"
    cache_dir.mkdir(parents=True)
    (cache_dir / "metadata.json").write_text(
        '{"metadata": {"duration_seconds": 240.0}}', encoding="utf-8"
    )
    config = Settings(gemini_api_key="segredo", groq_api_key="segredo")
    analytics = agent._build_analytics(
        _make_state(), Path("/fake/output"), "abc123", config, cache_dir
    )
    assert analytics.video_duration_seconds == 240.0
    assert "gemini_api_key" not in analytics.config_snapshot
    assert "groq_api_key" not in analytics.config_snapshot
    assert analytics.config_snapshot["llm_provider"] == config.llm_provider


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


def test_run_copies_edited_video_from_video_id_dir(tmp_path):
    """Regressao: edited.mp4 (gravado em outputs/{video_id}/) e copiado para o pacote."""
    cache_dir = tmp_path / "cache" / "abc123"
    cache_dir.mkdir(parents=True)
    video_id = "sessao-campanha-abc123"
    (cache_dir / "metadata.json").write_text(
        f'{{"video_id": "{video_id}", "metadata": {{"duration_seconds": 60.0}}}}',
        encoding="utf-8",
    )

    outputs = tmp_path / "outputs"
    edited_src = outputs / video_id / "edited.mp4"
    edited_src.parent.mkdir(parents=True)
    edited_src.write_bytes(b"fake edited video")

    now = datetime.now()
    state = PipelineState(
        video_hash="abc123",
        video_path=Path("sessao campanha.mp4"),
        created_at=now,
        updated_at=now,
        stages=[],
        completed=True,
    )

    config = Settings(outputs_dir=str(outputs), cache_dir=str(tmp_path / "cache"))
    agent = PackagingAgent()
    agent.run(Path("/fake/sessao campanha.mp4"), "abc123", config, state)

    copied = outputs / "sessao campanha" / "edited.mp4"
    assert copied.exists()
    assert copied.read_bytes() == b"fake edited video"

    zip_path = outputs / "sessao campanha.zip"
    assert zip_path.exists()
