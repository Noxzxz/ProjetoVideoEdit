import logging
from pathlib import Path

from config.settings import Settings
from schemas.state import PipelineState
from schemas.transcript import TranscriptRaw
from services.whisper_service import transcribe
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir, get_video_hash_from_id

logger = logging.getLogger(__name__)


class SpeechRecognitionAgent:
    def run(self, video_id: str, audio_path: str) -> TranscriptRaw:
        cache_dir = get_cache_dir(get_video_hash_from_id(video_id))
        cached = load_json(cache_dir / "transcript.json")
        if cached:
            logger.info("Transcricao carregada do cache")
            return TranscriptRaw(**cached)

        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio nao encontrado: {audio_path}")

        transcript = transcribe(Path(audio_path), video_id)
        save_json(cache_dir / "transcript.json", transcript.model_dump())
        logger.info(f"Transcricao concluida para {video_id}")
        return transcript

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        if not metadata:
            raise FileNotFoundError(f"Metadados nao encontrados no cache para hash {video_hash}")
        self.run(metadata["video_id"], metadata["audio_path"])
