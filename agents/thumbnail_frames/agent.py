import logging
from pathlib import Path

from config.settings import Settings
from schemas.state import PipelineState
from services.opencv_service import extract_candidate_frames
from utils.file_utils import load_json
from utils.hash_utils import get_cache_dir, get_video_hash_from_id

logger = logging.getLogger(__name__)


class ThumbnailFramesAgent:
    def run(
        self,
        video_id: str,
        original_video_path: str,
        config: Settings,
    ) -> list[Path]:
        cache_dir = get_cache_dir(get_video_hash_from_id(video_id))
        output_dir = cache_dir / "thumbnails"

        frames = extract_candidate_frames(
            video_path=Path(original_video_path),
            output_dir=output_dir,
            max_frames=5,
            min_spacing_percent=5.0,
        )
        return frames

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        if not metadata:
            raise FileNotFoundError(f"Metadados nao encontrados no cache para hash {video_hash}")
        self.run(metadata["video_id"], metadata["original_path"], config)
