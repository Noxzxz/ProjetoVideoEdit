import json
import logging
from pathlib import Path

from config.settings import Settings, settings
from schemas.content import ContentIntelligenceResult
from schemas.state import PipelineState
from services.ollama_service import generate
from shared.exceptions import ContentGenerationError
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


class ContentIntelligenceAgent:
    def _load_prompt(self) -> str:
        prompt_path = Path(settings.prompts_dir) / "content_intelligence.md"
        if not prompt_path.exists():
            raise ContentGenerationError(f"Prompt nao encontrado: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    def _format_transcript(self, transcript_data: dict, max_segments: int = 400) -> str:
        segments = transcript_data.get("segments", [])
        lines = []
        for seg in segments[:max_segments]:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "").strip()
            lines.append(f"[{start:.2f}s - {end:.2f}s] {text}")
        return "\n".join(lines)

    def run(
        self,
        transcript: dict,
        video_duration_seconds: float,
    ) -> ContentIntelligenceResult:
        prompt = self._load_prompt()
        formatted = self._format_transcript(transcript)

        user_prompt = (
            f"Duracao do video: {video_duration_seconds:.1f}s\n\n"
            f"Transcricao (com timestamps):\n{formatted}"
        )

        try:
            response = generate(
                system_prompt=prompt,
                user_prompt=user_prompt,
                json_mode=True,
            )
        except Exception as exc:
            raise ContentGenerationError(f"Falha ao gerar conteudo: {exc}") from exc

        try:
            data = json.loads(response)
            result = ContentIntelligenceResult(
                video_id=transcript.get("video_id", ""),
                **data,
            )
        except (json.JSONDecodeError, TypeError) as exc:
            raise ContentGenerationError(f"Resposta invalida do LLM: {exc}") from exc

        return result

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        cleaned = load_json(cache_dir / "cleaned.json")
        if not metadata or not cleaned:
            raise FileNotFoundError("Dados necessarios nao encontrados no cache")
        video_duration = metadata["metadata"]["duration_seconds"]
        result = self.run(cleaned, video_duration)
        save_json(cache_dir / "content.json", result.model_dump())
