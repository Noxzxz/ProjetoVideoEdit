"""Testes do config fingerprint por etapa (D27)."""


from config.settings import Settings
from pipeline.fingerprint import (
    compute_stage_fingerprint,
    compute_stage_fingerprints,
)


def test_fingerprint_is_deterministic():
    config = Settings()
    fp1 = compute_stage_fingerprint("CONTENT_INTELLIGENCE", config)
    fp2 = compute_stage_fingerprint("CONTENT_INTELLIGENCE", config)
    assert fp1 == fp2
    assert len(fp1) == 16


def test_fingerprint_changes_with_relevant_setting():
    config = Settings()
    base = compute_stage_fingerprint("TIMELINE_VALIDATION", config)
    config.shorts_min_duration_seconds = 20
    assert compute_stage_fingerprint("TIMELINE_VALIDATION", config) != base


def test_fingerprint_ignores_irrelevant_setting():
    config = Settings()
    base = compute_stage_fingerprint("MARKER_DETECTION", config)
    config.shorts_min_duration_seconds = 20  # nao afeta MARKER_DETECTION
    assert compute_stage_fingerprint("MARKER_DETECTION", config) == base


def test_fingerprint_tracks_prompt_file(tmp_path, monkeypatch):
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    (prompts / "content_intelligence.md").write_text("v1", encoding="utf-8")
    config = Settings()
    config.prompts_dir = str(prompts)
    base = compute_stage_fingerprint("CONTENT_INTELLIGENCE", config)

    (prompts / "content_intelligence.md").write_text("v2", encoding="utf-8")
    changed = compute_stage_fingerprint("CONTENT_INTELLIGENCE", config)
    assert changed != base


def test_fingerprints_cover_all_stages():
    config = Settings()
    fps = compute_stage_fingerprints(config)
    assert "VIDEO_PROCESSING" in fps
    assert "CONTENT_INTELLIGENCE" in fps
    assert "PACKAGING" in fps
    assert len(fps) == 10
