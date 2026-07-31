import json
import logging
import subprocess
import urllib.request
from pathlib import Path

from config.settings import Settings
from shared.exceptions import PreflightError

logger = logging.getLogger(__name__)


def run_preflight_checks(config: Settings | None = None) -> list[str]:
    errors: list[str] = []

    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        errors.append("FFmpeg nao encontrado. Instale com: sudo apt install ffmpeg")

    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
    except Exception:
        errors.append("ffprobe nao encontrado. Instale com: sudo apt install ffmpeg")

    settings = config if config is not None else Settings()

    if settings.llm_provider == "ollama":
        try:
            req = urllib.request.Request(
                f"{settings.ollama_base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
        except Exception:
            errors.append("Ollama nao esta rodando. Execute 'ollama serve' no terminal.")
            data = None

        if data:
            models = json.loads(data).get("models", [])
            model_names = [m.get("name", "") for m in models]
            if settings.ollama_model not in model_names:
                errors.append(
                    f"Modelo '{settings.ollama_model}' nao encontrado. "
                    f"Baixe com: ollama pull {settings.ollama_model}"
                )
    elif settings.llm_provider == "gemini":
        if not settings.gemini_api_key:
            errors.append(
                "GEMINI_API_KEY nao configurada. "
                "Defina no .env ou exporte a variavel."
            )
    elif settings.llm_provider == "groq":
        if not settings.groq_api_key:
            errors.append(
                "GROQ_API_KEY nao configurada. "
                "Defina no .env ou exporte a variavel."
            )

    huggingface_cache = Path.home() / ".cache" / "huggingface" / "hub"
    if not huggingface_cache.exists():
        logger.warning("Modelo Whisper sera baixado automaticamente na primeira execucao.")

    try:
        import shutil

        free = shutil.disk_usage(settings.data_dir).free
        if free < 5 * 1024 * 1024 * 1024:
            errors.append("Espaco em disco insuficiente. Libere pelo menos 5GB.")
    except Exception:
        pass

    if settings.whisper_device == "cuda":
        try:
            import torch

            if not torch.cuda.is_available():
                logger.warning("GPU nao detectada. Whisper usara CPU (mais lento).")
        except ImportError:
            logger.warning("PyTorch nao instalado. Nao foi possivel verificar GPU.")

    prompts_dir = Path(settings.prompts_dir)
    required_prompts = ["content_intelligence.md", "cleaning_llm.md", "shorts_prompt.md"]
    missing = [p for p in required_prompts if not (prompts_dir / p).exists()]
    if missing:
        errors.append(f"Prompts obrigatorios ausentes: {missing}")

    return errors


class PreFlightCheck:
    def __init__(self, config: Settings):
        self.config = config

    def run(self) -> None:
        errors = run_preflight_checks(self.config)
        if errors:
            raise PreflightError("; ".join(errors))
        logger.info("Pre-flight check concluido com sucesso.")
