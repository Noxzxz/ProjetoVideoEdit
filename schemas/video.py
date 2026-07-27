from pydantic import BaseModel, ConfigDict


class VideoMetadata(BaseModel):
    model_config = ConfigDict(strict=True)
    duration_seconds: float
    fps: float
    width: int
    height: int
    codec: str
    has_audio_track: bool


class VideoIngestResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    original_path: str
    audio_path: str
    metadata: VideoMetadata
