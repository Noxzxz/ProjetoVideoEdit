import logging
import re
import unicodedata
from pathlib import Path

from config.settings import Settings
from schemas.marker import MarkerPair
from schemas.transcript import TranscriptRaw
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


def _strip_accents(text: str) -> str:
    """Remove diacritics (acentos) de uma string para matching diacritic-insensitive."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _detect_pair(
    transcript: TranscriptRaw,
    start_word: str,
    end_word: str,
    kind: str,
) -> list[MarkerPair]:
    pairs: list[MarkerPair] = []
    start_indices: list[tuple[int, object]] = []
    end_indices: list[tuple[int, object]] = []

    start_stripped = _strip_accents(start_word)
    pattern = re.compile(rf"\b{re.escape(start_stripped)}\b", re.IGNORECASE)

    for i, seg in enumerate(transcript.segments):
        seg_text = _strip_accents(seg.text)
        if pattern.search(seg_text):
            start_indices.append((i, seg))

    end_stripped = _strip_accents(end_word)
    pattern_end = re.compile(rf"\b{re.escape(end_stripped)}\b", re.IGNORECASE)

    for i, seg in enumerate(transcript.segments):
        seg_text = _strip_accents(seg.text)
        if pattern_end.search(seg_text):
            end_indices.append((i, seg))

    end_cursor = 0  # proximo end disponivel (indice na lista de ends)

    for start_idx, start_seg in start_indices:
        while end_cursor < len(end_indices) and end_indices[end_cursor][0] <= start_idx:
            end_cursor += 1
        if end_cursor >= len(end_indices):
            logger.warning(
                f"Marcador '{start_word}' em {start_seg.start:.1f}s "
                f"sem '{end_word}' correspondente. Ignorando."
            )
            break

        end_idx, end_seg = end_indices[end_cursor]
        end_cursor += 1  # consome o end para que próximo start use o seguinte
        pairs.append(
            MarkerPair(
                start=start_seg.start,
                end=end_seg.end,
                cut_word=start_word,
                resume_word=end_word,
                kind=kind,
            )
        )
        logger.info(
            f"Marcador [{kind}]: {start_word} em {start_seg.start:.1f}s "
            f"-> retorno em {end_seg.end:.1f}s"
        )

    return pairs


def detect_markers(
    transcript: TranscriptRaw,
    cut_word: str,
    resume_word: str,
    ooc_pause_word: str | None = None,
    ooc_resume_word: str | None = None,
) -> list[MarkerPair]:
    """Detecta pares de marcadores de voz: erro de fala (corte) e OOC (D25)."""
    pairs = _detect_pair(transcript, cut_word, resume_word, "erro_fala")
    if ooc_pause_word and ooc_resume_word:
        pairs += _detect_pair(transcript, ooc_pause_word, ooc_resume_word, "ooc")
    return pairs


class MarkerDetectionAgent:
    def run(self, transcript: TranscriptRaw, config: Settings) -> list[MarkerPair]:
        return detect_markers(
            transcript,
            config.marker_cut_word,
            config.marker_resume_word,
            ooc_pause_word=config.ooc_pause_word,
            ooc_resume_word=config.ooc_resume_word,
        )

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        cache_dir = get_cache_dir(video_hash)
        transcript_data = load_json(cache_dir / "transcript.json")
        if not transcript_data:
            raise FileNotFoundError(f"Transcricao nao encontrada no cache para hash {video_hash}")
        transcript = TranscriptRaw(**transcript_data)
        pairs = self.run(transcript, config)
        save_json(cache_dir / "markers.json", [p.model_dump() for p in pairs])
        logger.info(f"{len(pairs)} par(es) de marcador detectados")
