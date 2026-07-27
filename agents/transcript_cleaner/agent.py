import logging
import re
import time
from pathlib import Path

from config.settings import Settings, settings
from schemas.state import PipelineState
from schemas.transcript import TranscriptCleaned, TranscriptRaw, TranscriptSegment
from services.llm_provider import generate
from shared.exceptions import CleaningError
from utils.file_utils import load_json, save_json
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
    def run(self, transcript: TranscriptRaw) -> TranscriptCleaned:
        """Limpa transcrição: regex (listas fechadas) + LLM em lote (25 segmentos/chamada)."""

        # 1. Regex cleaning
        cleaned_texts = [apply_regex_cleaning(s.text) for s in transcript.segments]

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
                time.sleep(3)  # Pausa entre lotes para evitar rate limit

            # Formatar para LLM (inclui timestamps para contexto)
            prompt_lines = []
            for seg in batch:
                timestamp_part = f"[{seg.start:.2f}s - {seg.end:.2f}s]"
                text_part = seg.text.replace("\n", " ")
                prompt_lines.append(f"{timestamp_part} {text_part}")
            prompt = "\n".join(prompt_lines)
            prompt += """

Limpeza adicional:
- Mantenha apenas o que está no original
- Corrija pontuação, espaços e capitalização
- Não invente conteúdo

Responda APENAS com o texto corrigido, sem anotações."""

            try:
                llm_response = generate(
                    system_prompt=(
                        "Você é um editor de texto especializado em transcrição em português."
                    ),
                    user_prompt=prompt,
                    temperature=settings.ollama_temperature,
                    json_mode=False,
                )
                # Valida anti-alucinação (variação relativa entre 50% e 200%)
                original_length = sum(len(s.text) for s in batch)
                llm_length = len(llm_response)
                if not (0.5 * original_length <= llm_length <= 2.0 * original_length):
                    raise CleaningError(
                        f"LLM gerou tamanho inesperado: {llm_length} (original: {original_length})"
                    )

                for seg in batch:
                    cleaned_segments_after_llm.append(
                        TranscriptSegment(
                            id=seg.id,
                            start=seg.start,
                            end=seg.end,
                            text=seg.text,
                            confidence=seg.confidence,
                        )
                    )
            except Exception as e:
                logger.error(f"Falha no LLM para batch {batch}: {e}")
                # Se LLM falhar, retorna o texto com regex apenas
                start_idx = len(cleaned_segments_after_llm)
                for i, seg in enumerate(batch):
                    original_idx = start_idx + i
                    cleaned_text = (
                        cleaned_texts[original_idx]
                        if original_idx < len(cleaned_texts)
                        else seg.text
                    )
                    cleaned_segments_after_llm.append(
                        TranscriptSegment(
                            id=seg.id,
                            start=seg.start,
                            end=seg.end,
                            text=cleaned_text,
                            confidence=seg.confidence,
                        )
                    )

        return TranscriptCleaned(
            video_id=transcript.video_id,
            segments=cleaned_segments_after_llm,
            full_text_cleaned=" ".join(s.text.strip() for s in cleaned_segments_after_llm),
        )

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        cache_dir = get_cache_dir(video_hash)
        transcript_data = load_json(cache_dir / "transcript.json")
        if not transcript_data:
            raise FileNotFoundError(f"Transcricao nao encontrada no cache para hash {video_hash}")
        transcript = TranscriptRaw(**transcript_data)
        result = self.run(transcript)
        save_json(cache_dir / "cleaned.json", result.model_dump())
