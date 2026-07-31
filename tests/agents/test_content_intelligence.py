import json
from pathlib import Path

import pytest

from agents.content_intelligence.agent import ContentIntelligenceAgent
from config.settings import Settings
from shared.exceptions import ContentGenerationError
from utils.file_utils import load_json


def test_prompt_not_found_raises_error(monkeypatch):
    agent = ContentIntelligenceAgent()
    monkeypatch.setattr(
        "agents.content_intelligence.agent.settings.prompts_dir", "/inexistente/prompts"
    )
    config = type("Settings", (), {"shorts_target_count": 4})()
    with pytest.raises(ContentGenerationError):
        agent.run({"video_id": "test", "segments": []}, 60.0, config)


def test_format_transcript_capped_at_400_segments():
    agent = ContentIntelligenceAgent()
    transcript = {
        "video_id": "test",
        "segments": [{"start": i, "end": i + 1, "text": f"seg {i}"} for i in range(500)],
    }
    formatted = agent._format_transcript(transcript, max_segments=10)
    lines = formatted.strip().split("\n")
    assert len(lines) == 10


def _chunk_json_response():
    return json.dumps({
        "seo": {
            "title": "Titulo do video",
            "description": "Descricao do video",
            "hashtags": ["vampiro", "worldofdarkness"],
            "chapters": [{"timestamp_seconds": 5, "title": "Intro"}],
        },
        "thumbnail_suggestions": ["Destaque a frase"],
        "summary": {"overview": "o", "key_points": ["p1", "p2"], "next_steps": ["n"]},
    })


def test_run_consolidation_failure_falls_back_to_chunk_seo(monkeypatch):
    """Regressione: SEO nao pode sair vazio quando a consolidacao final falha."""
    agent = ContentIntelligenceAgent()
    monkeypatch.setattr(agent, "_consolidate", lambda *a, **k: {})
    monkeypatch.setattr(
        "agents.content_intelligence.agent.settings.llm_call_delay_seconds", 0.0
    )

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            return json.dumps({"shorts": []})
        return _chunk_json_response()

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)

    transcript = {
        "video_id": "v1",
        "segments": [
            {"start": 0, "end": 10, "text": "bem vindos ao canal"},
            {"start": 30, "end": 40, "text": "hoje vamos falar"},
        ],
    }
    result = agent.run(transcript, 50.0, Settings())
    assert result.seo.title == "Titulo do video"
    assert result.seo.description == "Descricao do video"
    assert result.seo.hashtags == ["vampiro", "worldofdarkness"]
    assert result.seo.chapters[0].timestamp_seconds == 5.0


def test_run_uses_consolidated_seo_and_chapters(monkeypatch):
    """Consolidacao decide titulo/descricao/hashtags e capitulos finais."""
    agent = ContentIntelligenceAgent()
    monkeypatch.setattr(
        agent,
        "_consolidate",
        lambda *a, **k: {
            "seo": {
                "title": "Titulo consolidado",
                "description": "Descricao consolidada",
                "hashtags": ["vampiro"],
                "chapters": [
                    {"timestamp_seconds": 0, "title": "Intro"},
                    {"timestamp_seconds": 30, "title": "Desenvolvimento"},
                ],
            },
            "summary": {"overview": "o", "key_points": ["k"], "next_steps": ["n"]},
        },
    )
    monkeypatch.setattr(
        "agents.content_intelligence.agent.settings.llm_call_delay_seconds", 0.0
    )

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            return json.dumps({"shorts": []})
        return _chunk_json_response()

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)

    transcript = {
        "video_id": "v1",
        "segments": [
            {"start": 0, "end": 10, "text": "bem vindos ao canal"},
            {"start": 30, "end": 40, "text": "hoje vamos falar"},
        ],
    }
    result = agent.run(transcript, 50.0, Settings())
    assert result.seo.title == "Titulo consolidado"
    assert [c.title for c in result.seo.chapters] == ["Intro", "Desenvolvimento"]


def test_run_discards_unanchored_shorts(monkeypatch):
    """Regressione D18: candidato cujo gancho/payoff nao existe na transcricao e descartado."""
    agent = ContentIntelligenceAgent()
    monkeypatch.setattr(agent, "_consolidate", lambda *a, **k: {})
    monkeypatch.setattr(
        "agents.content_intelligence.agent.settings.llm_call_delay_seconds", 0.0
    )
    monkeypatch.setattr(
        "agents.content_intelligence.agent.load_transcript_segments",
        lambda video_hash: [
            {"id": 0, "start": 0, "end": 5, "text": "bem vindos ao canal"},
            {"id": 1, "start": 30, "end": 40, "text": "hoje vamos falar do principio"},
        ],
    )

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            return json.dumps({
                "shorts": [
                    {"gancho": "frase inventada que nao existe", "payoff": "outra inventada"},
                    {"gancho": "hoje vamos falar do principio", "payoff": "frase inexistente"},
                ]
            })
        return _chunk_json_response()

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)

    transcript = {
        "video_id": "v1",
        "segments": [
            {"start": 0, "end": 5, "text": "bem vindos ao canal"},
            {"start": 30, "end": 40, "text": "hoje vamos falar do principio"},
        ],
    }
    result = agent.run(transcript, 40.0, Settings(), video_hash="abc123")
    assert result.shorts == []


