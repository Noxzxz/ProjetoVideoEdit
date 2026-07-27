from config.settings import Settings


def test_default_settings():
    s = Settings(_env_file=None)
    assert s.whisper_model_size == "small"
    assert s.whisper_device == "cuda"
    assert s.ollama_model == "qwen2.5:3b"
    assert s.shorts_max_duration_seconds == 60
    assert s.shorts_min_duration_seconds == 15
    assert s.max_words_per_line == 4
    assert s.ollama_temperature == 0.2
    assert s.llm_provider == "ollama"


def test_custom_settings_via_env(monkeypatch):
    monkeypatch.setenv("WHISPER_MODEL_SIZE", "tiny")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma2:2b")
    s = Settings()
    assert s.whisper_model_size == "tiny"
    assert s.whisper_device == "cpu"
    assert s.ollama_model == "gemma2:2b"


def test_shorts_bounds_validation():
    s = Settings()
    assert s.shorts_min_duration_seconds < s.shorts_max_duration_seconds
