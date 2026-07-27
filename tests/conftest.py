from datetime import datetime
from pathlib import Path

import pytest

from config.settings import Settings
from schemas.content import (
    Chapter,
    ContentIntelligenceResult,
    SeoContent,
    ShortCandidate,
    SummaryContent,
    ThumbnailPromptItem,
)
from schemas.state import PipelineState, StageResult
from schemas.transcript import TranscriptCleaned, TranscriptRaw, TranscriptSegment
from schemas.video import VideoIngestResult, VideoMetadata


@pytest.fixture
def sample_video_metadata() -> VideoMetadata:
    return VideoMetadata(
        duration_seconds=120.0,
        fps=30.0,
        width=1920,
        height=1080,
        codec="h264",
        has_audio_track=True,
    )


@pytest.fixture
def sample_video_ingest(sample_video_metadata: VideoMetadata) -> VideoIngestResult:
    return VideoIngestResult(
        video_id="test-video-abc123def456",
        original_path="/fake/path/video.mp4",
        audio_path="/fake/path/audio.wav",
        metadata=sample_video_metadata,
    )


@pytest.fixture
def sample_transcript_segments() -> list[TranscriptSegment]:
    return [
        TranscriptSegment(id=0, start=0.0, end=2.5, text="Olá pessoal tudo bem", confidence=0.95),
        TranscriptSegment(id=1, start=2.5, end=5.0, text="hoje vamos aprender", confidence=0.92),
        TranscriptSegment(
            id=2, start=5.0, end=8.0,
            text="como funciona este projeto incrível", confidence=0.88,
        ),
    ]


@pytest.fixture
def sample_transcript_raw(sample_transcript_segments: list[TranscriptSegment]) -> TranscriptRaw:
    return TranscriptRaw(
        video_id="test-video-abc123def456",
        language="pt",
        segments=sample_transcript_segments,
    )


@pytest.fixture
def sample_transcript_cleaned(
    sample_transcript_segments: list[TranscriptSegment],
) -> TranscriptCleaned:
    return TranscriptCleaned(
        video_id="test-video-abc123def456",
        segments=sample_transcript_segments,
        full_text_cleaned=(
            "Olá pessoal tudo bem hoje vamos aprender "
            "como funciona este projeto incrível"
        ),
    )


@pytest.fixture
def sample_content_result() -> ContentIntelligenceResult:
    return ContentIntelligenceResult(
        video_id="test-video-abc123def456",
        seo=SeoContent(
            title="Tutorial Incrível",
            description="Aprenda como fazer",
            hashtags=["#tutorial", "#python"],
            chapters=[
                Chapter(timestamp_seconds=0.0, title="Introdução"),
                Chapter(timestamp_seconds=30.0, title="Desenvolvimento"),
            ],
        ),
        shorts=[
            ShortCandidate(start=10.0, end=25.0, reason="destaque inicial", score=0.9),
            ShortCandidate(start=50.0, end=65.0, reason="conclusão", score=0.8),
        ],
        thumbnail=[
            ThumbnailPromptItem(
                prompt_pt="Frame inicial com título",
                prompt_en="Opening frame with title",
                mood="profissional",
            ),
        ],
        summary=SummaryContent(
            overview="Visão geral do vídeo",
            key_points=["Ponto 1", "Ponto 2"],
            next_steps=["Se inscreva", "Ative o sininho"],
        ),
    )


@pytest.fixture
def sample_stage_results() -> list[StageResult]:
    now = datetime.now()
    return [
        StageResult(
            stage="VIDEO_PROCESSING", status="success",
            started_at=now, finished_at=now, duration_seconds=5.0,
        ),
        StageResult(
            stage="SPEECH_RECOGNITION", status="success",
            started_at=now, finished_at=now, duration_seconds=30.0,
        ),
    ]


@pytest.fixture
def sample_pipeline_state(sample_stage_results: list[StageResult]) -> PipelineState:
    return PipelineState(
        video_hash="abc123def4567890",
        video_path=Path("/fake/path/video.mp4"),
        created_at=datetime.now(),
        updated_at=datetime.now(),
        stages=sample_stage_results,
        current_stage=None,
        completed=True,
    )


@pytest.fixture
def sample_settings() -> Settings:
    return Settings()


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    cache.mkdir()
    return cache
