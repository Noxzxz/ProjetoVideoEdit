import logging
from pathlib import Path

from config.settings import Settings
from schemas.content import ContentIntelligenceResult
from services.ffmpeg_service import extract_segment
from utils.file_utils import load_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


class ShortsExtractorAgent:
    def run(
        self,
        video_path: Path,
        content: ContentIntelligenceResult,
        output_dir: Path,
        config: Settings,
    ) -> list[Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []

        for i, short in enumerate(content.shorts):
            short_path = output_dir / f"short_{i:03d}.mp4"
            extract_segment(
                video_path=video_path,
                start_seconds=short.start,
                end_seconds=short.end,
                output_path=short_path,
                config=config,
            )
            paths.append(short_path)
            logger.info(
                f"Short {i + 1}/{len(content.shorts)} extraido: "
                f"{short.start:.1f}s - {short.end:.1f}s"
            )

        return paths

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        cache_dir = get_cache_dir(video_hash)
        content_data = load_json(cache_dir / "content.json")
        if not content_data:
            raise FileNotFoundError(f"Conteudo nao encontrado no cache para hash {video_hash}")
        content = ContentIntelligenceResult(**content_data)
        output_dir = cache_dir / "shorts"
        self.run(video_path, content, output_dir, config)
