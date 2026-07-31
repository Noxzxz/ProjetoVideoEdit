"""Config fingerprint por etapa (D27).

Determina quando o cache de uma etapa do pipeline esta invalido. Cada etapa e
sensivel a um subconjunto de settings + arquivos (prompts, glossario, campanha,
hashtags). O fingerprint e o sha256 (16 hex) do JSON ordenado dessas entradas.
"""

import hashlib
import json
from pathlib import Path

from config.settings import Settings

_LLM_MODEL_FIELDS = [
    "llm_provider",
    "ollama_model",
    "gemini_model",
    "groq_model",
    "ollama_temperature",
]

_SETTINGS_BY_STAGE: dict[str, list[str]] = {
    "VIDEO_PROCESSING": [],
    "SPEECH_RECOGNITION": [
        "whisper_model_size",
        "whisper_device",
        "whisper_vad_filter",
        "whisper_vad_threshold",
        "whisper_initial_prompt",
    ],
    "MARKER_DETECTION": [
        "marker_cut_word",
        "marker_resume_word",
        "ooc_pause_word",
        "ooc_resume_word",
    ],
    "TRANSCRIPT_CLEANING": [
        *_LLM_MODEL_FIELDS,
        "llm_call_delay_seconds",
    ],
    "CONTENT_INTELLIGENCE": [
        *_LLM_MODEL_FIELDS,
        "content_type",
        "shorts_min_duration_seconds",
        "shorts_max_duration_seconds",
        "shorts_target_count",
        "shorts_min_spacing_seconds",
        "shorts_min_standalone_score",
    ],
    "TIMELINE_VALIDATION": [
        "shorts_min_duration_seconds",
        "shorts_max_duration_seconds",
        "shorts_min_spacing_seconds",
    ],
    "VIDEO_EDIT": [
        "silence_threshold_db",
        "min_gap_seconds",
        "silence_pre_padding_ms",
        "silence_post_padding_ms",
    ],
    "SUBTITLE_STYLING": ["max_words_per_line"],
    "SHORTS_EXTRACTION": ["video_codec", "audio_codec", "video_preset"],
    "PACKAGING": [],
}


def _file_snapshot(path: Path) -> dict | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _files_by_stage(stage_name: str, config: Settings) -> dict[str, dict | None]:
    prompts = Path(config.prompts_dir)
    glossaries = Path(config.glossaries_dir)
    files: dict[str, Path] = {}

    def _maybe(path: Path | None, label: str) -> None:
        if path is not None:
            files[label] = path

    if stage_name == "SPEECH_RECOGNITION":
        if not config.whisper_initial_prompt.strip() and config.glossary_name:
            _maybe(glossaries / f"{config.glossary_name}.md", "glossary")
    elif stage_name == "TRANSCRIPT_CLEANING":
        if config.glossary_name:
            _maybe(glossaries / f"{config.glossary_name}.md", "glossary")
    elif stage_name == "CONTENT_INTELLIGENCE":
        for name in (
            "content_intelligence",
            "content_consolidation",
            "shorts_prompt",
            "standalone_check_prompt",
        ):
            _maybe(prompts / f"{name}.md", f"prompt_{name}")
        if config.glossary_name:
            _maybe(glossaries / f"{config.glossary_name}.md", "glossary")
        if config.campaign_context_file:
            _maybe(Path(config.campaign_context_file), "campaign")
        if config.hashtags_file:
            hashtag_path = Path(config.hashtags_file)
            if not hashtag_path.exists():
                hashtag_path = glossaries / config.hashtags_file
            _maybe(hashtag_path, "hashtags")

    return {label: _file_snapshot(path) for label, path in files.items()}


def compute_stage_fingerprint(stage_name: str, config: Settings) -> str:
    fields = _SETTINGS_BY_STAGE.get(stage_name, [])
    data: dict = {field: getattr(config, field, None) for field in fields}
    data.update(_files_by_stage(stage_name, config))
    raw = json.dumps(data, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_stage_fingerprints(config: Settings) -> dict[str, str]:
    return {
        stage_name: compute_stage_fingerprint(stage_name, config)
        for stage_name in _SETTINGS_BY_STAGE
    }
