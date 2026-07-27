from pydantic import BaseModel, ConfigDict


class SubtitleStyle(BaseModel):
    model_config = ConfigDict(strict=True)
    max_words_per_line: int = 4
    font_size: int = 48


class SubtitleResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    srt_path: str
    vtt_path: str
