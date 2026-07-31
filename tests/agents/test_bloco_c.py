"""Testes de regressao do Bloco C (D20-D25)."""

import json
import struct
import wave
from pathlib import Path

from agents.content_intelligence.agent import ContentIntelligenceAgent
from agents.marker_detection.agent import detect_markers
from agents.transcript_cleaner.agent import TranscriptCleanerAgent
from config.settings import Settings
from schemas.transcript import TranscriptRaw, TranscriptSegment
from services.audio_analysis_service import find_energy_peaks
from utils.glossary_correction import (
    build_initial_prompt_from_glossary,
    correct_segment_text,
    load_glossary,
)


def _fast_config(**overrides) -> Settings:
    cfg = Settings()
    cfg.llm_call_delay_seconds = 0.0
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# --- D20: glossario ---

def test_glossary_loads_terms():
    terms = load_glossary("vampiro")
    assert "Camarilla" in terms
    assert "Frenzy" in terms


def test_glossary_corrects_fuzzy_typo():
    glossary = ["Camarilla", "Frenzy", "Kindred"]
    assert correct_segment_text("a camarila chegou", glossary) == "a Camarilla chegou"
    assert correct_segment_text("o kindred chegou", glossary) == "o Kindred chegou"


def test_glossary_does_not_touch_common_words():
    glossary = ["Camarilla", "Frenzy", "Kindred", "Auspex"]
    text = "consegui hoje vamos aprender frenesi"
    assert correct_segment_text(text, glossary) == text


def test_glossary_correction_in_transcript_cleaner(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "agents.transcript_cleaner.agent.settings.glossary_name", "vampiro"
    )
    monkeypatch.setattr(
        "agents.transcript_cleaner.agent.generate",
        lambda **kwargs: "a Camarilla esta aqui",
    )
    raw = TranscriptRaw(
        video_id="v1",
        language="pt",
        segments=[
            TranscriptSegment(id=0, start=0.0, end=1.0, text="a camarila esta aqui", confidence=0.9)
        ],
    )
    cleaned = TranscriptCleanerAgent().run(raw)
    assert "Camarilla" in cleaned.full_text_cleaned


def test_initial_prompt_from_glossary():
    prompt = build_initial_prompt_from_glossary("vampiro")
    assert "Camarilla" in prompt
    assert "Frenzy" in prompt


# --- D25: marcadores OOC ---

def test_detect_markers_returns_erro_fala_and_ooc():
    raw = TranscriptRaw(
        video_id="v1",
        language="pt",
        segments=[
            TranscriptSegment(id=0, start=0.0, end=2.0, text="vamos jogar", confidence=0.9),
            TranscriptSegment(id=1, start=2.0, end=3.0, text="corte errei a fala", confidence=0.9),
            TranscriptSegment(id=2, start=3.0, end=4.0, text="inicio continuando", confidence=0.9),
            TranscriptSegment(id=3, start=4.0, end=5.0, text="pausa o pessoal", confidence=0.9),
            TranscriptSegment(id=4, start=5.0, end=6.0, text="retomando vamos la", confidence=0.9),
        ],
    )
    pairs = detect_markers(
        raw, "corte", "inicio", ooc_pause_word="pausa", ooc_resume_word="retomando"
    )
    kinds = {p.kind for p in pairs}
    assert kinds == {"erro_fala", "ooc"}
    ooc = next(p for p in pairs if p.kind == "ooc")
    assert ooc.start == 4.0
    assert ooc.end == 6.0


def test_detect_markers_without_ooc_words_is_backward_compatible():
    raw = TranscriptRaw(
        video_id="v1",
        language="pt",
        segments=[
            TranscriptSegment(id=0, start=0.0, end=2.0, text="corte errei", confidence=0.9),
            TranscriptSegment(id=1, start=2.0, end=4.0, text="inicio ok", confidence=0.9),
        ],
    )
    pairs = detect_markers(raw, "corte", "inicio")
    assert len(pairs) == 1
    assert pairs[0].kind == "erro_fala"


# --- D23/D24: campanha e hashtags chegam na consolidacao ---

def test_load_hashtags_from_glossaries_dir(monkeypatch, tmp_path):
    (tmp_path / "hashtags_vampiro.md").write_text(
        "# comentario\nVampiroAMascara\n# WorldOfDarkness\n\nRPG\n", encoding="utf-8"
    )
    config = _fast_config(hashtags_file="hashtags_vampiro.md", glossaries_dir=str(tmp_path))
    tags = ContentIntelligenceAgent._load_hashtags(config)
    assert tags == ["#VampiroAMascara", "#RPG"]


