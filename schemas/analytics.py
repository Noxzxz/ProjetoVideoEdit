from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StageMetric(BaseModel):
    model_config = ConfigDict(strict=True)
    stage: str
    duration_seconds: float
    status: Literal["success", "skipped", "failed"]


class ShortMetric(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float
    end: float
    duration_seconds: float
    score: float
    reason: str
    file_name: str | None = None


class ThumbnailMetric(BaseModel):
    model_config = ConfigDict(strict=True)
    file_name: str
    sharpness_score: float
    selected_reason: str


class AnalyticsReport(BaseModel):
    model_config = ConfigDict(strict=True)
    video_hash: str
    video_name: str
    video_duration_seconds: float
    processed_at: datetime
    pipeline_version: str = "1.0.0"
    config_snapshot: dict
    stages: list[StageMetric]
    transcript_stats: dict = Field(default_factory=dict)
    content: dict = Field(default_factory=dict)
    shorts: list[ShortMetric] = Field(default_factory=list)
    thumbnails: list[ThumbnailMetric] = Field(default_factory=list)
    total_processing_time_seconds: float
    output_directory: Path
