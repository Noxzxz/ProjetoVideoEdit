import logging
from pathlib import Path

from config.settings import Settings
from schemas.video import VideoIngestResult
from services.ffmpeg_service import extract_audio, get_video_metadata
from shared.exceptions import AudioExtractionError, VideoNotFoundError
from utils.file_utils import ensure_dir, load_json, save_json
from utils.hash_utils import compute_video_hash, get_cache_dir
from utils.slugify import generate_video_id

logger = logging.getLogger(__name__)


class VideoProcessingAgent:
    def run(
        self,
        video_path: str,
        video_hash: str | None = None,
        config: Settings | None = None,
    ) -> VideoIngestResult:
        cfg = config or Settings()
        path = Path(video_path)
        if not path.exists():
            raise VideoNotFoundError(f"Arquivo nao encontrado: {video_path}")

        if video_hash is None:
            video_hash = compute_video_hash(path)
        video_id = generate_video_id(path.name, video_hash)
        cache_dir = get_cache_dir(video_hash)

        # Verifica cache
        cached = load_json(cache_dir / "metadata.json")
        if cached:
            logger.info("Metadados carregados do cache")
            return VideoIngestResult(**cached)

        metadata = get_video_metadata(path)
        if not metadata.has_audio_track:
            raise AudioExtractionError("Video nao possui trilha de audio")

        audio_path = Path(cfg.data_dir) / "intermediate" / video_id / "audio.wav"
        ensure_dir(audio_path.parent)
        extract_audio(path, audio_path)

        result = VideoIngestResult(
            video_id=video_id,
            original_path=str(path),
            audio_path=str(audio_path),
            metadata=metadata,
        )

        save_json(cache_dir / "metadata.json", result.model_dump())
        logger.info(f"Video processado: {video_id}")
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        self.run(str(video_path), video_hash, config)