def test_consolidate_receives_campaign_and_hashtags(monkeypatch, tmp_path):
    agent = ContentIntelligenceAgent()
    campaign = tmp_path / "cronica.md"
    campaign.write_text("PC: Marcus (Ventrue)", encoding="utf-8")

    config = _fast_config(campaign_context_file=str(campaign), hashtags_file="")
    captured = {}

    def fake_consolidate(
        video_duration,
        chapters,
        thumbs,
        key_points,
        config,
        campaign_context="",
        allowed_hashtags=None,
    ):
        captured["campaign"] = campaign_context
        captured["hashtags"] = allowed_hashtags
        return {}

    monkeypatch.setattr(agent, "_consolidate", fake_consolidate)

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            return json.dumps({"shorts": []})
        return json.dumps({
            "seo": {
                "title": "t",
                "description": "d",
                "hashtags": ["h"],
                "chapters": [{"timestamp_seconds": 0, "title": "Intro"}],
            },
            "thumbnail_suggestions": [],
            "summary": {"overview": "o", "key_points": ["k"], "next_steps": ["n"]},
        })

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)

    agent.run(
        {"video_id": "v1", "segments": [{"start": 0, "end": 10, "text": "bem vindos"}]},
        10.0,
        config,
    )
    assert "Marcus" in captured["campaign"]
    assert not captured["hashtags"]


# --- D22: content_type entra no prompt de shorts ---

def test_content_type_passed_to_shorts_prompt(monkeypatch):
    agent = ContentIntelligenceAgent()
    monkeypatch.setattr(agent, "_consolidate", lambda *a, **k: {})
    captured = {}

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            captured["user"] = user_prompt
            return json.dumps({"shorts": []})
        return json.dumps({
            "seo": {"title": "t", "description": "d", "hashtags": ["h"],
                    "chapters": [{"timestamp_seconds": 0, "title": "Intro"}]},
            "thumbnail_suggestions": [],
            "summary": {"overview": "o", "key_points": ["k"], "next_steps": ["n"]},
        })

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)

    config = _fast_config(content_type="lore")
    agent.run(
        {"video_id": "v1", "segments": [{"start": 0, "end": 10, "text": "bem vindos"}]},
        10.0,
        config,
    )
    assert "Tipo de conteudo: lore" in captured["user"]


# --- D25: OOC excluido da curadoria de shorts ---

def test_run_excludes_shorts_overlapping_ooc(monkeypatch, tmp_path):
    agent = ContentIntelligenceAgent()
    monkeypatch.setattr(agent, "_consolidate", lambda *a, **k: {})
    monkeypatch.setattr(
        agent,
        "_check_standalone",
        lambda short, transcript, config: (0.9, "ok"),
    )

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr("utils.hash_utils.settings.cache_dir", str(cache_dir))
    video_cache = cache_dir / "abc123"
    video_cache.mkdir()
    (video_cache / "markers.json").write_text(
        json.dumps([
            {
                "start": 25.0,
                "end": 45.0,
                "kind": "ooc",
                "cut_word": "pausa",
                "resume_word": "retomando",
            }
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "agents.content_intelligence.agent.load_transcript_segments",
        lambda video_hash: [
            {"id": 1, "start": 30, "end": 40, "text": "hoje vamos falar do principio"},
            {"id": 2, "start": 60, "end": 70, "text": "e foi assim que ele caiu"},
        ],
    )

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            return json.dumps({"shorts": [{
                "gancho": "hoje vamos falar do principio",
                "payoff": "e foi assim que ele caiu",
                "emocao": "curiosidade",
                "justificativa": "arco",
            }]})
        return json.dumps({
            "seo": {"title": "t", "description": "d", "hashtags": ["h"],
                    "chapters": [{"timestamp_seconds": 0, "title": "Intro"}]},
            "thumbnail_suggestions": [],
            "summary": {"overview": "o", "key_points": ["k"], "next_steps": ["n"]},
        })

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)

    transcript = {
        "video_id": "v1",
        "segments": [
            {"id": 0, "start": 0, "end": 5, "text": "bem vindos"},
            {"id": 1, "start": 30, "end": 40, "text": "hoje vamos falar do principio"},
            {"id": 2, "start": 60, "end": 70, "text": "e foi assim que ele caiu"},
        ],
    }
    result = agent.run(transcript, 100.0, _fast_config(), video_hash="abc123")
    assert result.shorts == []


# --- D21: picos de energia RMS ---

def _write_test_wav(path: Path, rate: int = 8000, seconds: float = 2.0) -> Path:
    n = int(rate * seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = []
        for i in range(n):
            t = i / rate
            frames.append(9000 if 0.5 <= t < 1.5 else 0)
        wf.writeframes(b"".join(struct.pack("<h", f) for f in frames))
    return path


def test_find_energy_peaks(tmp_path):
    wav = _write_test_wav(tmp_path / "test.wav")
    peaks = find_energy_peaks(wav, window_seconds=0.5, top_n=5)
    starts = [round(p[0], 2) for p in peaks]
    assert 0.5 in starts
    assert 1.0 in starts
    assert all(p[0] >= 0.5 for p in peaks)


def test_find_energy_peaks_missing_audio(tmp_path):
    assert find_energy_peaks(tmp_path / "nao_existe.wav") == []
