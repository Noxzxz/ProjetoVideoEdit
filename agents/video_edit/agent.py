import logging
from pathlib import Path

from config.settings import Settings
from schemas.edit import CutInstruction, CutList, EditResult
from services.ffmpeg_service import apply_cut_list
from shared.exceptions import EditingError
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


def build_cut_list(
    video_ingest: dict,
    transcript: dict,
    config: Settings,
    marker_pairs: list[dict] | None = None,
) -> CutList:
    """Constroi lista de cortes baseada em segmentos VAD + marcadores."""
    segments = transcript.get("segments", [])
    if not segments:
        raise EditingError("Nenhum segmento de transcricao para construir lista de cortes")

    video_id = video_ingest.get("video_id", "unknown")

    kept_intervals = []
    pre_pad = config.silence_pre_padding_ms / 1000.0
    post_pad = config.silence_post_padding_ms / 1000.0

    for seg in segments:
        start = max(0, seg.get("start", 0) - pre_pad)
        end = seg.get("end", 0) + post_pad
        if end > start:
            kept_intervals.append(CutInstruction(start=start, end=end))

    if not kept_intervals:
        raise EditingError("Nenhum intervalo valido para manter apos analise")

    # Merge intervals within min_gap_seconds
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

    # Remove intervals overlapping with marker pairs
    if marker_pairs:
        marker_regions: list[tuple[float, float]] = []
        for mp in marker_pairs:
            ms = mp.get("start", 0)
            me = mp.get("end", 0)
            if me > ms:
                marker_regions.append((ms, me))

        filtered = []
        for interval in merged:
            trimmed_start = interval.start
            trimmed_end = interval.end
            for ms, me in marker_regions:
                if ms < trimmed_end and me > trimmed_start:
                    if ms > trimmed_start:
                        filtered.append(CutInstruction(start=trimmed_start, end=ms))
                    trimmed_start = max(trimmed_start, me)
            if trimmed_end > trimmed_start:
                filtered.append(CutInstruction(start=trimmed_start, end=trimmed_end))
        merged = filtered

    if not merged:
        raise EditingError("Nenhum intervalo valido apos aplicar marcadores de corte")

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
        marker_pairs: list[dict] | None = None,
    ) -> EditResult:
        cut_list = build_cut_list(video_ingest, transcript, config, marker_pairs)
        video_path = Path(video_ingest["original_path"])
        output_dir = Path(config.outputs_dir) / cut_list.video_id
        output_path = output_dir / "edited.mp4"

        apply_cut_list(video_path, cut_list, output_path)

        return EditResult(
            video_id=cut_list.video_id,
            output_path=str(output_path),
            cut_list=cut_list,
        )

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        transcript_data = load_json(cache_dir / "cleaned.json")
        if not transcript_data:
            transcript_data = load_json(cache_dir / "transcript.json")
        if not metadata or not transcript_data:
            raise FileNotFoundError("Dados necessarios nao encontrados no cache")
        marker_pairs = load_json(cache_dir / "markers.json")
        result = self.run(metadata, transcript_data, config, marker_pairs)
        save_json(cache_dir / "edit_result.json", result.model_dump())
