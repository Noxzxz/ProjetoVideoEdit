import logging
from pathlib import Path

from config.settings import Settings
from schemas.subtitle import SubtitleResult
from schemas.transcript import TranscriptCleaned, TranscriptSegment
from utils.file_utils import ensure_dir, load_json, save_json
from utils.hash_utils import get_cache_dir
from utils.time_utils import seconds_to_srt_timestamp, seconds_to_vtt_timestamp

logger = logging.getLogger(__name__)


def split_into_caption_chunks(
    segments: list[TranscriptSegment],
    max_words_per_line: int = 4,
) -> list[TranscriptSegment]:
    """Agrupa palavras em chunks de no maximo max_words_per_line."""
    chunks: list[TranscriptSegment] = []
    current_words: list[str] = []
    chunk_start = 0.0
    chunk_end = 0.0
    chunk_id = 0

    for seg in segments:
        words = seg.text.split()
        if not words:
            continue

        for word in words:
            current_words.append(word)
            chunk_end = seg.end

            if len(current_words) >= max_words_per_line:
                chunks.append(
                    TranscriptSegment(
                        id=chunk_id,
                        start=chunk_start,
                        end=chunk_end,
                        text=" ".join(current_words),
                        confidence=seg.confidence,
                    )
                )
                chunk_id += 1
                current_words = []
                chunk_start = chunk_end

    # Last chunk
    if current_words:
        chunks.append(
            TranscriptSegment(
                id=chunk_id,
                start=chunk_start,
                end=chunk_end,
                text=" ".join(current_words),
                confidence=seg.confidence if seg else 0.0,
            )
        )

    return chunks


def to_srt(chunks: list[TranscriptSegment]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, 1):
        start = seconds_to_srt_timestamp(chunk.start)
        end = seconds_to_srt_timestamp(chunk.end)
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines)


def to_vtt(chunks: list[TranscriptSegment]) -> str:
    lines = ["WEBVTT", ""]
    for chunk in chunks:
        start = seconds_to_vtt_timestamp(chunk.start)
        end = seconds_to_vtt_timestamp(chunk.end)
        lines.append(f"{start} --> {end}")
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines)


class SubtitleStylingAgent:
    def run(
        self,
        video_id: str,
        transcript: TranscriptCleaned,
        config: Settings,
    ) -> SubtitleResult:
        chunks = split_into_caption_chunks(transcript.segments, config.max_words_per_line)

        output_dir = Path(config.outputs_dir) / video_id
        ensure_dir(output_dir)

        srt_path = output_dir / "subtitles.srt"
        vtt_path = output_dir / "subtitles.vtt"

        srt_path.write_text(to_srt(chunks), encoding="utf-8")
        vtt_path.write_text(to_vtt(chunks), encoding="utf-8")

        logger.info(f"Legendas geradas em {output_dir}")
        return SubtitleResult(
            video_id=video_id,
            srt_path=str(srt_path),
            vtt_path=str(vtt_path),
        )

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        cleaned_data = load_json(cache_dir / "cleaned.json")
        if not metadata or not cleaned_data:
            raise FileNotFoundError("Dados necessarios nao encontrados no cache")
        video_id = metadata["video_id"]
        transcript = TranscriptCleaned(**cleaned_data)
        result = self.run(video_id, transcript, config)
        save_json(cache_dir / "subtitle_result.json", result.model_dump())
