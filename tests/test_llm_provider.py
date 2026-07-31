"""Testes de retry/backoff generico (D29) no LLMProvider."""

from unittest.mock import MagicMock, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError

from config.settings import Settings
from services.llm_provider import OllamaProvider
from shared.exceptions import ExternalServiceError


def _provider(max_retries: int = 3) -> OllamaProvider:
    config = Settings()
    config.llm_max_retries = max_retries
    config.llm_retry_backoff_seconds = 0.01
    return OllamaProvider(config)


def test_post_retries_on_429_and_succeeds():
    provider = _provider()
    final = MagicMock(status_code=200, text="")
    with patch(
        "services.llm_provider.requests.post",
        side_effect=[MagicMock(status_code=429, text="rate"), final],
    ) as mock_post:
        resp = provider._post("http://x", payload={}, timeout=1)
    assert mock_post.call_count == 2
    assert resp is final


def test_post_retries_on_5xx_and_connection_error():
    provider = _provider(max_retries=3)
    final = MagicMock(status_code=200, text="")
    with patch(
        "services.llm_provider.requests.post",
        side_effect=[
            MagicMock(status_code=503, text="unavail"),
            RequestsConnectionError("boom"),
            final,
        ],
    ) as mock_post:
        resp = provider._post("http://x", payload={}, timeout=1)
    assert mock_post.call_count == 3
    assert resp is final


def test_post_raises_after_exhausting_retries():
    provider = _provider(max_retries=2)
    with patch(
        "services.llm_provider.requests.post",
        return_value=MagicMock(status_code=503, text="unavail"),
    ) as mock_post, pytest.raises(ExternalServiceError):
        provider._post("http://x", payload={}, timeout=1)
    assert mock_post.call_count == 2


def test_post_returns_immediately_on_success():
    provider = _provider()
    ok = MagicMock(status_code=200, text="")
    with patch("services.llm_provider.requests.post", return_value=ok) as mock_post:
        resp = provider._post("http://x", payload={}, timeout=1)
    assert mock_post.call_count == 1
    assert resp is ok
