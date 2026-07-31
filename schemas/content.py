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
    score: float = Field(default=0.5, ge=0, le=1)
    hook_strength: float = Field(default=0.5, ge=0, le=1)
    gancho: str = ""
    payoff: str = ""
    emocao: str = ""
    standalone_score: float = Field(default=0.5, ge=0, le=1)
    standalone_notes: str = ""


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
    thumbnail_suggestions: list[str] = Field(default_factory=list)
    summary: SummaryContent
