from pydantic import BaseModel, ConfigDict, Field, model_validator


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int
    start: float
    end: float
    text: str
    confidence: float = Field(ge=0, le=1)


class TranscriptRaw(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    language: str
    segments: list[TranscriptSegment]
    full_text: str = ""

    @model_validator(mode="after")
    def compute_full_text(self):
        self.full_text = " ".join(s.text.strip() for s in self.segments)
        return self


class TranscriptCleaned(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    segments: list[TranscriptSegment]
    full_text_cleaned: str
