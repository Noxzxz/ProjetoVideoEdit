import hashlib
from pathlib import Path

from config.settings import settings


def compute_video_hash(video_path: Path) -> str:
    h = hashlib.sha256()
    with open(video_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()[:16]


def get_cache_dir(video_hash: str) -> Path:
    return Path(settings.cache_dir) / video_hash


def get_video_hash_from_id(video_id: str) -> str:
    return video_id.rsplit("-", 1)[-1]
