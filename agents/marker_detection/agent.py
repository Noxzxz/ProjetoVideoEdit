import logging
import re
from pathlib import Path

from config.settings import Settings
from schemas.marker import MarkerPair
from schemas.state import PipelineState
from schemas.transcript import TranscriptRaw
from shared.exceptions import PipelineError
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


class MarkerDetectionError(PipelineError):
    pass


def detect_markers(
    transcript: TranscriptRaw,
    cut_word: str,
    resume_word: str,
) -> list[MarkerPair]:
    pairs: list[MarkerPair] = []
    cut_indices: list[int] = []
    resume_indices: list[int] = []

    pattern = re.compile(rf"\b{re.escape(cut_word)}\b", re.IGNORECASE)

    for i, seg in enumerate(transcript.segments):
        if pattern.search(seg.text):
            cut_indices.append((i, seg))

    pattern_resume = re.compile(rf"\b{re.escape(resume_word)}\b", re.IGNORECASE)

    for i, seg in enumerate(transcript.segments):
        if pattern_resume.search(seg.text):
            resume_indices.append((i, seg))

    for cut_idx, cut_seg in cut_indices:
        future_resumes = [(ri, rs) for ri, rs in resume_indices if ri > cut_idx]
        if not future_resumes:
            logger.warning(
                f"Marcador 'corte' em {cut_seg.start:.1f}s sem 'inicio' correspondente. Ignorando."
            )
            continue

        resume_idx, resume_seg = future_resumes[0]
        pairs.append(
            MarkerPair(
                start=cut_seg.start,
                end=resume_seg.end,
                cut_word=cut_word,
                resume_word=resume_word,
            )
        )
        logger.info(
            f"Marcador: corte em {cut_seg.start:.1f}s -> retorno em {resume_seg.end:.1f}s"
        )

    return pairs


class MarkerDetectionAgent:
    def run(self, transcript: TranscriptRaw, config: Settings) -> list[MarkerPair]:
        return detect_markers(transcript, config.marker_cut_word, config.marker_resume_word)

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        transcript_data = load_json(cache_dir / "transcript.json")
        if not transcript_data:
            raise FileNotFoundError(f"Transcricao nao encontrada no cache para hash {video_hash}")
        transcript = TranscriptRaw(**transcript_data)
        pairs = self.run(transcript, config)
        save_json(cache_dir / "markers.json", [p.model_dump() for p in pairs])
        logger.info(f"{len(pairs)} par(es) de marcador detectados")
