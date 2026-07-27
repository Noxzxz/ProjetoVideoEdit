import logging

import requests

from config.settings import settings
from shared.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


def generate(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    json_mode: bool = False,
    timeout: int = 120,
) -> str:
    url = f"{settings.ollama_base_url}/api/chat"
    payload = {
        "model": settings.ollama_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {
            "temperature": temperature or settings.ollama_temperature,
        },
    }
    if json_mode:
        payload["format"] = "json"

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
    except requests.ConnectionError as err:
        raise ExternalServiceError("Ollama nao esta rodando. Execute 'ollama serve'.") from err

    if resp.status_code == 404:
        raise ExternalServiceError(
            f"Modelo nao encontrado. Execute 'ollama pull {settings.ollama_model}'."
        )
    if resp.status_code != 200:
        raise ExternalServiceError(f"Ollama retornou {resp.status_code}: {resp.text}")

    data = resp.json()
    content = data.get("message", {}).get("content", "")
    logger.info(f"Ollama respondeu em {resp.elapsed.total_seconds():.1f}s")
    return content
