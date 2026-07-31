from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    data_dir: str = "data"
    outputs_dir: str = "outputs"
    cache_dir: str = "cache"
    logs_dir: str = "logs"
    prompts_dir: str = "prompts"

    whisper_model_size: Literal["tiny", "base", "small", "medium", "large-v3"] = "small"
    whisper_device: Literal["cuda", "cpu"] = "cuda"
    whisper_vad_filter: bool = True
    whisper_vad_threshold: float = 0.5

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_temperature: float = 0.2

    llm_provider: Literal["ollama", "gemini", "groq"] = "ollama"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    sqlite_path: str = "shared/db/analytics.db"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    llm_call_delay_seconds: float = 3.0

    shorts_max_duration_seconds: int = 60
    shorts_min_duration_seconds: int = 15
    shorts_target_count: int = 4
    shorts_min_spacing_seconds: float = 30.0
    shorts_min_standalone_score: float = 0.5

    silence_threshold_db: float = -35.0
    min_gap_seconds: float = 0.6
    silence_pre_padding_ms: int = 100
    silence_post_padding_ms: int = 150

    marker_cut_word: str = "corte"
    marker_resume_word: str = "inicio"

    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_preset: str = "fast"

    max_words_per_line: int = 4

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
