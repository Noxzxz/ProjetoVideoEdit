"""Correcao deterministica de vocabulario de sistema via glossario (D20)."""

import logging
import re
import unicodedata
from pathlib import Path

from config.settings import settings

logger = logging.getLogger(__name__)

_SINGLE_WORD = re.compile(r"[A-Za-zÀ-ÿ]+")


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _levenshtein(a: str, b: str) -> int:
    """Distancia de Levenshtein entre duas strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def load_glossary(glossary_name: str) -> list[str]:
    """Carrega termos de `glossaries/<glossary_name>.md`. Vazio se ausente."""
    if not glossary_name:
        return []
    path = Path(settings.glossaries_dir) / f"{glossary_name}.md"
    if not path.exists():
        logger.warning(f"Glossario nao encontrado: {path}")
        return []

    terms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return terms


def build_initial_prompt_from_glossary(glossary_name: str) -> str:
    """Monta initial_prompt para o Whisper a partir do glossario."""
    terms = load_glossary(glossary_name)
    return ", ".join(terms) if terms else ""


def correct_segment_text(text: str, glossary: list[str], threshold: float = 0.75) -> str:
    """Corrige um texto aplicando o glossario (fuzzy-match por palavra).

    Multi-word terms sao substituidos por correspondencia literal
    (case-insensitive); termos de palavra unica por Levenshtein.
    """
    if not text or not glossary:
        return text

    stripped_terms: list[tuple[str, str]] = []
    for term in glossary:
        key = _strip_accents(term).strip().lower()
        if key:
            stripped_terms.append((term, key))
    if not stripped_terms:
        return text

    # 1) Multi-word literal replacement (case-insensitive, accent-sensitive)
    result = text
    for term, key in sorted(stripped_terms, key=lambda t: len(t[1]), reverse=True):
        if " " in key:
            pattern = re.compile(
                r"\b" + r"\s+".join(re.escape(w) for w in key.split()) + r"\b",
                re.IGNORECASE,
            )
            result = pattern.sub(term, result)

    # 2) Single-word fuzzy correction via Levenshtein
    single_terms = [(term, key) for term, key in stripped_terms if " " not in key]

    def _best_term(word_key: str) -> tuple[str, float] | None:
        best_term: str | None = None
        best_sim = 0.0
        for term, key in single_terms:
            if abs(len(key) - len(word_key)) > 3:
                continue
            max_len = max(len(key), len(word_key), 1)
            sim = 1 - _levenshtein(word_key, key) / max_len
            if sim > best_sim:
                best_sim = sim
                best_term = term
        if best_term is not None and best_sim >= threshold:
            return best_term, best_sim
        return None

    replacements: list[tuple[int, int, str]] = []
    for token in _SINGLE_WORD.finditer(result):
        word = token.group(0)
        word_key = _strip_accents(word).lower()
        if len(word_key) < 3:
            continue
        hit = _best_term(word_key)
        if hit:
            term, _sim = hit
            replacements.append((token.start(), token.end(), term))

    for start, end, term in sorted(replacements, reverse=True):
        result = result[:start] + term + result[end:]

    return result


def apply_glossary_to_segments(segments, glossary: list[str], threshold: float = 0.75):
    """Aplica o glossario a uma lista de segmentos, retornando novos segmentos."""
    if not glossary:
        return segments

    corrected = []
    for seg in segments:
        new_text = correct_segment_text(seg.text, glossary, threshold)
        if new_text != seg.text:
            logger.debug(f"Glossario: '{seg.text}' -> '{new_text}'")
        corrected.append(seg.model_copy(update={"text": new_text}))
    return corrected
