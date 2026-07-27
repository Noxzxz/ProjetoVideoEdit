import json
import logging
import re
from pathlib import Path

from schemas.transcript import TranscriptRaw, TranscriptSegment

logger = logging.getLogger(__name__)

SRT_LINE_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3}) --> (\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _parse_timestamp(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt(path: Path, video_id: str) -> TranscriptRaw:
    text = path.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n")
    segments: list[TranscriptSegment] = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        match = SRT_LINE_RE.search(lines[1] if len(lines) > 1 else "")
        if not match:
            continue

        start = _parse_timestamp(*match.groups()[:4])
        end = _parse_timestamp(*match.groups()[4:])
        content = "\n".join(lines[2:]) if len(lines) > 2 else ""
        content = content.strip().replace("\n", " ")

        segments.append(
            TranscriptSegment(
                id=len(segments) + 1,
                start=start,
                end=end,
                text=content,
                confidence=1.0,
            )
        )

    if not segments:
        raise ValueError(f"Nenhum segmento SRT encontrado em {path}")

    duration = max(s.end for s in segments)
    logger.info(f"SRT importado: {len(segments)} segmentos, duracao {duration:.1f}s")
    return TranscriptRaw(video_id=video_id, segments=segments, duration_seconds=duration)


def parse_vtt(path: Path, video_id: str) -> TranscriptRaw:
    text = path.read_text(encoding="utf-8")
    # Remove WEBVTT header and metadata lines
    lines = text.split("\n")
    start_idx = 0
    for i, line in enumerate(lines):
        if line.strip() == "" and i > 0:
            start_idx = i + 1
            break
        if line.strip().startswith("NOTE"):
            start_idx = i + 1
            break
    body = "\n".join(lines[start_idx:])
    return parse_srt_from_vtt_body(body, video_id)


def parse_srt_from_vtt_body(body: str, video_id: str) -> TranscriptRaw:
    blocks = body.strip().split("\n\n")
    segments: list[TranscriptSegment] = []

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue
        match = SRT_LINE_RE.search(lines[0] if len(lines) > 0 else "")
        if not match:
            continue

        start = _parse_timestamp(*match.groups()[:4])
        end = _parse_timestamp(*match.groups()[4:])
        content = "\n".join(lines[1:]) if len(lines) > 1 else ""
        content = content.strip().replace("\n", " ")

        segments.append(
            TranscriptSegment(
                id=len(segments) + 1,
                start=start,
                end=end,
                text=content,
                confidence=1.0,
            )
        )

    if not segments:
        raise ValueError("Nenhum segmento VTT encontrado")

    duration = max(s.end for s in segments)
    logger.info(f"VTT importado: {len(segments)} segmentos, duracao {duration:.1f}s")
    return TranscriptRaw(video_id=video_id, segments=segments, duration_seconds=duration)


def parse_json(path: Path, video_id: str) -> TranscriptRaw:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "segments" not in data:
        raise ValueError("JSON de transcricao deve conter campo 'segments'")
    return TranscriptRaw(video_id=video_id, **data)


def import_transcript(path: Path, video_id: str) -> TranscriptRaw:
    ext = path.suffix.lower()
    if ext == ".srt":
        return parse_srt(path, video_id)
    if ext == ".vtt":
        return parse_vtt(path, video_id)
    if ext == ".json":
        return parse_json(path, video_id)
    raise ValueError(f"Formato nao suportado: {ext}. Use .srt, .vtt ou .json")