def test_run_stage_passes_video_hash_to_anchoring(monkeypatch, tmp_path):
    """Regressione bug critico: run_stage deve propagar video_hash para a ancoragem."""
    agent = ContentIntelligenceAgent()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr("agents.content_intelligence.agent.settings.cache_dir", str(cache_dir))
    monkeypatch.setattr(
        "agents.content_intelligence.agent.settings.llm_call_delay_seconds", 0.0
    )

    video_hash = "abc123"
    video_cache = cache_dir / video_hash
    video_cache.mkdir()
    (video_cache / "metadata.json").write_text(
        '{"metadata": {"duration_seconds": 100.0}}', encoding="utf-8"
    )
    (video_cache / "cleaned.json").write_text(
        json.dumps({
            "video_id": "v1",
            "segments": [
                {"id": 0, "start": 0, "end": 5, "text": "bem vindos ao canal"},
                {"id": 1, "start": 30, "end": 40, "text": "hoje vamos falar do principio"},
                {"id": 2, "start": 60, "end": 70, "text": "e foi assim que ele caiu"},
            ],
        }),
        encoding="utf-8",
    )

    captured = {}

    def fake_load_transcript_segments(video_hash_arg):
        captured["video_hash"] = video_hash_arg
        return [
            {"id": 1, "start": 30, "end": 40, "text": "hoje vamos falar do principio"},
            {"id": 2, "start": 60, "end": 70, "text": "e foi assim que ele caiu"},
        ]

    monkeypatch.setattr(
        "agents.content_intelligence.agent.load_transcript_segments",
        fake_load_transcript_segments,
    )
    monkeypatch.setattr(
        agent,
        "_consolidate",
        lambda *a, **k: {
            "seo": {
                "title": "Titulo",
                "description": "Descricao",
                "hashtags": ["h1"],
                "chapters": [{"timestamp_seconds": 0, "title": "Intro"}],
            },
            "summary": {"overview": "o", "key_points": ["k"], "next_steps": ["n"]},
        },
    )

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            return json.dumps({
                "shorts": [{
                    "gancho": "hoje vamos falar do principio",
                    "payoff": "e foi assim que ele caiu",
                    "emocao": "curiosidade",
                    "justificativa": "arco completo",
                }]
            })
        return _chunk_json_response()

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)

    agent.run_stage(Path("/fake/video.mp4"), video_hash, Settings(), None)

    assert captured["video_hash"] == video_hash
    content = load_json(video_cache / "content.json")
    assert len(content["shorts"]) >= 1
    assert content["shorts"][0]["start"] == 30.0
    assert content["shorts"][0]["end"] == 70.0
    assert content["seo"]["title"] == "Titulo"


_SHORT_CANDIDATE = {
    "gancho": "hoje vamos falar do principio",
    "payoff": "e foi assim que ele caiu",
    "emocao": "curiosidade",
    "justificativa": "arco completo",
}

_TRANSCRIPT = {
    "video_id": "v1",
    "segments": [
        {"id": 0, "start": 0, "end": 5, "text": "bem vindos ao canal"},
        {"id": 1, "start": 30, "end": 40, "text": "hoje vamos falar do principio"},
        {"id": 2, "start": 60, "end": 70, "text": "e foi assim que ele caiu"},
    ],
}


def _setup_content_run(monkeypatch, agent, check_returns):
    monkeypatch.setattr(agent, "_consolidate", lambda *a, **k: {})
    monkeypatch.setattr(
        "agents.content_intelligence.agent.settings.llm_call_delay_seconds", 0.0
    )
    monkeypatch.setattr(
        "agents.content_intelligence.agent.load_transcript_segments",
        lambda video_hash: [
            {"id": 1, "start": 30, "end": 40, "text": "hoje vamos falar do principio"},
            {"id": 2, "start": 60, "end": 70, "text": "e foi assim que ele caiu"},
        ],
    )
    monkeypatch.setattr(agent, "_check_standalone", lambda short, transcript: check_returns)

    def fake_generate(system_prompt, user_prompt, json_mode=False, **kwargs):
        if "Shorts" in system_prompt:
            return json.dumps({"shorts": [_SHORT_CANDIDATE]})
        return _chunk_json_response()

    monkeypatch.setattr("agents.content_intelligence.agent.generate", fake_generate)


def test_run_populates_standalone_scores(monkeypatch):
    """D19: critico de autocontencao preenche standalone_score/standalone_notes."""
    agent = ContentIntelligenceAgent()
    _setup_content_run(monkeypatch, agent, check_returns=(0.85, "Compreensivel sozinho"))
    result = agent.run(_TRANSCRIPT, 100.0, Settings(), video_hash="abc123")
    assert len(result.shorts) == 1
    assert result.shorts[0].standalone_score == 0.85
    assert result.shorts[0].standalone_notes == "Compreensivel sozinho"


def test_run_discards_short_below_standalone_threshold(monkeypatch):
    """D19: candidato que depende de contexto externo e descartado."""
    agent = ContentIntelligenceAgent()
    _setup_content_run(monkeypatch, agent, check_returns=(0.2, "Depende de contexto anterior"))
    result = agent.run(_TRANSCRIPT, 100.0, Settings(), video_hash="abc123")
    assert result.shorts == []
