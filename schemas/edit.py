from pydantic import BaseModel, ConfigDict


class CutInstruction(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float
    end: float


class CutList(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    segments_to_keep: list[CutInstruction]
    total_duration_kept: float


class EditResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    output_path: str
    cut_list: CutList
