from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class StageResult(BaseModel):
    stage: str
    status: Literal["success", "skipped", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    output_paths: list[Path] = Field(default_factory=list)
    error_message: str | None = None


class PipelineState(BaseModel):
    video_hash: str
    video_path: Path
    created_at: datetime
    updated_at: datetime
    stages: list[StageResult] = Field(default_factory=list)
    current_stage: str | None = None
    completed: bool = False

    def last_successful_stage(self) -> str | None:
        for stage_result in reversed(self.stages):
            if stage_result.status == "success":
                return stage_result.stage
        return None

    def is_stage_done(self, stage_name: str) -> bool:
        return any(s.stage == stage_name and s.status == "success" for s in self.stages)
