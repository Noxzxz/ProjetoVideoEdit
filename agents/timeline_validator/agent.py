import logging
from pathlib import Path

from config.settings import Settings, settings
from schemas.content import Chapter, ContentIntelligenceResult, ShortCandidate
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


def _snap_to_phrase_boundary(
    timestamp: float,
    segments: list[dict],
    direction: str = "nearest",
) -> float:
    if not segments:
        return timestamp

    best = timestamp
    min_dist = float("inf")
    for seg in segments:
        s = seg.get("start", 0)
        e = seg.get("end", 0)
        for boundary in (s, e):
            if direction == "left" and boundary > timestamp:
                continue
            if direction == "right" and boundary < timestamp:
                continue
            dist = abs(boundary - timestamp)
            if dist < min_dist:
                min_dist = dist
                best = boundary
    return best


class TimelineValidatorAgent:
    def run(
        self,
        content: ContentIntelligenceResult,
        video_duration_seconds: float,
        transcript: list[dict] | None = None,
        config: Settings | None = None,
    ) -> ContentIntelligenceResult:
        """Valida e corrige timestamps (shorts e capítulos) antes do corte de vídeo real.

        Regras:
        1. Shorts: duração em [shorts_min_duration_seconds, shorts_max_duration_seconds]
        2. Capítulos: timestamp_em ordem crescente, dentro da duração do vídeo
        3. Shorts respeitam espaçamento mínimo (shorts_min_spacing_seconds)
        4. Shorts com snap para limite de frase mais próximo na transcrição limpa
        5. Todos os timestamps >= 0, < video_duration_seconds

        Retorna: novo ContentIntelligenceResult (mesma estrutura, com ajustes)
        """
        cfg = config or settings
        min_duration = cfg.shorts_min_duration_seconds
        max_duration = cfg.shorts_max_duration_seconds
        min_spacing = cfg.shorts_min_spacing_seconds

        def clamp_short(short: ShortCandidate) -> ShortCandidate | None:
            s = short.start
            e = short.end

            if s < 0:
                s = 0.0
                e = min(e, video_duration_seconds)
            if e > video_duration_seconds:
                e = video_duration_seconds
                s = max(s, 0.0)

            if e - s < min_duration:
                s = max(0.0, e - min_duration)
            if e - s > max_duration:
                e = min(video_duration_seconds, s + max_duration)

            if s > e:
                s, e = e, s

            if e - s < min_duration or e - s > max_duration:
                return None

            return short.model_copy(update={"start": s, "end": e})

        valid_chapters = []
        last_chapter_end = 0.0
        for ch in content.seo.chapters:
            clamped_start = max(0.0, min(ch.timestamp_seconds, video_duration_seconds))
            if clamped_start < last_chapter_end:
                clamped_start = last_chapter_end
            if clamped_start > video_duration_seconds:
                continue
            clamped_ch = Chapter(timestamp_seconds=clamped_start, title=ch.title)
            valid_chapters.append(clamped_ch)
            last_chapter_end = clamped_start + 1.0

        valid_shorts: list[ShortCandidate] = []
        for short in content.shorts:
            clamped = clamp_short(short)
            if clamped is None:
                logger.warning(f"Descartado ShortCandidate invalido: {short}")
                continue

            # Snap to phrase boundary
            if transcript:
                clamped.start = _snap_to_phrase_boundary(
                    clamped.start, transcript, direction="left"
                )
                clamped.end = _snap_to_phrase_boundary(
                    clamped.end, transcript, direction="right"
                )

            # Enforce minimum spacing between shorts
            if valid_shorts:
                last = valid_shorts[-1]
                if clamped.start - last.end < min_spacing:
                    clamped.start = last.end + min_spacing
                    if clamped.end - clamped.start < min_duration:
                        clamped.end = clamped.start + min_duration

            if clamped.end <= video_duration_seconds and clamped.end > clamped.start:
                valid_shorts.append(clamped)

        return ContentIntelligenceResult(
            video_id=content.video_id,
            seo=type(content.seo)(
                title=content.seo.title,
                description=content.seo.description,
                hashtags=content.seo.hashtags,
                chapters=valid_chapters,
            ),
            shorts=valid_shorts,
            thumbnail_suggestions=content.thumbnail_suggestions,
            summary=content.summary,
        )

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        content_data = load_json(cache_dir / "content.json")
        if not metadata or not content_data:
            raise FileNotFoundError("Dados necessarios nao encontrados no cache")
        video_duration = metadata["metadata"]["duration_seconds"]
        content = ContentIntelligenceResult(**content_data)
        cleaned = load_json(cache_dir / "cleaned.json")
        transcript_segments = (cleaned or {}).get("segments", [])
        result = self.run(content, video_duration, transcript_segments, config)
        save_json(cache_dir / "content.json", result.model_dump())
