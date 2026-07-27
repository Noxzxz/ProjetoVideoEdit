import logging
import subprocess
from fractions import Fraction
from pathlib import Path

from config.settings import Settings
from schemas.edit import CutList
from schemas.video import VideoMetadata
from shared.exceptions import AudioExtractionError, EditingError, VideoNotFoundError

logger = logging.getLogger(__name__)


def get_video_metadata(video_path: Path) -> VideoMetadata:
    if not video_path.exists():
        raise VideoNotFoundError(f"Arquivo não encontrado: {video_path}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioExtractionError(f"ffprobe falhou: {result.stderr}")

    import json

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    format_info = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(format_info.get("duration", 0))
    fps_str = video_stream.get("r_frame_rate", "30/1")
    fps = float(Fraction(fps_str)) if "/" in fps_str else float(fps_str)

    return VideoMetadata(
        duration_seconds=duration,
        fps=fps,
        width=video_stream.get("width", 0),
        height=video_stream.get("height", 0),
        codec=video_stream.get("codec_name", "unknown"),
        has_audio_track=audio_stream is not None,
    )


def extract_audio(video_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioExtractionError(f"FFmpeg falhou: {result.stderr}")
    logger.info(f"Audio extracted: {output_path}")
    return output_path


def get_video_duration(video_path: Path) -> float:
    return get_video_metadata(video_path).duration_seconds


def apply_cut_list(
    video_path: Path,
    cut_list: CutList,
    output_path: Path,
) -> Path:
    """Cut and concat via FFmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "tmp_cuts"
    temp_dir.mkdir(parents=True, exist_ok=True)

    segment_files: list[Path] = []
    try:
        for idx, cut in enumerate(cut_list.segments_to_keep):
            seg_path = temp_dir / f"temp_{idx:03d}.mp4"
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(cut.start),
                "-to",
                str(cut.end),
                "-i",
                str(video_path),
                "-c",
                "copy",
                str(seg_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # Fallback reencode
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(cut.start),
                    "-to",
                    str(cut.end),
                    "-i",
                    str(video_path),
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    str(seg_path),
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise EditingError(f"Cut failed: {result.stderr}")
            segment_files.append(seg_path)

        # Concatenate segments via FFmpeg demuxer
        list_file = temp_dir / "concat_list.txt"
        with open(list_file, "w") as f:
            for seg in segment_files:
                f.write(f"file '{seg.resolve()}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise EditingError(f"Concatenation failed: {result.stderr}")

        logger.info(f"Edited video: {output_path}")
        return output_path
    finally:
        # Cleanup
        for f in temp_dir.glob("*"):
            f.unlink(missing_ok=True)
        temp_dir.rmdir()


def extract_segment(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    output_path: Path,
    config: Settings,
) -> Path:
    """Extrai um trecho do video. Tenta -c copy primeiro."""
    duration = end_seconds - start_seconds
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_copy = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_seconds),
        "-t",
        str(duration),
        "-i",
        str(video_path),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path),
    ]
    result = subprocess.run(cmd_copy, capture_output=True, text=True)
    if result.returncode != 0:
        cmd_reenc = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_seconds),
            "-t",
            str(duration),
            "-i",
            str(video_path),
            "-c:v",
            config.video_codec,
            "-c:a",
            config.audio_codec,
            "-preset",
            config.video_preset,
            str(output_path),
        ]
        result = subprocess.run(cmd_reenc, capture_output=True, text=True)
        if result.returncode != 0:
            raise EditingError(f"Falha ao extrair segmento: {result.stderr}")
    return output_path
