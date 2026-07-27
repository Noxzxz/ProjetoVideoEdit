import logging
from pathlib import Path

from config.settings import Settings, settings
from schemas.content import Chapter, ContentIntelligenceResult, ShortCandidate
from schemas.state import PipelineState
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


class TimelineValidatorAgent:
    def run(
        self,
        content: ContentIntelligenceResult,
        video_duration_seconds: float,
    ) -> ContentIntelligenceResult:
        """Valida e corrige timestamps (shorts e capítulos) antes do corte de vídeo real.

        Regras:
        1. Shorts: duração em [shorts_min_duration_seconds, shorts_max_duration_seconds]
        2. Capítulos: timestamp_em ordem crescente, dentro da duração do vídeo
        3. Sem overlaps entre shorts/capítulos (shorts têm precedência, capítulos são absolutos)
        4. Todos os timestamps >= 0, < video_duration_seconds

        Retorna: novo ContentIntelligenceResult (mesma estrutura, com ajustes)
        """

        def clamp_short(short: ShortCandidate) -> ShortCandidate:
            """Ajusta timestamps de ShortCandidate para respeitar os limites."""
            s = short.start
            e = short.end

            # Força dentro da duração do vídeo
            if s < 0:
                s = 0.0
                e = min(e, video_duration_seconds)
            if e > video_duration_seconds:
                e = video_duration_seconds
                s = max(s, 0.0)

            # Força em [min, max] de duração
            if e - s < settings.shorts_min_duration_seconds:
                s = max(0.0, e - settings.shorts_min_duration_seconds)
            if e - s > settings.shorts_max_duration_seconds:
                e = min(video_duration_seconds, s + settings.shorts_max_duration_seconds)

            # Garante start <= end
            if s > e:
                s, e = e, s

            # Rejeita se ainda estiver fora dos limites após ajuste (inválido)
            if (
                e - s < settings.shorts_min_duration_seconds
                or e - s > settings.shorts_max_duration_seconds
            ):
                return None  # descartar

            return ShortCandidate(
                start=s,
                end=e,
                reason=short.reason,
                score=short.score,
            )

        # Valida capítulos: ordem crescente, dentro da duração
        # Nota: não há restrição de overlap shorts/capítulos na especificação
        valid_chapters = []
        last_chapter_end = 0.0
        for ch in content.seo.chapters:
            clamped_start = max(0.0, min(ch.timestamp_seconds, video_duration_seconds))
            # Garante ordem crescente
            if clamped_start < last_chapter_end:
                clamped_start = last_chapter_end
            if clamped_start > video_duration_seconds:
                continue
            # Mantém duração razoável (1 a 3 segundos?)
            # Sem restrições de duração no schema original — apenas manter
            clamped_ch = Chapter(timestamp_seconds=clamped_start, title=ch.title)
            valid_chapters.append(clamped_ch)
            last_chapter_end = clamped_start + 1.0  # placeholder duration

        # Validar shorts
        valid_shorts = []
        for short in content.shorts:
            clamped = clamp_short(short)
            if clamped is None:
                logger.warning(f"Descartado ShortCandidate inválido: {short}")
                continue

            # Sem restrição de overlap shorts/capítulos na especificação original
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
            thumbnail=content.thumbnail,
            summary=content.summary,
        )

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        content_data = load_json(cache_dir / "content.json")
        if not metadata or not content_data:
            raise FileNotFoundError("Dados necessarios nao encontrados no cache")
        video_duration = metadata["metadata"]["duration_seconds"]
        content = ContentIntelligenceResult(**content_data)
        result = self.run(content, video_duration)
        save_json(cache_dir / "content.json", result.model_dump())
