import logging
from pathlib import Path

from config.settings import Settings
from schemas.edit import CutInstruction, CutList, EditResult
from schemas.state import PipelineState
from services.ffmpeg_service import apply_cut_list
from shared.exceptions import EditingError
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


def build_cut_list(
    video_ingest: dict,
    transcript: dict,
    config: Settings,
) -> CutList:
    """Constroi lista de cortes baseada em silencios/transcricao."""
    segments = transcript.get("segments", [])
    if not segments:
        raise EditingError("Nenhum segmento de transcricao para construir lista de cortes")

    video_id = video_ingest.get("video_id", "unknown")

    # Mantem todos os segmentos com fala (nao corta silencios entre segmentos)
    # Estrategia simples: manter intervalos dos segmentos de transcricao
    kept_intervals = []
    for seg in segments:
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        if end > start:
            kept_intervals.append(CutInstruction(start=start, end=end))

    if not kept_intervals:
        raise EditingError("Nenhum intervalo valido para manter apos analise")

    # Merge intervals that overlap or are close (within min_gap_seconds)
    merged = [kept_intervals[0]]
    gap = config.min_gap_seconds
    for interval in kept_intervals[1:]:
        if interval.start - merged[-1].end <= gap:
            merged[-1] = CutInstruction(
                start=merged[-1].start,
                end=max(merged[-1].end, interval.end),
            )
        else:
            merged.append(interval)

    total_duration = sum(c.end - c.start for c in merged)

    return CutList(
        video_id=video_id,
        segments_to_keep=merged,
        total_duration_kept=total_duration,
    )


class VideoEditAgent:
    def run(
        self,
        video_ingest: dict,
        transcript: dict,
        config: Settings,
    ) -> EditResult:
        cut_list = build_cut_list(video_ingest, transcript, config)
        video_path = Path(video_ingest["original_path"])
        output_dir = Path(config.outputs_dir) / cut_list.video_id
        output_path = output_dir / "edited.mp4"

        apply_cut_list(video_path, cut_list, output_path)

        return EditResult(
            video_id=cut_list.video_id,
            output_path=str(output_path),
            cut_list=cut_list,
        )

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        transcript_data = load_json(cache_dir / "cleaned.json")
        if not transcript_data:
            transcript_data = load_json(cache_dir / "transcript.json")
        if not metadata or not transcript_data:
            raise FileNotFoundError("Dados necessarios nao encontrados no cache")
        result = self.run(metadata, transcript_data, config)
        save_json(cache_dir / "edit_result.json", result.model_dump())
