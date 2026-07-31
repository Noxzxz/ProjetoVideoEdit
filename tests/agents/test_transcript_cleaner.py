"""Tests for TranscriptCleanerAgent with Portuguese regex edge cases."""

from agents.transcript_cleaner.agent import TranscriptCleanerAgent, apply_regex_cleaning
from schemas.transcript import TranscriptRaw, TranscriptSegment


def test_regex_removes_filler_words():
    """Testa remoção de palavras de preenchimento da lista fechada."""
    tests = [
        ("hum", ""),
        ("ah", ""),
        ("ahn", ""),
        ("ãhn", ""),
        ("ehm", ""),
        ("hum, tudo bem", ", tudo bem"),
    ]
    for input_text, expected in tests:
        assert apply_regex_cleaning(input_text) == expected


def test_regex_does_not_remove_ambiguous_words():
    """Testa que palavras ambíguas (como 'é', 'tipo', 'né') NÃO são removidas."""
    tests = [
        "você é",
        "esse tipo de coisa",
        "você não é do tipo né",
    ]
    for input_text in tests:
        assert apply_regex_cleaning(input_text) == input_text


def test_transcript_cleaner_agent_run_returns_cleaned(monkeypatch):
    """Testa que o agente limpa a transcrição após aplicação do regex."""
    monkeypatch.setattr(
        "agents.transcript_cleaner.agent.generate", lambda **kwargs: "tudo bem"
    )
    agent = TranscriptCleanerAgent()
    raw = TranscriptRaw(
        video_id="test-abc123def456",
        language="pt",
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text="tudo bem", confidence=0.9)
        ],
    )
    cleaned = agent.run(raw)
    assert len(cleaned.segments) == 1
    assert "tudo bem" in cleaned.full_text_cleaned


def test_batch_size_respects_25_segments(monkeypatch):
    """Testa que a limpeza em lote divide corretamente em batches."""
    monkeypatch.setattr(
        "agents.transcript_cleaner.agent.generate", lambda **kwargs: "palavra"
    )
    agent = TranscriptCleanerAgent()
    segments = [
        TranscriptSegment(id=i, start=0.0, end=1.0, text=f"palavra {i}", confidence=0.9)
        for i in range(30)
    ]
    raw = TranscriptRaw(
        video_id="batch-test",
        language="pt",
        segments=segments,
    )
    cleaned = agent.run(raw)
    assert len(cleaned.segments) == 30
