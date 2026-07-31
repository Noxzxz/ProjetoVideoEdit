import logging
import re
import time
from pathlib import Path

from config.settings import Settings, settings
from schemas.transcript import TranscriptCleaned, TranscriptRaw, TranscriptSegment
from services.llm_provider import generate
from shared.exceptions import CleaningError
from utils.file_utils import load_json, save_json
from utils.glossary_correction import apply_glossary_to_segments, load_glossary
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)

# Lista de preenchimentos vocais (fechada) para regex
FILLER_WORDS = [r"\b(hum|ah|ahn|ãhn|ehm)\b"]
PATTERN = re.compile("|".join(FILLER_WORDS))  # COMBACKS


def apply_regex_cleaning(text: str) -> str:
    """Aplica regex de lista fechada para remover preenchimentos vocais.
    SOMENTE usa letras do alfabeto português com \b para evitar remoção de palavras completas."""
    if not text:
        return text

    # Remove palavras que correspondem a FILLER_WORDS
    cleaned = PATTERN.sub("", text)

    # Verifica se houve alteração
    if cleaned == text:
        return text

    return cleaned


class TranscriptCleanerAgent:
    def run(
        self, transcript: TranscriptRaw, config: Settings | None = None
    ) -> TranscriptCleaned:
        """Limpa transcrição: glossário (D20) + regex (listas fechadas) + LLM em lote."""
        cfg = config or settings

        # 0. Correcao deterministica de vocabulario de sistema (D20) - entre
        #    SPEECH_RECOGNITION e TRANSCRIPT_CLEANING, antes de qualquer limpeza por LLM
        glossary = load_glossary(cfg.glossary_name, glossaries_dir=cfg.glossaries_dir)
        if glossary:
            transcript = TranscriptRaw(
                video_id=transcript.video_id,
                language=transcript.language,
                segments=apply_glossary_to_segments(transcript.segments, glossary),
            )

        # 1. Regex cleaning
        cleaned_by_id: dict[int, str] = {}
        for s in transcript.segments:
            cleaned_by_id[s.id] = apply_regex_cleaning(s.text)

        # 2. LLM cleaning (processamento em lote)
        batch_size = 15
        all_segments = [s for s in transcript.segments if s.text.strip()]  # Filtrar vazios
        batches = [
            all_segments[i : i + batch_size] for i in range(0, len(all_segments), batch_size)
        ]

        cleaned_segments_after_llm = []
        for idx, batch in enumerate(batches):
            if not batch:  # Batch vazio
                continue
            if idx > 0:
                time.sleep(cfg.llm_call_delay_seconds)  # Pausa entre lotes

            # Formatar para LLM (uma linha por segmento, com timestamp para contexto)
            prompt_lines = []
            for seg in batch:
                timestamp_part = f"[{seg.start:.2f}s - {seg.end:.2f}s]"
                text_part = seg.text.replace("\n", " ")
                prompt_lines.append(f"{timestamp_part} {text_part}")
            prompt = "\n".join(prompt_lines)
            prompt += """

Limpeza adicional:
- Mantenha apenas o que esta no original
- Corrija pontuacao, espacos e capitalizacao
- NAO invente conteudo
- Retorne UMA linha corrigida por segmento, na mesma ordem, sem timestamps."""

            try:
                llm_prompt_path = Path(cfg.prompts_dir) / "cleaning_llm.md"
                system_prompt = llm_prompt_path.read_text(encoding="utf-8")
            except Exception:
                system_prompt = (
                    "Voce e um editor de texto especializado em transcricao em portugues."
                )

            try:
                llm_response = generate(
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    temperature=cfg.ollama_temperature,
                    json_mode=False,
                    config=cfg,
                )
                original_length = sum(len(s.text) for s in batch)
                llm_length = len(llm_response)
                if not (0.5 * original_length <= llm_length <= 2.0 * original_length):
                    raise CleaningError(
                        f"LLM gerou tamanho inesperado: {llm_length} (original: {original_length})"
                    )

                llm_lines = [line.strip() for line in llm_response.splitlines() if line.strip()]
                if len(llm_lines) == len(batch):
                    for i, seg in enumerate(batch):
                        cleaned_segments_after_llm.append(
                            TranscriptSegment(
                                id=seg.id,
                                start=seg.start,
                                end=seg.end,
                                text=llm_lines[i],
                                confidence=seg.confidence,
                            )
                        )
                else:
                    for seg in batch:
                        cleaned_segments_after_llm.append(
                            TranscriptSegment(
                                id=seg.id,
                                start=seg.start,
                                end=seg.end,
                                text=cleaned_by_id.get(seg.id, seg.text),
                                confidence=seg.confidence,
                            )
                        )
            except Exception as e:
                logger.error(f"Falha no LLM para batch {idx}: {e}")
                for seg in batch:
                    cleaned_segments_after_llm.append(
                        TranscriptSegment(
                            id=seg.id,
                            start=seg.start,
                            end=seg.end,
                            text=cleaned_by_id.get(seg.id, seg.text),
                            confidence=seg.confidence,
                        )
                    )

        return TranscriptCleaned(
            video_id=transcript.video_id,
            segments=cleaned_segments_after_llm,
            full_text_cleaned=" ".join(s.text.strip() for s in cleaned_segments_after_llm),
        )

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        cache_dir = get_cache_dir(video_hash)
        transcript_data = load_json(cache_dir / "transcript.json")
        if not transcript_data:
            raise FileNotFoundError(f"Transcricao nao encontrada no cache para hash {video_hash}")
        transcript = TranscriptRaw(**transcript_data)
        result = self.run(transcript, config)
        save_json(cache_dir / "cleaned.json", result.model_dump())
