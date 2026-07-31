import logging
from pathlib import Path

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None  # will be handled at runtime

from config.settings import Settings, settings
from schemas.transcript import TranscriptRaw, TranscriptSegment
from shared.exceptions import TranscriptionError
from utils.glossary_correction import build_initial_prompt_from_glossary

logger = logging.getLogger(__name__)

_model = None  # type: ignore


def _load_model(config: Settings | None = None) -> WhisperModel:
    global _model
    cfg = config or settings
    if _model is None:
        compute_type = "int8" if cfg.whisper_device == "cpu" else "float16"
        _model = WhisperModel(
            cfg.whisper_model_size,
            device=cfg.whisper_device,
            compute_type=compute_type,
        )
    return _model


def transcribe(
    audio_path: Path, video_id: str, config: Settings | None = None
) -> TranscriptRaw:
    if not audio_path.exists():
        raise TranscriptionError(f"Audio nao encontrado: {audio_path}")

    try:
        cfg = config or settings
        model = _load_model(cfg)
        initial_prompt = cfg.whisper_initial_prompt
        if not initial_prompt:
            initial_prompt = build_initial_prompt_from_glossary(
                cfg.glossary_name, glossaries_dir=cfg.glossaries_dir
            )
        segments_iter, info = model.transcribe(
            str(audio_path),
            vad_filter=cfg.whisper_vad_filter,
            vad_parameters={"threshold": cfg.whisper_vad_threshold},
            initial_prompt=initial_prompt or None,
        )

        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(segments_iter):
            # normalize confidence: avg_logprob is negative, convert to 0-1
            # max confidence if logprob >= 0, min confidence if logprob <= -2 (roughly)
            raw_conf = 1.0 + seg.avg_logprob
            confidence = max(0.0, min(1.0, raw_conf))
            segments.append(
                TranscriptSegment(
                    id=idx,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                    confidence=confidence,
                )
            )

        return TranscriptRaw(
            video_id=video_id,
            language=info.language or "pt",
            segments=segments,
        )
    except Exception as exc:
        raise TranscriptionError(f"Falha na transcricao: {exc}") from exc


def unload_whisper_model() -> None:
    global _model
    if _model is not None:
        del _model
        _model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("Modelo Whisper descarregado da VRAM")
