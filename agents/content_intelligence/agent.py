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
from utils.shorts_anchoring import anchor_short_candidate, load_transcript_segments

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

    def _split_into_chunks(
        self, transcript_data: dict, chunk_duration_minutes: int = 25
    ) -> list[tuple[float, float, str]]:
        segments = transcript_data.get("segments", [])
        if not segments:
            return []

        duration_seconds = transcript_data.get("duration_seconds", 0)
        if duration_seconds == 0:
            max_end = max(seg.get("end", 0) for seg in segments)
            duration_seconds = max_end

        chunk_duration_seconds = chunk_duration_minutes * 60
        chunks: list[tuple[float, float, str]] = []

        for start_offset in range(0, int(duration_seconds), chunk_duration_seconds):
            end_offset = min(start_offset + chunk_duration_seconds, duration_seconds)
            chunk_text = self._format_transcript_range(
                transcript_data, start_offset, end_offset
            )
            if chunk_text.strip():
                chunks.append((start_offset, end_offset, chunk_text))

        return chunks

    def _extract_seo_data(self, response: dict, video_id: str) -> dict:
        return {
            "seo": response.get("seo", {}),
            "thumbnail_suggestions": response.get("thumbnail_suggestions", []),
            "summary": response.get("summary", {}),
        }

    def _consolidate(
        self,
        video_duration_seconds: float,
        chapter_candidates: list[Chapter],
        thumbnail_ideas: list[str],
        key_point_candidates: list[str],
    ) -> dict:
        """Chamada final de consolidacao (map-reduce): decide capitulos finais e SEO global."""
        if not chapter_candidates:
            return {}

        prompt_path = Path(settings.prompts_dir) / "content_consolidation.md"
        if not prompt_path.exists():
            raise ContentGenerationError(f"Prompt de consolidacao nao encontrado: {prompt_path}")
        prompt = prompt_path.read_text(encoding="utf-8")

        candidates = {
            "video_duration_seconds": video_duration_seconds,
            "chapter_candidates": [c.model_dump() for c in chapter_candidates],
            "thumbnail_ideas": thumbnail_ideas[:10],
            "key_points_candidates": key_point_candidates[:20],
        }
        user_prompt = json.dumps(candidates, ensure_ascii=False, indent=2)

        try:
            time.sleep(settings.llm_call_delay_seconds)
            response = generate(system_prompt=prompt, user_prompt=user_prompt, json_mode=True)
            data = json.loads(response)
            return {
                "seo": data.get("seo", {}),
                "summary": data.get("summary", {}),
            }
        except Exception as exc:
            logger.warning(f"Falha na consolidacao final: {exc}")
            return {}

    def _check_standalone(
        self, short: ShortCandidate, transcript: dict
    ) -> tuple[float, str]:
        """Critico de autocontencao (D19): verifica se o trecho cortado e compreensivel sozinho."""
        prompt_path = Path(settings.prompts_dir) / "standalone_check_prompt.md"
        if not prompt_path.exists():
            logger.warning(f"Prompt de autocontencao nao encontrado: {prompt_path}")
            return 0.5, ""

        prompt = prompt_path.read_text(encoding="utf-8")
        trecho_text = self._format_transcript_range(transcript, short.start, short.end)
        user_prompt = (
            f"Trecho do short:\n{trecho_text}\n\n"
            f"Gancho: {short.gancho}\nPayoff: {short.payoff}"
        )

        try:
            time.sleep(settings.llm_call_delay_seconds)
            response = generate(system_prompt=prompt, user_prompt=user_prompt, json_mode=True)
            data = json.loads(response)
            score = float(data.get("standalone_score", 0.5))
            notes = str(data.get("standalone_notes", ""))
            return max(0.0, min(1.0, score)), notes
        except Exception as exc:
            logger.warning(f"Falha na verificacao de autocontencao: {exc}")
            return 0.5, ""

    def run(
        self,
        transcript: dict,
        video_duration_seconds: float,
        config: Settings,
        video_hash: str | None = None,
    ) -> ContentIntelligenceResult:
        prompt = self._load_prompt()
        chunks = self._split_into_chunks(transcript, chunk_duration_minutes=25)

        if not chunks:
            formatted = self._format_transcript(transcript)
            chunks = [(0, video_duration_seconds, formatted)]

        all_chapters: list[Chapter] = []
        all_thumbnails: list[str] = []
        all_summaries: list[str] = []
        per_chunk_seo: list[dict] = []

        for idx, (chunk_start, chunk_end, chunk_text) in enumerate(chunks):
            user_prompt = (
                f"Duracao do video: {video_duration_seconds:.1f}s\n"
                f"Trecho: {chunk_start:.1f}s ate {chunk_end:.1f}s\n\n"
                f"Transcricao (com timestamps):\n{chunk_text}"
            )

            try:
                if idx > 0:
                    time.sleep(settings.llm_call_delay_seconds)
                response = generate(
                    system_prompt=prompt,
                    user_prompt=user_prompt,
                    json_mode=True,
                )
                data = json.loads(response)
                base = self._extract_seo_data(data, transcript.get("video_id", ""))

                chapters_data = base["seo"].get("chapters", [])
                for ch in chapters_data:
                    ch["timestamp_seconds"] += chunk_start
                    all_chapters.append(Chapter(**ch))

                per_chunk_seo.append(base["seo"])
                all_thumbnails.extend(base.get("thumbnail_suggestions", []))
                all_summaries.extend(base.get("summary", {}).get("key_points", []))

            except Exception as exc:
                logger.warning(f"Falha ao processar chunk {idx}: {exc}")

        all_chapters.sort(key=lambda c: c.timestamp_seconds)

        consolidated = self._consolidate(
            video_duration_seconds, all_chapters, all_thumbnails, all_summaries
        )

        seo_data = consolidated.get("seo", {})
        chapters_data = seo_data.get("chapters")
        if chapters_data:
            try:
                final_chapters = [Chapter(**c) for c in chapters_data]
                final_chapters.sort(key=lambda c: c.timestamp_seconds)
            except Exception as exc:
                logger.warning(f"Capitulos consolidados invalidos: {exc}")
                final_chapters = all_chapters
            title = seo_data.get("title", "")
            description = seo_data.get("description", "")
            hashtags = seo_data.get("hashtags", [])
        else:
            final_chapters = all_chapters
            title = ""
            description = ""
            hashtags = []
            for s in per_chunk_seo:
                title = title or s.get("title", "")
                description = description or s.get("description", "")
                hashtags = hashtags or s.get("hashtags", [])

        summary_data = consolidated.get("summary", {})
        overview = summary_data.get("overview", "")
        key_points = summary_data.get("key_points") or all_summaries
        next_steps = summary_data.get("next_steps") or []

        all_shorts: list[ShortCandidate] = []
        shorts_prompt = self._load_shorts_prompt()
        target_count = config.shorts_target_count

        transcript_segments = []
        if video_hash:
            transcript_segments = load_transcript_segments(video_hash)

        for idx, chapter in enumerate(final_chapters):
            chap_start = chapter.timestamp_seconds
            chap_end = (
                final_chapters[idx + 1].timestamp_seconds
                if idx + 1 < len(final_chapters)
                else video_duration_seconds
            )

            chap_transcript = self._format_transcript_range(
                transcript, chap_start, chap_end
            )
            if not chap_transcript.strip():
                continue

            chap_prompt = shorts_prompt.replace(
                "{target_count}", str(max(1, target_count // len(final_chapters)))
            )
            chap_user = (
                f"Trecho do video: {chap_start:.1f}s ate {chap_end:.1f}s\n"
                f"Titulo do capitulo: {chapter.title}\n\n"
                f"Transcricao do trecho:\n{chap_transcript}"
            )

            try:
                if idx > 0:
                    time.sleep(settings.llm_call_delay_seconds)
                chap_response = generate(
                    system_prompt=chap_prompt,
                    user_prompt=chap_user,
                    json_mode=True,
                )
                chap_data = json.loads(chap_response)

                for cand in chap_data.get("shorts", []):
                    anchored = anchor_short_candidate(
                        cand,
                        transcript_segments,
                        video_duration_seconds,
                        min_duration=config.shorts_min_duration_seconds,
                        max_duration=config.shorts_max_duration_seconds,
                    )
                    if anchored:
                        all_shorts.append(ShortCandidate(
                            start=anchored["start"],
                            end=anchored["end"],
                            reason=anchored.get("justificativa", ""),
                            score=0.7,
                            hook_strength=0.6,
                            gancho=anchored.get("gancho", ""),
                            payoff=anchored.get("payoff", ""),
                            emocao=anchored.get("emocao", ""),
                            standalone_score=0.5,
                            standalone_notes="",
                        ))
            except Exception as exc:
                logger.warning(f"Falha ao gerar shorts para capitulo '{chapter.title}': {exc}")

        # D19: critico de autocontencao sobre os candidatos finais (apos a ancoragem)
        for short in all_shorts:
            short.standalone_score, short.standalone_notes = self._check_standalone(
                short, transcript
            )

        all_shorts = [
            s for s in all_shorts if s.standalone_score >= config.shorts_min_standalone_score
        ]
        all_shorts.sort(
            key=lambda s: s.score * 0.5 + s.hook_strength * 0.3 + s.standalone_score * 0.2,
            reverse=True,
        )

        result_data = {
            "video_id": transcript.get("video_id", ""),
            "seo": {
                "title": title,
                "description": description,
                "hashtags": hashtags,
                "chapters": [c.model_dump() for c in final_chapters],
            },
            "shorts": [s.model_dump() for s in all_shorts[:target_count]],
            "thumbnail_suggestions": all_thumbnails[:5],
            "summary": {
                "overview": overview,
                "key_points": key_points[:10],
                "next_steps": next_steps,
            },
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
        result = self.run(cleaned, video_duration, config, video_hash=video_hash)
        save_json(cache_dir / "content.json", result.model_dump())
