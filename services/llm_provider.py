import logging
import time
from abc import ABC, abstractmethod

import requests

from config.settings import Settings, settings
from shared.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)

# Status HTTP sujeitos a retry (D29)
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMProvider(ABC):
    def __init__(self, config: Settings):
        self.config = config

    @abstractmethod
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        ...

    def _post(
        self,
        url: str,
        *,
        payload: dict,
        headers: dict | None = None,
        timeout: int = 120,
    ) -> requests.Response:
        """POST com retry/backoff generico (D29): 429/5xx/ConnectionError."""
        max_retries = self.config.llm_max_retries
        base = self.config.llm_retry_backoff_seconds
        last_error: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            except requests.ConnectionError as err:
                last_error = err
                if attempt == max_retries:
                    break
                logger.warning(
                    f"ConnectionError (tentativa {attempt}/{max_retries}). "
                    f"Retry em {base * attempt:.1f}s"
                )
                time.sleep(base * attempt)
                continue

            if resp.status_code in RETRYABLE_STATUS:
                last_error = ExternalServiceError(
                    f"HTTP {resp.status_code}: {resp.text}"
                )
                if attempt == max_retries:
                    break
                logger.warning(
                    f"HTTP {resp.status_code} (tentativa {attempt}/{max_retries}). "
                    f"Retry em {base * attempt:.1f}s"
                )
                time.sleep(base * attempt)
                continue

            return resp

        raise ExternalServiceError(
            f"Nao foi possivel concluir a chamada LLM apos {max_retries} tentativas"
        ) from last_error


class OllamaProvider(LLMProvider):
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        cfg = self.config
        url = f"{cfg.ollama_base_url}/api/chat"
        payload = {
            "model": cfg.ollama_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature or cfg.ollama_temperature,
            },
        }
        if json_mode:
            payload["format"] = "json"

        resp = self._post(url, payload=payload, timeout=timeout)

        if resp.status_code == 404:
            raise ExternalServiceError(
                f"Modelo nao encontrado: {cfg.ollama_model}. "
                f"Execute 'ollama pull {cfg.ollama_model}'."
            )
        if resp.status_code != 200:
            raise ExternalServiceError(f"Ollama retornou {resp.status_code}: {resp.text}")

        data = resp.json()
        content = data.get("message", {}).get("content", "")
        logger.info(f"Ollama respondeu em {resp.elapsed.total_seconds():.1f}s")
        return content


class GeminiProvider(LLMProvider):
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        cfg = self.config
        api_key = cfg.gemini_api_key
        if not api_key:
            raise ExternalServiceError(
                "GEMINI_API_KEY nao configurada. Defina no .env ou exporte a variavel."
            )

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{cfg.gemini_model}:generateContent?key={api_key}"

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"[System] {system_prompt}"}]})
        contents.append({"role": "user", "parts": [{"text": user_prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature or cfg.ollama_temperature,
            },
        }
        if json_mode:
            payload["generationConfig"]["response_mime_type"] = "application/json"

        resp = self._post(url, payload=payload, timeout=timeout)

        if resp.status_code == 403:
            raise ExternalServiceError(
                "API key do Gemini invalida ou sem permisao. "
                "Gere uma em https://aistudio.google.com/apikey"
            )
        if resp.status_code != 200:
            raise ExternalServiceError(f"Gemini retornou {resp.status_code}: {resp.text}")

        data = resp.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as err:
            raise ExternalServiceError(f"Resposta inesperada do Gemini: {data}") from err

        logger.info(f"Gemini respondeu em {resp.elapsed.total_seconds():.1f}s")
        return text


class GroqProvider(LLMProvider):
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str:
        cfg = self.config
        api_key = cfg.groq_api_key
        if not api_key:
            raise ExternalServiceError(
                "GROQ_API_KEY nao configurada. Obtenha em https://console.groq.com/keys"
            )

        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": cfg.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature or cfg.ollama_temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = self._post(url, payload=payload, headers=headers, timeout=timeout)

        if resp.status_code == 401:
            raise ExternalServiceError("GROQ_API_KEY invalida. Verifique sua chave.")
        if resp.status_code != 200:
            raise ExternalServiceError(f"Groq retornou {resp.status_code}: {resp.text}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as err:
            raise ExternalServiceError(f"Resposta inesperada do Groq: {data}") from err

        logger.info(f"Groq respondeu em {resp.elapsed.total_seconds():.1f}s")
        return content


_PROVIDERS: dict[tuple[str, int], LLMProvider] = {}


def get_provider(config: Settings | None = None) -> LLMProvider:
    cfg = config or settings
    name = cfg.llm_provider
    key = (name, id(cfg))
    if key not in _PROVIDERS:
        providers = {
            "ollama": OllamaProvider,
            "gemini": GeminiProvider,
            "groq": GroqProvider,
        }
        cls = providers.get(name)
        if cls is None:
            raise ExternalServiceError(
                f"Provedor LLM desconhecido: '{name}'. "
                f"Opcoes: {', '.join(providers)}"
            )
        _PROVIDERS[key] = cls(cfg)
        logger.info(f"Provedor LLM: {name}")
    return _PROVIDERS[key]


def generate(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    json_mode: bool = False,
    timeout: int = 120,
    config: Settings | None = None,
) -> str:
    return get_provider(config).generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        json_mode=json_mode,
        timeout=timeout,
    )
