from pydantic import BaseModel, ConfigDict, Field


class Chapter(BaseModel):
    model_config = ConfigDict(strict=True)
    timestamp_seconds: float
    title: str = Field(max_length=60)


class ShortCandidate(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float
    end: float
    reason: str
    score: float = Field(ge=0, le=1)


class ThumbnailPromptItem(BaseModel):
    model_config = ConfigDict(strict=True)
    prompt_pt: str
    prompt_en: str
    mood: str


class SeoContent(BaseModel):
    model_config = ConfigDict(strict=True)
    title: str = Field(max_length=100)
    description: str
    hashtags: list[str]
    chapters: list[Chapter]


class SummaryContent(BaseModel):
    model_config = ConfigDict(strict=True)
    overview: str
    key_points: list[str]
    next_steps: list[str]


class ContentIntelligenceResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    seo: SeoContent
    shorts: list[ShortCandidate]
    thumbnail: list[ThumbnailPromptItem]
    summary: SummaryContent
