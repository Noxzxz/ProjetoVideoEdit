"""Funcoes utilitarias para ancoragem deterministica de candidatos a short."""

import logging
from difflib import SequenceMatcher

from utils.file_utils import load_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


def _text_similarity(text1: str, text2: str) -> float:
    """Calcula similaridade entre dois textos (0.0 a 1.0)."""
    t1 = text1.lower().strip()
    t2 = text2.lower().strip()
    if not t1 or not t2:
        return 0.0
    return SequenceMatcher(None, t1, t2).ratio()


def anchor_text_to_segments(
    text: str,
    transcript_segments: list[dict],
    min_similarity: float = 0.6,
    max_distance_chars: int = 50,
) -> dict | None:
    """Busca um texto literal contra segmentos da transcrição e retorna o segmento encontrado.

    Args:
        text: Texto a buscar (gancho ou payoff).
        transcript_segments: Lista de segmentos da transcrição limpa.
        min_similarity: Similaridade minima para considerar match (0.0-1.0).
        max_distance_chars: Distancia maxima em caracteres para buscar contexto.

    Returns:
        Dicionario do segmento encontrado ou None se nao encontrar.
    """
    if not text or not transcript_segments:
        return None

    best_match = None
    best_score = 0.0

    for seg in transcript_segments:
        seg_text = seg.get("text", "").strip()
        if not seg_text:
            continue

        # Busca direta (substring)
        if text.lower() in seg_text.lower():
            return seg

        # Busca por similaridade
        score = _text_similarity(text, seg_text)
        if score > best_score and score >= min_similarity:
            best_score = score
            best_match = seg

    # Se nao encontrou match direto, tenta buscar no contexto vizinho
    if best_match is None and len(transcript_segments) > 1:
        for idx, seg in enumerate(transcript_segments):
            seg_text = seg.get("text", "").strip()
            # Contexto: segmento atual + proximo
            context = seg_text
            if idx + 1 < len(transcript_segments):
                context += " " + transcript_segments[idx + 1].get("text", "")

            score = _text_similarity(text, context)
            if score > best_score and score >= min_similarity:
                best_score = score
                best_match = seg

    if best_score >= min_similarity:
        logger.debug(f"Match encontrado: '{text[:50]}...' -> segmento {best_match.get('id', '?')} "
                     f"(similarity={best_score:.2f})")
        return best_match

    logger.debug(f"Match nao encontrado para: '{text[:50]}...' (best={best_score:.2f})")
    return None


def anchor_short_candidate(
    candidate: dict,
    transcript_segments: list[dict],
    video_duration_seconds: float,
    min_duration: float = 15.0,
    max_duration: float = 60.0,
) -> dict | None:
    """Ancora um candidato a short (com gancho/payoff) contra segmentos reais.

    Args:
        candidate: Dicionario com 'gancho' e 'payoff' (frases literais).
        transcript_segments: Segmentos da transcrição limpa.
        video_duration_seconds: Duracao total do video.
        min_duration: Duracao minima do short.
        max_duration: Duracao maxima do short.

    Returns:
        Dicionario com 'start', 'end', 'gancho', 'payoff' ou None se invalido.
    """
    gancho = candidate.get("gancho", "").strip()
    payoff = candidate.get("payoff", "").strip()

    if not gancho or not payoff:
        logger.debug("Candidato sem gancho ou payoff — descartado.")
        return None

    gancho_seg = anchor_text_to_segments(gancho, transcript_segments)
    payoff_seg = anchor_text_to_segments(payoff, transcript_segments)

    if not gancho_seg or not payoff_seg:
        logger.debug("Gancho ou payoff nao ancorados — descartado.")
        return None

    start = gancho_seg.get("start", 0)
    end = payoff_seg.get("end", 0)

    # Garante ordem
    if start > end:
        start, end = end, start

    # Verifica duracao
    duration = end - start
    if duration < min_duration:
        logger.debug(f"Short muito curto ({duration:.1f}s) — descartado.")
        return None
    if duration > max_duration:
        logger.debug(f"Short muito longo ({duration:.1f}s) — descartado.")
        return None

    # Verifica limites do video
    start = max(0.0, min(start, video_duration_seconds))
    end = max(0.0, min(end, video_duration_seconds))

    return {
        "start": start,
        "end": end,
        "gancho": gancho,
        "payoff": payoff,
        "emocao": candidate.get("emocao", ""),
        "justificativa": candidate.get("justificativa", ""),
    }


def load_transcript_segments(video_hash: str) -> list[dict]:
    """Carrega segmentos da transcrição limpa do cache."""
    cache_dir = get_cache_dir(video_hash)
    cleaned = load_json(cache_dir / "cleaned.json")
    if not cleaned:
        logger.warning("Transcricao limpa nao encontrada no cache.")
        return []
    return cleaned.get("segments", [])
