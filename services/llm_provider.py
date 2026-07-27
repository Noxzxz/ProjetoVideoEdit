import logging
from abc import ABC, abstractmethod

import requests

from config.settings import settings
from shared.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
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


class OllamaProvider(LLMProvider):
    def generate(
        self,
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
            raise ExternalServiceError(
                "Ollama nao esta rodando. Execute 'ollama serve'."
            ) from err

        if resp.status_code == 404:
            raise ExternalServiceError(
                f"Modelo nao encontrado: {settings.ollama_model}. "
                f"Execute 'ollama pull {settings.ollama_model}'."
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
        api_key = settings.gemini_api_key
        if not api_key:
            raise ExternalServiceError(
                "GEMINI_API_KEY nao configurada. Defina no .env ou exporte a variavel."
            )

        model = settings.gemini_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": f"[System] {system_prompt}"}]})
        contents.append({"role": "user", "parts": [{"text": user_prompt}]})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature or settings.ollama_temperature,
            },
        }
        if json_mode:
            payload["generationConfig"]["response_mime_type"] = "application/json"

        try:
            resp = requests.post(url, json=payload, timeout=timeout)
        except requests.ConnectionError as err:
            raise ExternalServiceError(
                "Nao foi possivel conectar a API do Gemini. Verifique sua internet."
            ) from err

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
        api_key = settings.groq_api_key
        if not api_key:
            raise ExternalServiceError(
                "GROQ_API_KEY nao configurada. Obtenha em https://console.groq.com/keys"
            )

        model = settings.groq_model
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature or settings.ollama_temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        import time

        delays = [5, 10, 20, 40, 60]
        last_error: Exception | None = None
        for attempt, delay in enumerate(delays):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
            except requests.ConnectionError as err:
                last_error = err
                break

            if resp.status_code == 429:
                logger.warning(
                    f"Groq rate limit (tentativa {attempt+1}/{len(delays)}). "
                    f"Aguardando {delay}s..."
                )
                time.sleep(delay)
                last_error = ExternalServiceError(
                    f"Groq retornou 429 apos {attempt+1} tentativas: {resp.text}"
                )
                continue

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

        raise ExternalServiceError(
            "Nao foi possivel conectar a API do Groq. Verifique sua internet."
        ) from last_error


_PROVIDERS: dict[str, LLMProvider] = {}


def get_provider() -> LLMProvider:
    name = settings.llm_provider
    if name not in _PROVIDERS:
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
        _PROVIDERS[name] = cls()
        logger.info(f"Provedor LLM: {name}")
    return _PROVIDERS[name]


def generate(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    json_mode: bool = False,
    timeout: int = 120,
) -> str:
    return get_provider().generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        json_mode=json_mode,
        timeout=timeout,
    )
