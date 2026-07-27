from unittest.mock import MagicMock, patch

import pytest

from shared.preflight import PreFlightCheck, run_preflight_checks


def test_preflight_passes_with_mocked_tools():
    with (
        patch("subprocess.run") as mock_run,
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"models": [{"name": "qwen2.5:3b"}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        errors = run_preflight_checks()
        assert errors == []


def test_preflight_fails_without_ffmpeg():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        errors = run_preflight_checks()
        assert any("FFmpeg" in e for e in errors)


def test_preflight_fails_without_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with (
        patch("subprocess.run") as mock_run,
        patch("urllib.request.urlopen", side_effect=ConnectionRefusedError()),
    ):
        mock_run.return_value = MagicMock(returncode=0)
        errors = run_preflight_checks()
        assert any("Ollama" in e for e in errors)


def test_preflight_check_class_raises_on_errors():
    with patch("shared.preflight.run_preflight_checks", return_value=["FFmpeg nao encontrado"]):
        from config.settings import Settings
        from shared.exceptions import PreflightError

        check = PreFlightCheck(Settings())
        with pytest.raises(PreflightError):
            check.run()


def test_preflight_check_class_passes_with_no_errors():
    with patch("shared.preflight.run_preflight_checks", return_value=[]):
        from config.settings import Settings

        check = PreFlightCheck(Settings())
        check.run()
