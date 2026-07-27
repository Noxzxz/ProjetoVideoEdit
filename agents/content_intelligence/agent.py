import json
import logging
import time
from pathlib import Path

from config.settings import Settings, settings
from schemas.content import Chapter, ContentIntelligenceResult, ShortCandidate
from schemas.state import PipelineState
from services.llm_provider import generate
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

    def _load_shorts_prompt(self) -> str:
        prompt_path = Path(settings.prompts_dir) / "shorts_prompt.md"
        if not prompt_path.exists():
            raise ContentGenerationError(f"Prompt de shorts nao encontrado: {prompt_path}")
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

    def _format_transcript_range(
        self, transcript_data: dict, range_start: float, range_end: float
    ) -> str:
        segments = transcript_data.get("segments", [])
        lines = []
        for seg in segments:
            seg_start = seg.get("start", 0)
            seg_end = seg.get("end", 0)
            if seg_end < range_start or seg_start > range_end:
                continue
            text = seg.get("text", "").strip()
            lines.append(f"[{seg_start:.2f}s - {seg_end:.2f}s] {text}")
        return "\n".join(lines)

    def _extract_seo_data(self, response: dict, video_id: str) -> dict:
        return {
            "seo": response.get("seo", {}),
            "thumbnail": response.get("thumbnail", []),
            "summary": response.get("summary", {}),
        }

    def run(
        self,
        transcript: dict,
        video_duration_seconds: float,
        config: Settings,
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
        except (json.JSONDecodeError, TypeError) as exc:
            raise ContentGenerationError(f"Resposta invalida do LLM: {exc}") from exc

        base = self._extract_seo_data(data, transcript.get("video_id", ""))

        chapters_data = base["seo"].get("chapters", [])
        chapters = [Chapter(**c) for c in chapters_data]

        all_shorts: list[ShortCandidate] = []
        shorts_prompt = self._load_shorts_prompt()
        target_count = config.shorts_target_count

        for idx, chapter in enumerate(chapters):
            chap_start = chapter.timestamp_seconds
            chap_end = (
                chapters[idx + 1].timestamp_seconds
                if idx + 1 < len(chapters)
                else video_duration_seconds
            )

            chap_transcript = self._format_transcript_range(
                transcript, chap_start, chap_end
            )
            if not chap_transcript.strip():
                continue

            chap_prompt = shorts_prompt.replace(
                "{target_count}", str(max(1, target_count // len(chapters)))
            )
            chap_user = (
                f"Trecho do video: {chap_start:.1f}s ate {chap_end:.1f}s\n"
                f"Titulo do capitulo: {chapter.title}\n\n"
                f"Transcricao do trecho:\n{chap_transcript}"
            )

            try:
                if idx > 0:
                    time.sleep(3)
                chap_response = generate(
                    system_prompt=chap_prompt,
                    user_prompt=chap_user,
                    json_mode=True,
                )
                chap_data = json.loads(chap_response)
                for sc in chap_data.get("shorts", []):
                    sc["start"] = max(sc.get("start", chap_start), chap_start)
                    sc["end"] = min(sc.get("end", chap_end), chap_end)
                    sc.setdefault("hook_strength", 0.5)
                    all_shorts.append(ShortCandidate(**sc))
            except Exception as exc:
                logger.warning(f"Falha ao gerar shorts para capitulo '{chapter.title}': {exc}")

        all_shorts.sort(key=lambda s: s.score * 0.6 + s.hook_strength * 0.4, reverse=True)

        result_data = {
            "video_id": transcript.get("video_id", ""),
            "seo": base["seo"],
            "shorts": [s.model_dump() for s in all_shorts[:target_count]],
            "thumbnail": base["thumbnail"],
            "summary": base["summary"],
        }

        return ContentIntelligenceResult(**result_data)

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        metadata = load_json(cache_dir / "metadata.json")
        cleaned = load_json(cache_dir / "cleaned.json")
        if not metadata or not cleaned:
            raise FileNotFoundError("Dados necessarios nao encontrados no cache")
        video_duration = metadata["metadata"]["duration_seconds"]
        result = self.run(cleaned, video_duration, config)
        save_json(cache_dir / "content.json", result.model_dump())
