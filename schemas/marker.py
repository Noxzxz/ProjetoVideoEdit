from typing import Literal

from pydantic import BaseModel, ConfigDict


class MarkerPair(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float
    end: float
    cut_word: str
    resume_word: str
    kind: Literal["erro_fala", "ooc"] = "erro_fala"
