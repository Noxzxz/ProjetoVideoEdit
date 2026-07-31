import hashlib
import os
from pathlib import Path

from config.settings import settings

_SAMPLE_SIZE = 1024 * 1024  # 1 MB


def compute_video_hash(video_path: Path) -> str:
    """Hash por amostra (B12): tamanho + mtime + 1o/ultimo MB.

    Evita ler arquivos multi-GB inteiros a cada execucao/resume. Colisoes exigem
    mesmo tamanho, mesmo mtime e mesmos 2 MB de borda -- caso negligenciavel.
    """
    stat = video_path.stat()
    size = stat.st_size
    mtime_ns = stat.st_mtime_ns

    h = hashlib.sha256()
    h.update(str(size).encode())
    h.update(str(mtime_ns).encode())
    with open(video_path, "rb") as f:
        h.update(f.read(_SAMPLE_SIZE))
        if size > 2 * _SAMPLE_SIZE:
            f.seek(-_SAMPLE_SIZE, os.SEEK_END)
            h.update(f.read(_SAMPLE_SIZE))
    return h.hexdigest()[:16]


def get_cache_dir(video_hash: str) -> Path:
    return Path(settings.cache_dir) / video_hash


def get_video_hash_from_id(video_id: str) -> str:
    return video_id.rsplit("-", 1)[-1]
