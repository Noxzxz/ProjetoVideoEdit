"""Analise de energia de audio (RMS) para apoio a candidatos a short (D21)."""

import logging
import wave
from pathlib import Path

import numpy as np

from utils.file_utils import load_json, save_json

logger = logging.getLogger(__name__)


def find_energy_peaks(
    audio_path: str | Path,
    window_seconds: float = 30.0,
    top_n: int = 8,
    factor_above_mean: float = 1.8,
) -> list[tuple[float, float]]:
    """Encontra janelas de alta energia RMS no audio (deterministico, sem LLM).

    Args:
        audio_path: Caminho do WAV (pcm_s16le).
        window_seconds: Tamanho da janela de analise.
        top_n: Maximo de picos retornados.
        factor_above_mean: Janela precisa ter RMS acima de (media * fator).

    Returns:
        Lista de (start, end) em segundos, ordenada por energia decrescente.
        Vazia se o audio nao puder ser lido ou nao tiver picos.
    """
    path = Path(audio_path)
    if not path.exists():
        logger.warning(f"Audio nao encontrado para analise de picos: {path}")
        return []

    try:
        with wave.open(str(path), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames = wf.getnframes()

            if sampwidth != 2:
                logger.warning(
                    f"Sampwidth {sampwidth} nao suportado (esperado 16-bit). "
                    "Pulando picos de energia."
                )
                return []

            window_frames = max(1, int(window_seconds * framerate))
            peaks: list[tuple[float, float, float]] = []
            frames_read = 0
            total_rms = 0.0
            n_windows = 0

            while True:
                raw = wf.readframes(window_frames)
                if not raw:
                    break

                samples = np.frombuffer(raw, dtype=np.int16)
                if n_channels > 1:
                    total_len = len(samples) // n_channels * n_channels
                    mono = samples[:total_len].reshape(-1, n_channels)[:, 0].astype(np.float64)
                else:
                    mono = samples.astype(np.float64)
                rms = float(np.sqrt(np.mean(mono ** 2)))

                win_start = frames_read / framerate
                win_end = min(
                    (frames_read + window_frames) / framerate, n_frames / framerate
                )
                peaks.append((rms, win_start, win_end))
                total_rms += rms
                n_windows += 1
                frames_read += window_frames
    except Exception as exc:
        logger.warning(f"Falha na analise de energia de {path}: {exc}")
        return []

    if not peaks:
        return []

    avg_rms = total_rms / n_windows
    if avg_rms <= 0:
        return []

    threshold = avg_rms * factor_above_mean
    selected = [p for p in peaks if p[0] >= threshold]
    selected.sort(key=lambda p: p[0], reverse=True)
    return [(p[1], p[2]) for p in selected[:top_n]]


def get_energy_peaks_cached(
    audio_path: str | Path,
    cache_dir: Path | None,
    window_seconds: float = 30.0,
    top_n: int = 8,
    factor_above_mean: float = 1.8,
) -> list[tuple[float, float]]:
    """Picos RMS cacheados por tamanho+mtime do WAV (B14), evitando reler o arquivo."""
    audio = Path(audio_path)
    if cache_dir is None or not audio.exists():
        return find_energy_peaks(
            audio, window_seconds=window_seconds, top_n=top_n,
            factor_above_mean=factor_above_mean,
        )

    cache_file = Path(cache_dir) / "audio_peaks.json"
    stat = audio.stat()
    cached = load_json(cache_file)
    if (
        cached
        and cached.get("size") == stat.st_size
        and cached.get("mtime_ns") == stat.st_mtime_ns
    ):
        return [tuple(p) for p in cached.get("peaks", [])]

    peaks = find_energy_peaks(
        audio, window_seconds=window_seconds, top_n=top_n,
        factor_above_mean=factor_above_mean,
    )
    save_json(
        cache_file,
        {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "peaks": peaks},
    )
    return peaks
