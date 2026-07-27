# Documento de Desenvolvimento Completo — Pipeline de Pós-Produção com IA

> **Versão 1.1 Consolidada** | Compatível com ADR v3
> **Hardware-alvo:** Ryzen 7 6000, GTX 1650 4 GB, 32 GB RAM, NVMe 1 TB
> **Modelos homologados:** Whisper `small` (GPU) | Qwen2.5 3B / Gemma 2 2B (CPU)

---

## Changelog — v1.1 (patch pré-implementação)

Correções aplicadas após revisão crítica do código de exemplo da v1.0
Consolidada, antes do início da implementação:

1. **[Bug crítico] Cache dir divergente entre agentes.** `generate_video_id()`
   truncava o hash para 8 chars enquanto `PipelineRunner`/`VideoProcessingAgent`
   usavam o hash completo (16 chars) — agentes liam/escreviam cache em
   diretórios diferentes, quebrando o resume silenciosamente. Corrigido
   centralizando a extração do hash em `utils/hash_utils.get_video_hash_from_id()`,
   usado por todos os agentes.
2. **[Bug crítico] `StageResult` duplicado.** Cada `run_stage()` de agente
   fazia seu próprio `state.stages.append(...)`, e o `PipelineRunner`
   também — toda etapa gerava dois registros no histórico, corrompendo
   `analytics.json`. Removido o append de dentro dos 10 agentes; agora é
   responsabilidade exclusiva do `PipelineRunner`.
3. **[Risco] `strict=True` em `PipelineState`/`StageResult`.** Podia rejeitar
   a coerção `str → Path`/`datetime` ao recarregar o estado do cache em
   disco. Removido desses dois schemas (mantido nos schemas de contrato de
   dados/LLM, onde não há esse round-trip).
4. **[Segurança/qualidade] `eval()` no parsing de FPS** (`ffmpeg_service.py`).
   Substituído por `fractions.Fraction`.
5. **[Performance crítica] `TranscriptCleanerAgent` fazia 1 chamada LLM por
   segmento** — inviável em CPU no hardware-alvo para vídeos de 20-30min.
   Reescrito para processar em batches de 25 segmentos por chamada, com
   checkpoint parcial (`cleaned.partial.json`) para não reprocessar tudo em
   caso de falha no meio.
6. **[Hardware] Sem gestão de VRAM do Whisper.** Adicionado
   `unload_whisper_model()`, chamado ao final da etapa `SPEECH_RECOGNITION` —
   relevante em sessões longas do Streamlit onde o processo não reinicia
   entre vídeos.
7. **[Performance] Sem paralelismo entre etapas independentes.**
   `SUBTITLE_STYLING`, `THUMBNAIL_FRAMES` e `SHORTS_EXTRACTION` não dependem
   umas das outras, mas rodavam sequencialmente. `PipelineRunner` agora
   agrupa e executa esse trio em paralelo via `ThreadPoolExecutor`.

---

## Sumário

1. [Visão Geral e Pipeline](#1-visão-geral-e-pipeline)
2. [Hardware e Stack](#2-hardware-e-stack)
3. [Estrutura de Pastas Definitiva](#3-estrutura-de-pastas-definitiva)
4. [Configuração](#4-configuração)
5. [Schemas Pydantic](#5-schemas-pydantic)
6. [Shared (Logging, Exceções, PreFlight, DB)](#6-shared)
7. [Utils](#7-utils)
8. [Prompts](#8-prompts)
9. [Serviços](#9-serviços)
10. [Agentes](#10-agentes)
11. [PipelineRunner](#11-pipelinerunner)
12. [CLI](#12-cli)
13. [Streamlit Dashboard](#13-streamlit-dashboard)
14. [Packaging](#14-packaging)
15. [Testes](#15-testes)
16. [pyproject.toml](#16-pyprojecttoml)
17. [Checklist Final de Aprovação](#17-checklist-final-de-aprovação)
18. [Notas para Vibe Coding](#18-notas-para-vibe-coding)

---

## 1. Visão Geral e Pipeline

Ferramenta pessoal de pós-produção de vídeo 100% local/open source. Executa em hardware pessoal (Ryzen 7 6000, GTX 1650 4GB).

**Pipeline sequencial:**

```
Vídeo Bruto
    ↓
[Pre-Flight Check] → aborta se ambiente quebrado
    ↓
[Video Processing] → extrai áudio WAV 16kHz mono + metadados
    ↓
[Speech Recognition] → faster-whisper small (GPU) + VAD
    ↓
[Transcript Cleaner] → Regex (lista fechada) + LLM (fluidez/pontuação)
    ↓
[Content Intelligence] → 1 inferência LLM → SEO + Shorts + Thumbnail + Resumo
    ↓
[Timeline Validator] → valida timestamps, durações, ordenação
    ↓
[Video Edit] → detecta silêncios, corta via FFmpeg (copy ou reencode)
    ↓
[Subtitle Styling] → gera SRT + VTT (quebra em max 4 palavras/linha)
    ↓
[Thumbnail Frames] → OpenCV: histograma + Laplaciano/blur → 3-5 frames
    ↓
[Shorts Extraction] → extrai cada ShortCandidate em .mp4 individual
    ↓
[Packaging] → analytics.json + relatório final + ZIP
    ↓
Outputs/<video_id>/
```

**Decisões arquiteturais (ADR v3):**
- ❌ LangGraph removido → PipelineRunner sequencial
- ❌ MoviePy removido → apenas FFmpeg e OpenCV
- ❌ Burn-in de legendas removido da V1 → apenas SRT/VTT
- ❌ Modelos 7B não são requisito
- ✅ Configuração única em `config.yaml` (flat)
- ✅ Prompts externos em `prompts/*.md`
- ✅ Cache por hash de vídeo em `cache/<hash>/`
- ✅ Pre-flight check obrigatório
- ✅ SQLite apenas para analytics/histórico
- ✅ VAD ativado por padrão
- ✅ Content Intelligence unificado (1 inferência)
- ✅ Timeline Validator separado e determinístico

---

## 2. Hardware e Stack

### Hardware-Alvo

```text
CPU:     Ryzen 7 6000
GPU:     GTX 1650 4 GB
RAM:     32 GB
SSD:     NVMe 1 TB
```

### Modelos Homologados

| Modelo | Uso | Hardware |
|---|---|---|
| faster-whisper `small` | Transcrição | GPU (CUDA) |
| Qwen2.5 3B | LLM geral | CPU (ou GPU leve) |
| Gemma 2 2B | LLM alternativo | CPU |

### Stack Tecnológica

| Tecnologia | Status |
|---|---|
| Python 3.11+ | ✅ |
| Pydantic v2 | ✅ (contratos) |
| faster-whisper | ✅ (GPU, small, VAD) |
| Ollama | ✅ (HTTP POST /api/chat) |
| FFmpeg | ✅ (subprocess direto, lista de args) |
| OpenCV | ✅ (frames de thumbnail) |
| SQLite | ✅ (apenas analytics) |
| Streamlit | ✅ (dashboard single-page) |
| requests | ✅ (cliente HTTP para Ollama) |
| pytest | ✅ |
| Ruff | ✅ (lint + format, line-length=100) |
| LangGraph | ❌ removido |
| MoviePy | ❌ removido |
| ffmpeg-python | ❌ removido |
| Redis | ❌ fora do escopo |
| Kubernetes | ❌ fora do escopo |

---

## 3. Estrutura de Pastas Definitiva

```
ai-video-pipeline/
├── main.py                          # CLI entry point
├── pyproject.toml                   # Dependências
├── .env.example                     # Variáveis de ambiente
├── README.md
├── config/
│   ├── __init__.py
│   ├── settings.py                  # Pydantic-Settings (flat)
│   └── config.yaml                  # ÚNICA fonte de verdade
├── prompts/
│   ├── content_intelligence.md      # Prompt de sistema unificado
│   ├── cleaning_llm.md              # Prompt de sistema do cleaner
│   └── thumbnail_prompt.md          # Prompt para análise de frames (opcional)
├── app/
│   ├── __init__.py
│   ├── cli.py                       # Parsing de args
│   └── streamlit_app.py             # Dashboard single-page
├── pipeline/
│   ├── __init__.py
│   └── runner.py                    # PipelineRunner + PipelineState + StageResult
├── agents/
│   ├── __init__.py
│   ├── video_processing/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── speech_recognition/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── transcript_cleaner/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── content_intelligence/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── timeline_validator/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── video_edit/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── subtitle_styling/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── thumbnail_frames/
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── shorts_extractor/
│   │   ├── __init__.py
│   │   └── agent.py                 # NOVO — extrai shorts em .mp4
│   └── packaging/
│       ├── __init__.py
│       └── agent.py
├── services/
│   ├── __init__.py
│   ├── ffmpeg_service.py
│   ├── whisper_service.py
│   ├── ollama_service.py
│   └── opencv_service.py
├── schemas/
│   ├── __init__.py
│   ├── video.py
│   ├── transcript.py
│   ├── content.py
│   ├── edit.py
│   ├── subtitle.py
│   ├── analytics.py                 # Schema unificado
│   ├── state.py                     # PipelineState, StageResult
│   └── enums.py
├── shared/
│   ├── __init__.py
│   ├── logging_config.py
│   ├── exceptions.py                # PipelineError base (único)
│   ├── preflight.py                 # run_preflight_checks() + PreFlightCheck
│   └── db/
│       ├── __init__.py
│       ├── database.py
│       └── repositories.py
├── utils/
│   ├── __init__.py
│   ├── time_utils.py
│   ├── slugify.py
│   ├── file_utils.py
│   └── hash_utils.py
├── cache/                           # .gitignored
├── data/
│   ├── raw/
│   └── intermediate/
├── outputs/                         # .gitignored
├── logs/                            # .gitignored
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_preflight.py
    ├── test_settings.py
    ├── test_cache.py
    ├── test_runner.py
    ├── test_packaging.py
    ├── agents/
    │   ├── test_video_processing.py
    │   ├── test_speech_recognition.py
    │   ├── test_transcript_cleaner.py
    │   ├── test_content_intelligence.py
    │   ├── test_timeline_validator.py
    │   ├── test_video_edit.py
    │   ├── test_subtitle_styling.py
    │   ├── test_thumbnail_frames.py
    │   ├── test_shorts_extractor.py
    │   └── test_packaging.py
    └── fixtures/
        ├── sample_5s.mp4
        └── sample_5s.wav
```

---

## 4. Configuração

### 4.1 config/config.yaml

```yaml
# ÚNICA fonte de verdade — formato FLAT
data_dir: "data"
outputs_dir: "outputs"
cache_dir: "cache"
logs_dir: "logs"
whisper_model_size: "small"
whisper_device: "cuda"
whisper_vad_filter: true
whisper_vad_threshold: 0.5
ollama_base_url: "http://localhost:11434"
ollama_model: "qwen2.5:3b"
ollama_temperature: 0.2
sqlite_path: "shared/db/analytics.db"
log_level: "INFO"
shorts_max_duration_seconds: 60
shorts_min_duration_seconds: 15
silence_threshold_db: -35.0
min_gap_seconds: 0.6
video_codec: "libx264"
audio_codec: "aac"
video_preset: "fast"
prompts_dir: "prompts"
max_words_per_line: 4
```

### 4.2 config/settings.py

```python
from pydantic_settings import BaseSettings
from pathlib import Path
from typing import Literal


class Settings(BaseSettings):
    """
    Configuração central tipada do pipeline.
    Lê de variáveis de ambiente (.env) com fallback para defaults.
    """

    # Diretórios
    data_dir: str = "data"
    outputs_dir: str = "outputs"
    cache_dir: str = "cache"
    logs_dir: str = "logs"
    prompts_dir: str = "prompts"

    # Whisper
    whisper_model_size: Literal["tiny", "base", "small", "medium", "large-v3"] = "small"
    whisper_device: Literal["cuda", "cpu"] = "cuda"
    whisper_vad_filter: bool = True
    whisper_vad_threshold: float = 0.5

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_temperature: float = 0.2

    # SQLite
    sqlite_path: str = "shared/db/analytics.db"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Shorts
    shorts_max_duration_seconds: int = 60
    shorts_min_duration_seconds: int = 15

    # Edição
    silence_threshold_db: float = -35.0
    min_gap_seconds: float = 0.6
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_preset: str = "fast"

    # Legendas
    max_words_per_line: int = 4

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 4.3 .env.example

```bash
# Opcional — todos os campos têm defaults em config/settings.py
DATA_DIR=data
OUTPUTS_DIR=outputs
CACHE_DIR=cache
LOGS_DIR=logs
WHISPER_MODEL_SIZE=small
WHISPER_DEVICE=cuda
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
LOG_LEVEL=INFO
```

---

## 5. Schemas Pydantic

### 5.1 schemas/enums.py

```python
from enum import Enum


class JobStatusEnum(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class AgentNameEnum(str, Enum):
    VIDEO_PROCESSING = "VIDEO_PROCESSING"
    SPEECH_RECOGNITION = "SPEECH_RECOGNITION"
    TRANSCRIPT_CLEANER = "TRANSCRIPT_CLEANER"
    CONTENT_INTELLIGENCE = "CONTENT_INTELLIGENCE"
    TIMELINE_VALIDATOR = "TIMELINE_VALIDATOR"
    VIDEO_EDIT = "VIDEO_EDIT"
    SUBTITLE_STYLING = "SUBTITLE_STYLING"
    THUMBNAIL_FRAMES = "THUMBNAIL_FRAMES"
    SHORTS_EXTRACTION = "SHORTS_EXTRACTION"
    PACKAGING = "PACKAGING"
```

### 5.2 schemas/video.py

```python
from pydantic import BaseModel, ConfigDict


class VideoMetadata(BaseModel):
    model_config = ConfigDict(strict=True)
    duration_seconds: float
    fps: float
    width: int
    height: int
    codec: str
    has_audio_track: bool


class VideoIngestResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    original_path: str
    audio_path: str
    metadata: VideoMetadata
```

### 5.3 schemas/transcript.py

```python
from pydantic import BaseModel, Field, ConfigDict, model_validator


class TranscriptSegment(BaseModel):
    model_config = ConfigDict(strict=True)
    id: int
    start: float
    end: float
    text: str
    confidence: float = Field(ge=0, le=1)


class TranscriptRaw(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    language: str
    segments: list[TranscriptSegment]
    full_text: str = ""

    @model_validator(mode="after")
    def compute_full_text(self):
        self.full_text = " ".join(s.text.strip() for s in self.segments)
        return self


class TranscriptCleaned(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    segments: list[TranscriptSegment]
    full_text_cleaned: str
```

### 5.4 schemas/content.py

```python
from pydantic import BaseModel, Field, ConfigDict


class Chapter(BaseModel):
    model_config = ConfigDict(strict=True)
    timestamp_seconds: float
    title: str = Field(max_length=60)


class ShortCandidate(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float
    end: float
    reason: str
    score: float = Field(ge=0, le=1)


class ThumbnailPromptItem(BaseModel):
    model_config = ConfigDict(strict=True)
    prompt_pt: str
    prompt_en: str
    mood: str


class SeoContent(BaseModel):
    model_config = ConfigDict(strict=True)
    title: str = Field(max_length=100)
    description: str
    hashtags: list[str]
    chapters: list[Chapter]


class SummaryContent(BaseModel):
    model_config = ConfigDict(strict=True)
    overview: str
    key_points: list[str]
    next_steps: list[str]


class ContentIntelligenceResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    seo: SeoContent
    shorts: list[ShortCandidate]
    thumbnail: list[ThumbnailPromptItem]
    summary: SummaryContent
```

### 5.5 schemas/edit.py

```python
from pydantic import BaseModel, ConfigDict


class CutInstruction(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float
    end: float


class CutList(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    segments_to_keep: list[CutInstruction]
    total_duration_kept: float


class EditResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    output_path: str
    cut_list: CutList
```

### 5.6 schemas/subtitle.py

```python
from pydantic import BaseModel, ConfigDict


class SubtitleStyle(BaseModel):
    model_config = ConfigDict(strict=True)
    max_words_per_line: int = 4
    font_size: int = 48


class SubtitleResult(BaseModel):
    model_config = ConfigDict(strict=True)
    video_id: str
    srt_path: str
    vtt_path: str
```

### 5.7 schemas/analytics.py

```python
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from pathlib import Path
from typing import Literal


class StageMetric(BaseModel):
    model_config = ConfigDict(strict=True)
    stage: str
    duration_seconds: float
    status: Literal["success", "skipped", "failed"]


class ShortMetric(BaseModel):
    model_config = ConfigDict(strict=True)
    start: float
    end: float
    duration_seconds: float
    score: float
    reason: str
    file_name: str | None = None


class ThumbnailMetric(BaseModel):
    model_config = ConfigDict(strict=True)
    file_name: str
    sharpness_score: float
    selected_reason: str


class AnalyticsReport(BaseModel):
    model_config = ConfigDict(strict=True)
    video_hash: str
    video_name: str
    video_duration_seconds: float
    processed_at: datetime
    pipeline_version: str = "1.0.0"
    config_snapshot: dict
    stages: list[StageMetric]
    transcript_stats: dict = Field(default_factory=dict)
    content: dict = Field(default_factory=dict)
    shorts: list[ShortMetric] = Field(default_factory=list)
    thumbnails: list[ThumbnailMetric] = Field(default_factory=list)
    total_processing_time_seconds: float
    output_directory: Path
```

### 5.8 schemas/state.py

```python
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from pathlib import Path
from typing import Literal

# IMPORTANTE: PipelineState e StageResult são persistidos em
# cache/<hash>/pipeline_state.json e recarregados a cada execução do
# PipelineRunner (para suportar --from e resume automático). Com
# strict=True, o Pydantic pode rejeitar a coerção automática de
# str -> Path e str -> datetime que acontece ao validar dados vindos
# de JSON (json.load sempre retorna strings), quebrando o carregamento
# do estado salvo. Por isso estes dois schemas usam validação NÃO
# estrita — diferente dos schemas de contrato de dados/LLM (video.py,
# transcript.py, content.py etc.), que continuam com strict=True
# porque não fazem esse round-trip disco->objeto.


class StageResult(BaseModel):
    stage: str
    status: Literal["success", "skipped", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    output_paths: list[Path] = Field(default_factory=list)
    error_message: str | None = None


class PipelineState(BaseModel):
    video_hash: str
    video_path: Path
    created_at: datetime
    updated_at: datetime
    stages: list[StageResult] = Field(default_factory=list)
    current_stage: str | None = None
    completed: bool = False

    def last_successful_stage(self) -> str | None:
        for stage_result in reversed(self.stages):
            if stage_result.status == "success":
                return stage_result.stage
        return None

    def is_stage_done(self, stage_name: str) -> bool:
        return any(s.stage == stage_name and s.status == "success" for s in self.stages)
```

---

## 6. Shared

### 6.1 shared/exceptions.py

```python
class PipelineError(Exception):
    """Exceção base de todo o pipeline."""

    pass


class VideoNotFoundError(PipelineError):
    """Arquivo de vídeo não encontrado ou inacessível."""

    pass


class AudioExtractionError(PipelineError):
    """Falha ao extrair áudio do vídeo via FFmpeg."""

    pass


class TranscriptionError(PipelineError):
    """Falha na transcrição com Whisper."""

    pass


class CleaningError(PipelineError):
    """Falha na limpeza de transcrição."""

    pass


class ContentGenerationError(PipelineError):
    """Falha na geração de conteúdo inteligente."""

    pass


class TimelineValidationError(PipelineError):
    """Falha na validação de timeline."""

    pass


class EditingError(PipelineError):
    """Falha na edição de vídeo."""

    pass


class ExportError(PipelineError):
    """Falha na exportação de artefatos."""

    pass


class ExternalServiceError(PipelineError):
    """Serviço externo (Ollama, FFmpeg) indisponível ou respondeu com erro."""

    pass


class PreflightError(PipelineError):
    """Pre-flight check detectou ambiente inadequado."""

    pass
```

### 6.2 shared/logging_config.py

```python
import logging
import logging.handlers
from pathlib import Path
from config.settings import settings


def setup_logging(log_level: str | None = None) -> None:
    level = log_level or settings.log_level
    log_dir = Path(settings.logs_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "pipeline.log"

    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s - %(message)s")

    # Console
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # Arquivo com rotação
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    root.handlers = [console_handler, file_handler]
```

### 6.3 shared/preflight.py

```python
import logging
import subprocess
import urllib.request
from pathlib import Path
from config.settings import Settings
from shared.exceptions import PreflightError

logger = logging.getLogger(__name__)


def run_preflight_checks() -> list[str]:
    """
    Verifica o ambiente antes de qualquer processamento.
    Retorna lista de erros (vazia = tudo OK).
    """
    errors: list[str] = []

    # 1. FFmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        errors.append("FFmpeg não encontrado. Instale com: sudo apt install ffmpeg")

    # 2. ffprobe
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
    except Exception:
        errors.append("ffprobe não encontrado. Instale com: sudo apt install ffmpeg")

    # 3. Ollama respondendo
    try:
        settings = Settings()
        req = urllib.request.Request(
            f"{settings.ollama_base_url}/api/tags",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read()
    except Exception:
        errors.append("Ollama não está rodando. Execute 'ollama serve' no terminal.")
        data = None

    # 4. Modelo LLM disponível
    if data:
        import json

        models = json.loads(data).get("models", [])
        model_names = [m.get("name", "") for m in models]
        if settings.ollama_model not in model_names:
            errors.append(
                f"Modelo '{settings.ollama_model}' não encontrado. "
                f"Baixe com: ollama pull {settings.ollama_model}"
            )

    # 5. Modelo Whisper (warning, não erro fatal)
    huggingface_cache = Path.home() / ".cache" / "huggingface" / "hub"
    if not huggingface_cache.exists():
        logger.warning("Modelo Whisper será baixado automaticamente na primeira execução.")

    # 6. Espaço em disco
    try:
        import shutil

        free = shutil.disk_usage(settings.data_dir).free
        if free < 5 * 1024 * 1024 * 1024:
            errors.append("Espaço em disco insuficiente. Libere pelo menos 5GB.")
    except Exception:
        pass

    # 7. GPU disponível (warning)
    if settings.whisper_device == "cuda":
        try:
            import torch

            if not torch.cuda.is_available():
                logger.warning("GPU não detectada. Whisper usará CPU (mais lento).")
        except ImportError:
            logger.warning("PyTorch não instalado. Não foi possível verificar GPU.")

    # 8. Pasta de prompts
    prompts_dir = Path(settings.prompts_dir)
    required_prompts = ["content_intelligence.md", "cleaning_llm.md", "thumbnail_prompt.md"]
    missing = [p for p in required_prompts if not (prompts_dir / p).exists()]
    if missing:
        errors.append(f"Prompts obrigatórios ausentes: {missing}")

    return errors


class PreFlightCheck:
    """Wrapper em classe para compatibilidade com CLI/Runner."""

    def __init__(self, config: Settings):
        self.config = config

    def run(self) -> None:
        """Executa pre-flight check. Levanta PreflightError se falhar."""
        errors = run_preflight_checks()
        if errors:
            raise PreflightError("; ".join(errors))
        logger.info("Pre-flight check concluído com sucesso.")
```

### 6.4 shared/db/database.py

```python
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from config.settings import settings

Base = declarative_base()


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(Integer, primary_key=True)
    video_hash = Column(String, nullable=False)
    video_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    total_duration_seconds = Column(Float, nullable=True)


class AgentMetric(Base):
    __tablename__ = "agent_metrics"
    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey("pipeline_runs.id"), nullable=False)
    agent_name = Column(String, nullable=False)
    step = Column(String, nullable=False)
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String, nullable=False)
    error_message = Column(String, nullable=True)


def init_db():
    engine = create_engine(f"sqlite:///{settings.sqlite_path}")
    Base.metadata.create_all(engine)
    return engine


Session = sessionmaker()
```

### 6.5 shared/db/repositories.py

```python
from datetime import datetime
from sqlalchemy.orm import Session as SqlSession
from shared.db.database import init_db, PipelineRun, AgentMetric


class AnalyticsRepository:
    def __init__(self):
        self.engine = init_db()

    def create_run(self, video_hash: str, video_name: str) -> int:
        with SqlSession(self.engine) as session:
            run = PipelineRun(
                video_hash=video_hash,
                video_name=video_name,
                status="RUNNING",
                started_at=datetime.now(),
            )
            session.add(run)
            session.commit()
            return run.id

    def mark_run_done(self, run_id: int, total_duration: float) -> None:
        with SqlSession(self.engine) as session:
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "DONE"
                run.finished_at = datetime.now()
                run.total_duration_seconds = total_duration
                session.commit()

    def mark_run_failed(self, run_id: int, error: str) -> None:
        with SqlSession(self.engine) as session:
            run = session.get(PipelineRun, run_id)
            if run:
                run.status = "FAILED"
                run.finished_at = datetime.now()
                session.commit()

    def log_metric(
        self,
        run_id: int,
        agent_name: str,
        step: str,
        started_at: datetime,
        finished_at: datetime,
        status: str,
        error_message: str | None = None,
    ) -> None:
        with SqlSession(self.engine) as session:
            metric = AgentMetric(
                run_id=run_id,
                agent_name=agent_name,
                step=step,
                started_at=started_at,
                finished_at=finished_at,
                status=status,
                error_message=error_message,
            )
            session.add(metric)
            session.commit()

    def get_run_history(self, limit: int = 20) -> list[PipelineRun]:
        with SqlSession(self.engine) as session:
            return (
                session.query(PipelineRun)
                .order_by(PipelineRun.started_at.desc())
                .limit(limit)
                .all()
            )
```

---

## 7. Utils

### 7.1 utils/hash_utils.py

```python
import hashlib
from pathlib import Path
from config.settings import settings


def compute_video_hash(video_path: Path) -> str:
    """Calcula SHA-256 do arquivo em blocos de 1MB. Retorna hex de 16 chars (64 bits)."""
    h = hashlib.sha256()
    with open(video_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()[:16]


def get_cache_dir(video_hash: str) -> Path:
    return Path(settings.cache_dir) / video_hash


def get_video_hash_from_id(video_id: str) -> str:
    """
    Extrai o video_hash (16 chars) a partir do video_id (formato
    '<slug>-<hash16>', ver utils/slugify.generate_video_id).

    CENTRALIZADO DE PROPÓSITO: nenhum agente deve fazer
    `video_id.split("-")[-1]` manualmente. Se a lógica de formação do
    video_id mudar no futuro, só este ponto precisa ser atualizado —
    do contrário, agentes voltam a divergir silenciosamente sobre qual
    é o cache_dir correto (foi exatamente isso que quebrou o cache
    entre VideoProcessingAgent e os agentes seguintes na v1.0).
    """
    return video_id.rsplit("-", 1)[-1]
```

### 7.2 utils/file_utils.py

```python
import json
import os
from pathlib import Path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp), str(path))
```

### 7.3 utils/time_utils.py

```python
def seconds_to_hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def seconds_to_srt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def seconds_to_vtt_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def hms_to_seconds(hms: str) -> float:
    parts = hms.strip().split(":")
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s)
    elif len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s)
    raise ValueError(f"Formato inválido: {hms}")
```

### 7.4 utils/slugify.py

```python
import re


def slugify_filename(filename: str) -> str:
    name = filename.rsplit(".", 1)[0] if "." in filename else filename
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    name = re.sub(r"-+", "-", name)
    return name.strip("-")


def generate_video_id(filename: str, video_hash: str) -> str:
    """
    IMPORTANTE: usa o video_hash COMPLETO (16 chars), não um prefixo.
    Vários agentes recuperam o hash a partir do video_id via
    `video_id.split("-")[-1]` para montar o cache_dir (ver
    utils/hash_utils.get_cache_dir). Se aqui for usado apenas um prefixo
    (ex: video_hash[:8]), esses agentes passam a apontar para um
    cache_dir DIFERENTE do usado pelo PipelineRunner e por
    VideoProcessingAgent (que usam o hash completo de 16 chars),
    quebrando o cache/resume silenciosamente. Nunca truncar aqui.
    """
    return f"{slugify_filename(filename)}-{video_hash}"
```

---

## 8. Prompts

### 8.1 prompts/cleaning_llm.md

```markdown
# Prompt de Sistema — Limpeza de Transcrição

Você é um editor de texto especializado em transcrições de vídeo em português.

Sua única função é melhorar a fluidez, pontuação e capitalização do texto fornecido.

REGRAS ABSOLUTAS:
- NUNCA adicione informação que não esteja no texto original.
- NUNCA resuma ou condense o conteúdo.
- NUNCA remova fatos, números, nomes próprios ou termos técnicos.
- NUNCA altere o significado das frases.
- Apenas corrija: pontuação, capitalização de início de frase, espaços extras.
- Responda APENAS com o texto corrigido. Sem aspas. Sem comentários. Sem explicações.
```

### 8.2 prompts/content_intelligence.md

```markdown
# Prompt de Sistema — Content Intelligence

Você é um especialista em marketing de conteúdo, SEO e análise de vídeo.

Analise a transcrição fornecida (com timestamps) e gere um pacote completo de conteúdo.

REGRAS ABSOLUTAS:
- Responda APENAS em JSON válido, sem comentários, sem markdown, sem texto fora do JSON.
- NUNCA invente fatos que não estejam na transcrição.
- NUNCA sugira timestamps fora da duração real do vídeo.
- O título deve ter no máximo 100 caracteres.
- A descrição deve ser informativa e conter quebras de parágrafo.
- Hashtags devem ser relevantes e NÃO incluir o caractere # no JSON.
- Capítulos devem cobrir do início ao fim do vídeo, em ordem crescente, sem sobreposição.
- Shorts devem ter duração entre 15 e 60 segundos.
- Thumbnail prompts devem existir em português (prompt_pt) e inglês (prompt_en).
- O resumo deve conter: visão geral, 3 a 8 pontos principais, e próximos passos (se aplicável).

FORMATO DE RESPOSTA (JSON):
{
  "seo": {
    "title": "...",
    "description": "...",
    "hashtags": ["...", "..."],
    "chapters": [{"timestamp_seconds": 120, "title": "..."}]
  },
  "shorts": [
    {"start": 125.5, "end": 180.0, "reason": "...", "score": 0.92}
  ],
  "thumbnail": [
    {"prompt_pt": "...", "prompt_en": "...", "mood": "..."}
  ],
  "summary": {
    "overview": "...",
    "key_points": ["...", "..."],
    "next_steps": ["...", "..."]
  }
}
```

### 8.3 prompts/thumbnail_prompt.md

```markdown
# Prompt de Sistema — Análise de Thumbnail

Você é um designer de thumbnails para vídeos no YouTube.

Analise os frames candidatos extraídos do vídeo e sugira qual seria o melhor para uma thumbnail impactante.

REGRAS:
- Considere composição, iluminação, expressões faciais (se houver pessoas) e contraste.
- Sugira ajustes de cor ou texto overlay que poderiam melhorar o frame.
- Responda em português.
```

---

## 9. Serviços

### 9.1 services/ffmpeg_service.py

```python
import logging
import subprocess
from fractions import Fraction
from pathlib import Path
from config.settings import Settings
from schemas.video import VideoMetadata, VideoIngestResult
from schemas.edit import CutList
from shared.exceptions import VideoNotFoundError, AudioExtractionError, EditingError

logger = logging.getLogger(__name__)


def get_video_metadata(video_path: Path) -> VideoMetadata:
    if not video_path.exists():
        raise VideoNotFoundError(f"Arquivo não encontrado: {video_path}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioExtractionError(f"ffprobe falhou: {result.stderr}")

    import json

    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    format_info = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = float(format_info.get("duration", 0))
    fps_str = video_stream.get("r_frame_rate", "30/1")
    # Nunca usar eval() em string vinda de metadata externa (mesmo que
    # normalmente confiável, é um hábito perigoso). Fraction() faz o
    # parse de "30000/1001" com segurança e sem risco de execução de
    # código arbitrário.
    fps = float(Fraction(fps_str)) if "/" in fps_str else float(fps_str)

    return VideoMetadata(
        duration_seconds=duration,
        fps=fps,
        width=video_stream.get("width", 0),
        height=video_stream.get("height", 0),
        codec=video_stream.get("codec_name", "unknown"),
        has_audio_track=audio_stream is not None,
    )


def extract_audio(video_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioExtractionError(f"FFmpeg falhou: {result.stderr}")
    logger.info(f"Áudio extraído: {output_path}")
    return output_path


def get_video_duration(video_path: Path) -> float:
    return get_video_metadata(video_path).duration_seconds


def apply_cut_list(video_path: Path, cut_list: CutList, output_path: Path) -> Path:
    """Corta e concatena trechos via FFmpeg."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = output_path.parent / "tmp_cuts"
    temp_dir.mkdir(parents=True, exist_ok=True)

    segment_files: list[Path] = []
    try:
        for idx, cut in enumerate(cut_list.segments_to_keep):
            seg_path = temp_dir / f"temp_{idx:03d}.mp4"
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(cut.start),
                "-to",
                str(cut.end),
                "-i",
                str(video_path),
                "-c",
                "copy",
                str(seg_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # Fallback reencode
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    str(cut.start),
                    "-to",
                    str(cut.end),
                    "-i",
                    str(video_path),
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    str(seg_path),
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    raise EditingError(f"Corte falhou: {result.stderr}")
            segment_files.append(seg_path)

        # Concat demuxer
        list_file = temp_dir / "concat_list.txt"
        with open(list_file, "w") as f:
            for seg in segment_files:
                f.write(f"file '{seg.resolve()}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise EditingError(f"Concatenação falhou: {result.stderr}")

        logger.info(f"Vídeo editado: {output_path}")
        return output_path
    finally:
        # Limpeza
        for f in temp_dir.glob("*"):
            f.unlink(missing_ok=True)
        temp_dir.rmdir()


def extract_segment(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    output_path: Path,
    config: Settings,
) -> Path:
    """Extrai um trecho do vídeo. Tenta -c copy primeiro."""
    duration = end_seconds - start_seconds
    cmd_copy = [
        "ffmpeg",
        "-y",
        "-ss",
        str(start_seconds),
        "-t",
        str(duration),
        "-i",
        str(video_path),
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path),
    ]
    result = subprocess.run(cmd_copy, capture_output=True, text=True)
    if result.returncode != 0:
        cmd_reenc = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_seconds),
            "-t",
            str(duration),
            "-i",
            str(video_path),
            "-c:v",
            config.video_codec,
            "-c:a",
            config.audio_codec,
            "-preset",
            config.video_preset,
            str(output_path),
        ]
        result = subprocess.run(cmd_reenc, capture_output=True, text=True)
        if result.returncode != 0:
            raise EditingError(f"Falha ao extrair segmento: {result.stderr}")
    return output_path
```

### 9.2 services/whisper_service.py

```python
import logging
from pathlib import Path
from faster_whisper import WhisperModel
from config.settings import Settings
from schemas.transcript import TranscriptRaw, TranscriptSegment
from shared.exceptions import TranscriptionError

logger = logging.getLogger(__name__)
settings = Settings()

_model: WhisperModel | None = None


def _load_model() -> WhisperModel:
    global _model
    if _model is None:
        compute_type = "int8" if settings.whisper_device == "cpu" else "float16"
        _model = WhisperModel(
            settings.whisper_model_size,
            device=settings.whisper_device,
            compute_type=compute_type,
        )
    return _model


def transcribe(audio_path: Path, video_id: str) -> TranscriptRaw:
    if not audio_path.exists():
        raise TranscriptionError(f"Áudio não encontrado: {audio_path}")

    try:
        model = _load_model()
        segments_iter, info = model.transcribe(
            str(audio_path),
            vad_filter=settings.whisper_vad_filter,
            vad_parameters=dict(threshold=settings.whisper_vad_threshold),
        )

        segments: list[TranscriptSegment] = []
        for idx, seg in enumerate(segments_iter):
            confidence = min(1.0, max(0.0, 1.0 + seg.avg_logprob))
            segments.append(
                TranscriptSegment(
                    id=idx,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text.strip(),
                    confidence=confidence,
                )
            )

        return TranscriptRaw(
            video_id=video_id,
            language=info.language or "pt",
            segments=segments,
        )
    except Exception as exc:
        raise TranscriptionError(f"Falha na transcrição: {exc}") from exc


def unload_whisper_model() -> None:
    """
    Libera o modelo Whisper e a VRAM associada.

    Na GTX 1650 (4GB), manter o modelo carregado sem necessidade é
    desperdício de VRAM que poderia ser usada por outra etapa. Em
    execução via CLI isso é irrelevante (processo termina e libera
    tudo sozinho), mas em execução via Streamlit o processo do
    dashboard fica de pé entre vídeos processados na mesma sessão —
    sem isso, a VRAM do Whisper nunca é devolvida. Chamar ao final da
    etapa SPEECH_RECOGNITION (ver agents/speech_recognition/agent.py).
    """
    global _model
    if _model is not None:
        del _model
        _model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("Modelo Whisper descarregado da VRAM")
```

### 9.3 services/ollama_service.py

```python
import logging
import requests
from config.settings import Settings
from shared.exceptions import ExternalServiceError

logger = logging.getLogger(__name__)
settings = Settings()


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
    except requests.ConnectionError:
        raise ExternalServiceError("Ollama não está rodando. Execute 'ollama serve'.")

    if resp.status_code == 404:
        raise ExternalServiceError(
            f"Modelo não encontrado. Execute 'ollama pull {settings.ollama_model}'."
        )
    if resp.status_code != 200:
        raise ExternalServiceError(f"Ollama retornou {resp.status_code}: {resp.text}")

    data = resp.json()
    content = data.get("message", {}).get("content", "")
    logger.info(f"Ollama respondeu em {resp.elapsed.total_seconds():.1f}s")
    return content
```

### 9.4 services/opencv_service.py

```python
import logging
from pathlib import Path
import cv2
import numpy as np
from shared.exceptions import VideoNotFoundError

logger = logging.getLogger(__name__)


def extract_candidate_frames(
    video_path: Path,
    output_dir: Path,
    max_frames: int = 5,
    min_spacing_percent: float = 5.0,
) -> list[Path]:
    if not video_path.exists():
        raise VideoNotFoundError(f"Vídeo não encontrado: {video_path}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise VideoNotFoundError(f"Não foi possível abrir: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    spacing_seconds = (min_spacing_percent / 100) * duration

    frames_data: list[tuple[int, float, np.ndarray]] = []
    prev_hist: np.ndarray | None = None
    frame_idx = 0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % int(fps or 1) == 0:
                hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
                hist = cv2.calcHist([hsv], [0, 1], None, [50, 60], [0, 180, 0, 256])
                cv2.normalize(hist, hist)

                scene_dist = 1.0
                if prev_hist is not None:
                    corr = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                    scene_dist = 1.0 - max(0.0, corr)

                # Blur detection
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
                if lap_var >= 100:
                    frames_data.append((frame_idx, scene_dist, frame.copy()))

                prev_hist = hist

            frame_idx += 1
    finally:
        cap.release()

    # Sort by scene distance (highest first)
    frames_data.sort(key=lambda x: x[1], reverse=True)

    # Apply spacing filter
    selected: list[tuple[int, np.ndarray]] = []
    for idx, dist, frame in frames_data:
        timestamp = idx / fps
        if all(abs(timestamp - (s[0] / fps)) >= spacing_seconds for s in selected):
            selected.append((idx, frame))
        if len(selected) >= max_frames:
            break

    selected.sort(key=lambda x: x[0])

    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for idx, (frame_idx, frame) in enumerate(selected):
        timestamp = int(frame_idx / fps)
        out_path = output_dir / f"frame_{timestamp:03d}.jpg"
        cv2.imwrite(str(out_path), frame)
        paths.append(out_path)

    logger.info(f"{len(paths)} frames candidatos extraídos em {output_dir}")
    return paths
```

---

## 10. Agentes

**Interface unificada:** Todo agente expõe `run_stage(video_path: Path, video_hash: str, config: Settings, state: PipelineState)`.

### 10.1 agents/video_processing/agent.py

```python
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.video import VideoIngestResult
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from shared.exceptions import VideoNotFoundError, AudioExtractionError
from services.ffmpeg_service import get_video_metadata, extract_audio
from utils.hash_utils import compute_video_hash, get_cache_dir
from utils.slugify import generate_video_id
from utils.file_utils import ensure_dir, load_json, save_json

logger = logging.getLogger(__name__)


class VideoProcessingAgent:
    def __init__(self):
        pass

    def run(self, video_path: str) -> VideoIngestResult:
        path = Path(video_path)
        if not path.exists():
            raise VideoNotFoundError(f"Arquivo não encontrado: {video_path}")

        video_hash = compute_video_hash(path)
        video_id = generate_video_id(path.name, video_hash)
        cache_dir = get_cache_dir(video_hash)

        # Verifica cache
        cached = load_json(cache_dir / "metadata.json")
        if cached:
            logger.info("Metadados carregados do cache")
            return VideoIngestResult(**cached)

        metadata = get_video_metadata(path)
        if not metadata.has_audio_track:
            raise AudioExtractionError("Vídeo não possui trilha de áudio")

        audio_path = Path("data/intermediate") / video_id / "audio.wav"
        ensure_dir(audio_path.parent)
        extract_audio(path, audio_path)

        result = VideoIngestResult(
            video_id=video_id,
            original_path=str(path),
            audio_path=str(audio_path),
            metadata=metadata,
        )

        save_json(cache_dir / "metadata.json", result.model_dump())
        logger.info(f"Vídeo processado: {video_id}")
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        # NOTA: run_stage() NÃO deve fazer state.stages.append() — isso é
        # responsabilidade exclusiva do PipelineRunner, que já registra o
        # StageResult (com started_at/finished_at/duration corretos) após
        # chamar este handler. Fazer o append aqui também duplicava cada
        # entrada no histórico de estágios e corrompia analytics.json.
        self.run(str(video_path))
```

### 10.2 agents/speech_recognition/agent.py

```python
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.transcript import TranscriptRaw
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from shared.exceptions import TranscriptionError
from services.whisper_service import transcribe, unload_whisper_model
from utils.hash_utils import get_cache_dir, get_video_hash_from_id
from utils.file_utils import load_json, save_json

logger = logging.getLogger(__name__)


class SpeechRecognitionAgent:
    def __init__(self):
        pass

    def run(self, video_id: str, audio_path: str) -> TranscriptRaw:
        cache_dir = get_cache_dir(get_video_hash_from_id(video_id))
        cached = load_json(cache_dir / "transcript.json")
        if cached:
            logger.info("Transcrição carregada do cache")
            return TranscriptRaw(**cached)

        if not Path(audio_path).exists():
            raise TranscriptionError(f"Áudio não encontrado: {audio_path}")

        result = transcribe(Path(audio_path), video_id)
        save_json(cache_dir / "transcript.json", result.model_dump())
        logger.info(f"Transcrição concluída: {len(result.segments)} segmentos")
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        cache_dir = get_cache_dir(video_hash)
        meta = load_json(cache_dir / "metadata.json")
        if not meta:
            raise TranscriptionError("metadata.json não encontrado no cache")

        result = self.run(meta["video_id"], meta["audio_path"])
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner
        # (evita duplicar entradas no histórico — ver comentário em
        # VideoProcessingAgent.run_stage).
        # Libera a VRAM do Whisper assim que a transcrição termina —
        # nenhuma etapa seguinte do pipeline precisa de GPU. Importante
        # sobretudo em sessões longas do Streamlit (ver
        # services/whisper_service.unload_whisper_model).
        unload_whisper_model()
```

### 10.3 agents/transcript_cleaner/agent.py

```python
import re
import json
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.transcript import TranscriptRaw, TranscriptCleaned, TranscriptSegment
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from shared.exceptions import ExternalServiceError, CleaningError
from services.ollama_service import generate
from utils.hash_utils import get_cache_dir, get_video_hash_from_id
from utils.file_utils import load_json, save_json

logger = logging.getLogger(__name__)

# Lista FECHADA de preenchimentos vocais
FILLER_PATTERNS = [r"\bhum\b", r"\bah\b", r"\bahn\b", r"\bãhn\b", r"\behm\b"]
FILLER_REGEX = re.compile("|".join(FILLER_PATTERNS), re.IGNORECASE)

# Quantos segmentos são enviados por chamada ao LLM. Ver nota de
# performance abaixo — v1.0 fazia 1 chamada LLM POR SEGMENTO, o que em
# CPU (Qwen2.5 3B) inviabiliza vídeos de 20-30min no hardware-alvo.
CLEANING_BATCH_SIZE = 25


def apply_regex_cleaning(text: str) -> str:
    """
    Remove preenchimentos vocais usando regex com word boundaries.
    Lista FECHADA: hum, ah, ahn, ãhn, ehm.
    PROIBIDO remover: é, tipo, né, tá, etc.
    """
    cleaned = FILLER_REGEX.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else text


class TranscriptCleanerAgent:
    def __init__(self):
        pass

    def run(self, transcript: TranscriptRaw) -> TranscriptCleaned:
        cache_dir = get_cache_dir(get_video_hash_from_id(transcript.video_id))
        cached = load_json(cache_dir / "cleaned.json")
        if cached:
            logger.info("Transcrição limpa carregada do cache")
            return TranscriptCleaned(**cached)

        system_prompt = Path("prompts/cleaning_llm.md").read_text(encoding="utf-8")

        # Checkpoint parcial: se uma execução anterior morreu no meio
        # (ex: Ollama travou no batch 8 de 15), retomamos do último
        # batch salvo em vez de reprocessar tudo. Crítico no
        # hardware-alvo (LLM em CPU), onde cada batch já é caro.
        partial_path = cache_dir / "cleaned.partial.json"
        partial = load_json(partial_path) or {}
        cleaned_by_id: dict[int, TranscriptSegment] = {
            int(k): TranscriptSegment(**v) for k, v in partial.items()
        }

        pending = [s for s in transcript.segments if s.id not in cleaned_by_id]
        batches = [
            pending[i : i + CLEANING_BATCH_SIZE]
            for i in range(0, len(pending), CLEANING_BATCH_SIZE)
        ]

        for batch_num, batch in enumerate(batches, start=1):
            pre_cleaned_map = {}
            for seg in batch:
                pre = apply_regex_cleaning(seg.text)
                pre_cleaned_map[seg.id] = pre if pre.strip() else seg.text

            items = [{"id": seg_id, "text": text} for seg_id, text in pre_cleaned_map.items()]
            user_prompt = (
                "Corrija pontuação, capitalização e fluidez de CADA item da lista JSON "
                "a seguir. NÃO adicione informação nova. NÃO resuma. NÃO remova conteúdo "
                "factual. NÃO funda, divida ou reordene itens — a lista de saída deve ter "
                "exatamente os mesmos 'id's da entrada. Responda APENAS com um JSON no "
                'formato {"items": [{"id": <int>, "text": "<texto corrigido>"}, ...]}.\n\n'
                f"Entrada:\n{json.dumps(items, ensure_ascii=False)}"
            )

            try:
                raw = generate(system_prompt, user_prompt, temperature=0.2, json_mode=True)
                data = json.loads(raw)
                corrected = {int(it["id"]): str(it["text"]) for it in data.get("items", [])}
            except ExternalServiceError:
                raise
            except Exception as exc:
                raise CleaningError(f"LLM falhou no batch {batch_num}/{len(batches)}: {exc}")

            for seg in batch:
                pre_cleaned = pre_cleaned_map[seg.id]
                llm_text = corrected.get(seg.id, "").strip().strip('"').strip("'")

                # Anti-alucinação: se o item sumiu da resposta ou o
                # tamanho variou demais, mantém o texto pré-limpo (regex)
                # em vez de aceitar a saída do LLM.
                if not llm_text:
                    logger.warning(f"Segmento {seg.id}: ausente na resposta do LLM, mantendo regex")
                    llm_text = pre_cleaned
                else:
                    original_len = len(pre_cleaned)
                    cleaned_len = len(llm_text)
                    if cleaned_len < original_len * 0.5 or cleaned_len > original_len * 2.0:
                        logger.warning(
                            f"Segmento {seg.id}: limpeza rejeitada por diferença de tamanho"
                        )
                        llm_text = pre_cleaned

                cleaned_by_id[seg.id] = TranscriptSegment(
                    id=seg.id,
                    start=seg.start,
                    end=seg.end,
                    text=llm_text,
                    confidence=seg.confidence,
                )

            # Salva o checkpoint parcial após cada batch concluído.
            save_json(
                partial_path,
                {str(k): v.model_dump() for k, v in cleaned_by_id.items()},
            )
            logger.info(f"Batch de limpeza {batch_num}/{len(batches)} concluído")

        cleaned_segments = [cleaned_by_id[s.id] for s in transcript.segments]
        result = TranscriptCleaned(
            video_id=transcript.video_id,
            segments=cleaned_segments,
            full_text_cleaned=" ".join(s.text for s in cleaned_segments),
        )

        save_json(cache_dir / "cleaned.json", result.model_dump())
        partial_path.unlink(missing_ok=True)
        logger.info("Limpeza de transcrição concluída")
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        cache_dir = get_cache_dir(video_hash)
        raw_data = load_json(cache_dir / "transcript.json")
        if not raw_data:
            raise CleaningError("transcript.json não encontrado no cache")

        transcript = TranscriptRaw(**raw_data)
        self.run(transcript)
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

### 10.4 agents/content_intelligence/agent.py

```python
import json
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.content import ContentIntelligenceResult
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from shared.exceptions import ExternalServiceError, ContentGenerationError
from services.ollama_service import generate
from utils.hash_utils import get_cache_dir, get_video_hash_from_id
from utils.file_utils import load_json, save_json

logger = logging.getLogger(__name__)


class ContentIntelligenceAgent:
    def __init__(self):
        pass

    def _format_transcript(self, transcript_data: dict, max_segments: int = 400) -> str:
        segments = transcript_data.get("segments", [])
        if len(segments) > max_segments:
            step = len(segments) // max_segments
            segments = segments[::step][:max_segments]

        lines = []
        for seg in segments:
            start = seg["start"]
            end = seg["end"]
            m_start = int(start // 60)
            s_start = int(start % 60)
            m_end = int(end // 60)
            s_end = int(end % 60)
            lines.append(f"[{m_start:02d}:{s_start:02d}-{m_end:02d}:{s_end:02d}] {seg['text']}")
        return "\n".join(lines)

    def run(self, transcript: dict, video_duration_seconds: float) -> ContentIntelligenceResult:
        video_id = transcript.get("video_id", "unknown")
        cache_dir = get_cache_dir(get_video_hash_from_id(video_id))
        cached = load_json(cache_dir / "content.json")
        if cached:
            logger.info("Content Intelligence carregado do cache")
            return ContentIntelligenceResult(**cached)

        system_prompt = Path("prompts/content_intelligence.md").read_text(encoding="utf-8")
        formatted = self._format_transcript(transcript)

        user_prompt = (
            f"Duração total do vídeo: {video_duration_seconds:.1f} segundos.\n\n"
            f"Transcrição:\n{formatted}\n\n"
            "Gere o pacote completo de conteúdo em JSON válido."
        )

        # Primeira tentativa
        try:
            raw = generate(system_prompt, user_prompt, json_mode=True, timeout=180)
            data = json.loads(raw)
        except (json.JSONDecodeError, ExternalServiceError) as exc:
            # Retry com prompt de correção
            logger.warning(f"JSON malformado, tentando retry: {exc}")
            retry_prompt = (
                user_prompt
                + "\n\nATENÇÃO: A resposta anterior não era JSON válido. Responda APENAS em JSON válido."
            )
            try:
                raw = generate(system_prompt, retry_prompt, json_mode=True, timeout=180)
                data = json.loads(raw)
            except Exception as exc2:
                raise ContentGenerationError(f"Falha ao parsear JSON do LLM após retry: {exc2}")

        # Garante video_id
        data["video_id"] = video_id

        try:
            result = ContentIntelligenceResult(**data)
        except Exception as exc:
            raise ContentGenerationError(f"Validação Pydantic falhou: {exc}")

        save_json(cache_dir / "content.json", result.model_dump())
        logger.info("Content Intelligence concluído")
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        cache_dir = get_cache_dir(video_hash)
        cleaned_data = load_json(cache_dir / "cleaned.json")
        meta_data = load_json(cache_dir / "metadata.json")
        if not cleaned_data or not meta_data:
            raise ContentGenerationError("Dados de entrada não encontrados no cache")

        duration = meta_data.get("metadata", {}).get("duration_seconds", 0)
        self.run(cleaned_data, duration)
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

### 10.5 agents/timeline_validator/agent.py

```python
import logging
from datetime import datetime

from config.settings import Settings
from schemas.content import ContentIntelligenceResult, ShortCandidate, Chapter
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from utils.hash_utils import get_cache_dir, get_video_hash_from_id
from utils.file_utils import load_json, save_json

logger = logging.getLogger(__name__)


class TimelineValidatorAgent:
    def __init__(self):
        pass

    def run(
        self, content: ContentIntelligenceResult, video_duration_seconds: float, config: Settings
    ) -> ContentIntelligenceResult:
        cache_dir = get_cache_dir(get_video_hash_from_id(content.video_id))
        cached = load_json(cache_dir / "timeline.json")
        if cached:
            logger.info("Timeline validada carregada do cache")
            return ContentIntelligenceResult(**cached)

        # Valida capítulos
        chapters = sorted(content.seo.chapters, key=lambda c: c.timestamp_seconds)
        valid_chapters: list[Chapter] = []
        seen_timestamps: set[float] = set()

        for ch in chapters:
            if ch.timestamp_seconds < 0 or ch.timestamp_seconds > video_duration_seconds:
                logger.warning(f"Capítulo fora do vídeo: {ch.timestamp_seconds}s")
                continue
            if ch.timestamp_seconds in seen_timestamps:
                logger.warning(f"Capítulo duplicado: {ch.timestamp_seconds}s")
                continue
            seen_timestamps.add(ch.timestamp_seconds)
            valid_chapters.append(ch)

        if not valid_chapters or valid_chapters[0].timestamp_seconds > 0:
            valid_chapters.insert(0, Chapter(timestamp_seconds=0.0, title="Introdução"))
            logger.info("Capítulo 'Introdução' inserido no 0s")

        # Valida shorts
        valid_shorts: list[ShortCandidate] = []
        for short in content.shorts:
            start = max(0.0, short.start)
            end = min(short.end, video_duration_seconds)
            duration = end - start

            if start >= end:
                logger.warning(f"Short inválido: start >= end ({start} >= {end})")
                continue
            if duration < config.shorts_min_duration_seconds:
                logger.warning(f"Short muito curto: {duration:.1f}s")
                continue
            if duration > config.shorts_max_duration_seconds:
                logger.warning(f"Short muito longo: {duration:.1f}s")
                continue

            valid_shorts.append(
                ShortCandidate(start=start, end=end, reason=short.reason, score=short.score)
            )

        # Fallback se nenhum short válido
        if not valid_shorts and content.shorts:
            best = max(content.shorts, key=lambda s: s.score)
            start = max(0.0, best.start)
            end = min(best.end, video_duration_seconds)
            duration = end - start
            if duration > config.shorts_max_duration_seconds:
                end = start + config.shorts_max_duration_seconds
            if end - start < config.shorts_min_duration_seconds:
                end = start + config.shorts_min_duration_seconds
            end = min(end, video_duration_seconds)
            valid_shorts.append(
                ShortCandidate(
                    start=start, end=end, reason=best.reason + " (ajustado)", score=best.score
                )
            )
            logger.warning("Nenhum short válido gerado. Usando fallback.")

        valid_shorts.sort(key=lambda s: s.score, reverse=True)
        valid_shorts = valid_shorts[:5]

        result = ContentIntelligenceResult(
            video_id=content.video_id,
            seo=content.seo.model_copy(update={"chapters": valid_chapters}),
            shorts=valid_shorts,
            thumbnail=content.thumbnail,
            summary=content.summary,
        )

        save_json(cache_dir / "timeline.json", result.model_dump())
        logger.info(
            f"Timeline validada: {len(valid_chapters)} capítulos, {len(valid_shorts)} shorts"
        )
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        cache_dir = get_cache_dir(video_hash)
        content_data = load_json(cache_dir / "content.json")
        meta_data = load_json(cache_dir / "metadata.json")
        if not content_data or not meta_data:
            raise TimelineValidationError("Dados de entrada não encontrados no cache")

        content = ContentIntelligenceResult(**content_data)
        duration = meta_data.get("metadata", {}).get("duration_seconds", 0)
        self.run(content, duration, config)
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

### 10.6 agents/video_edit/agent.py

```python
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.transcript import TranscriptRaw
from schemas.edit import CutInstruction, CutList, EditResult
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from shared.exceptions import EditingError
from services.ffmpeg_service import apply_cut_list
from utils.hash_utils import get_cache_dir, get_video_hash_from_id
from utils.slugify import generate_video_id
from utils.file_utils import load_json, save_json, ensure_dir

logger = logging.getLogger(__name__)


def build_cut_list(
    transcript: TranscriptRaw,
    video_duration_seconds: float,
    min_gap_seconds: float = 0.6,
    safety_margin: float = 0.15,
) -> CutList:
    """
    Gera lista de trechos a MANTER no vídeo, removendo silêncios longos.
    """
    segments = sorted(transcript.segments, key=lambda s: s.start)
    kept: list[CutInstruction] = []

    for i, seg in enumerate(segments):
        start_eff = max(0.0, seg.start - safety_margin)
        end_eff = min(video_duration_seconds, seg.end + safety_margin)

        if kept:
            gap = start_eff - kept[-1].end
            if gap <= min_gap_seconds:
                # Mescla com o trecho anterior
                kept[-1] = CutInstruction(start=kept[-1].start, end=end_eff)
                continue

        kept.append(CutInstruction(start=start_eff, end=end_eff))

    # Remove gaps no início e fim
    if kept and kept[0].start < min_gap_seconds:
        kept[0] = CutInstruction(start=0.0, end=kept[0].end)

    if kept and (video_duration_seconds - kept[-1].end) < min_gap_seconds:
        kept[-1] = CutInstruction(start=kept[-1].start, end=video_duration_seconds)

    total_kept = sum(c.end - c.start for c in kept)
    return CutList(
        video_id=transcript.video_id,
        segments_to_keep=kept,
        total_duration_kept=total_kept,
    )


class VideoEditAgent:
    def __init__(self):
        pass

    def run(self, video_ingest: dict, transcript: dict, config: Settings) -> EditResult:
        video_id = video_ingest["video_id"]
        video_hash = get_video_hash_from_id(video_id)
        cache_dir = get_cache_dir(video_hash)
        cached = load_json(cache_dir / "edit.json")
        if cached:
            logger.info("Edição carregada do cache")
            return EditResult(**cached)

        transcript_obj = TranscriptRaw(**transcript)
        duration = video_ingest["metadata"]["duration_seconds"]
        cut_list = build_cut_list(transcript_obj, duration, config.min_gap_seconds)

        output_path = Path(config.outputs_dir) / video_id / "video_editado.mp4"
        ensure_dir(output_path.parent)

        apply_cut_list(Path(video_ingest["original_path"]), cut_list, output_path)

        result = EditResult(
            video_id=video_id,
            output_path=str(output_path),
            cut_list=cut_list,
        )

        save_json(cache_dir / "edit.json", result.model_dump())
        logger.info(f"Vídeo editado: {output_path}")
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        cache_dir = get_cache_dir(video_hash)
        meta = load_json(cache_dir / "metadata.json")
        transcript = load_json(cache_dir / "transcript.json")
        if not meta or not transcript:
            raise EditingError("Dados de entrada não encontrados no cache")

        self.run(meta, transcript, config)
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

### 10.7 agents/subtitle_styling/agent.py

```python
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.transcript import TranscriptCleaned, TranscriptSegment
from schemas.subtitle import SubtitleResult
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from utils.time_utils import seconds_to_srt_timestamp, seconds_to_vtt_timestamp
from utils.hash_utils import get_cache_dir, get_video_hash_from_id
from utils.slugify import generate_video_id
from utils.file_utils import load_json, save_json, ensure_dir

logger = logging.getLogger(__name__)


def split_into_caption_chunks(
    segments: list[TranscriptSegment],
    max_words_per_line: int,
) -> list[TranscriptSegment]:
    """Quebra segmentos longos em pedaços menores, redistribuindo tempo proporcionalmente."""
    chunks: list[TranscriptSegment] = []
    chunk_id = 0

    for seg in segments:
        words = seg.text.split()
        if len(words) <= max_words_per_line:
            chunks.append(
                TranscriptSegment(
                    id=chunk_id,
                    start=seg.start,
                    end=seg.end,
                    text=seg.text,
                    confidence=seg.confidence,
                )
            )
            chunk_id += 1
            continue

        # Divide em N chunks
        n_chunks = (len(words) + max_words_per_line - 1) // max_words_per_line
        total_duration = seg.end - seg.start
        words_per_chunk = len(words) / n_chunks

        for i in range(n_chunks):
            start_word = int(i * words_per_chunk)
            end_word = int((i + 1) * words_per_chunk) if i < n_chunks - 1 else len(words)
            chunk_words = words[start_word:end_word]
            chunk_text = " ".join(chunk_words)

            # Tempo proporcional
            ratio = len(chunk_words) / len(words)
            chunk_start = seg.start + (total_duration * (start_word / len(words)))
            chunk_end = chunk_start + (total_duration * ratio)

            chunks.append(
                TranscriptSegment(
                    id=chunk_id,
                    start=chunk_start,
                    end=chunk_end,
                    text=chunk_text,
                    confidence=seg.confidence,
                )
            )
            chunk_id += 1

    return chunks


def to_srt(chunks: list[TranscriptSegment]) -> str:
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        lines.append(str(i))
        lines.append(
            f"{seconds_to_srt_timestamp(chunk.start)} --> {seconds_to_srt_timestamp(chunk.end)}"
        )
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines)


def to_vtt(chunks: list[TranscriptSegment]) -> str:
    lines = ["WEBVTT", ""]
    for chunk in chunks:
        lines.append(
            f"{seconds_to_vtt_timestamp(chunk.start)} --> {seconds_to_vtt_timestamp(chunk.end)}"
        )
        lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines)


class SubtitleStylingAgent:
    def __init__(self):
        pass

    def run(self, video_id: str, transcript: TranscriptCleaned, config: Settings) -> SubtitleResult:
        cache_dir = get_cache_dir(get_video_hash_from_id(video_id))
        cached = load_json(cache_dir / "subtitle.json")
        if cached:
            logger.info("Legendas carregadas do cache")
            return SubtitleResult(**cached)

        chunks = split_into_caption_chunks(transcript.segments, config.max_words_per_line)

        output_dir = Path(config.outputs_dir) / video_id
        ensure_dir(output_dir)

        srt_path = output_dir / "legendas.srt"
        vtt_path = output_dir / "legendas.vtt"

        srt_path.write_text(to_srt(chunks), encoding="utf-8")
        vtt_path.write_text(to_vtt(chunks), encoding="utf-8")

        result = SubtitleResult(
            video_id=video_id,
            srt_path=str(srt_path),
            vtt_path=str(vtt_path),
        )

        save_json(cache_dir / "subtitle.json", result.model_dump())
        logger.info(f"Legendas geradas: {srt_path}, {vtt_path}")
        return result

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        cache_dir = get_cache_dir(video_hash)
        cleaned_data = load_json(cache_dir / "cleaned.json")
        if not cleaned_data:
            raise ExportError("cleaned.json não encontrado no cache")

        transcript = TranscriptCleaned(**cleaned_data)
        self.run(transcript.video_id, transcript, config)
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

### 10.8 agents/thumbnail_frames/agent.py

```python
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from services.opencv_service import extract_candidate_frames
from utils.hash_utils import get_cache_dir, get_video_hash_from_id
from utils.slugify import generate_video_id
from utils.file_utils import load_json, save_json, ensure_dir

logger = logging.getLogger(__name__)


class ThumbnailFramesAgent:
    def __init__(self):
        pass

    def run(self, video_id: str, original_video_path: str, config: Settings) -> list[Path]:
        cache_dir = get_cache_dir(get_video_hash_from_id(video_id))
        cached = load_json(cache_dir / "frames.json")
        if cached:
            logger.info("Frames carregados do cache")
            return [Path(p) for p in cached["frame_paths"]]

        output_dir = Path(config.outputs_dir) / video_id / "thumbnail_frames"
        ensure_dir(output_dir)

        try:
            paths = extract_candidate_frames(
                video_path=Path(original_video_path),
                output_dir=output_dir,
                max_frames=5,
            )
        except Exception as exc:
            logger.warning(f"Falha ao extrair frames: {exc}")
            paths = []

        save_json(cache_dir / "frames.json", {"frame_paths": [str(p) for p in paths]})
        logger.info(f"{len(paths)} frames extraídos")
        return paths

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        video_id = generate_video_id(video_path.name, video_hash)
        self.run(video_id, str(video_path), config)
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

### 10.9 agents/shorts_extractor/agent.py

```python
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.content import ContentIntelligenceResult
from schemas.state import PipelineState, StageResult
from schemas.enums import AgentNameEnum
from shared.exceptions import EditingError
from services.ffmpeg_service import extract_segment
from utils.hash_utils import get_cache_dir
from utils.file_utils import ensure_dir, load_json, save_json

logger = logging.getLogger(__name__)


class ShortsExtractorAgent:
    def __init__(self):
        pass

    def run(
        self,
        video_path: Path,
        content: ContentIntelligenceResult,
        output_dir: Path,
        config: Settings,
    ) -> list[Path]:
        ensure_dir(output_dir)
        shorts_paths: list[Path] = []

        for idx, short in enumerate(content.shorts[:5], start=1):
            start = max(0.0, short.start)
            end = min(short.end, content.video_duration_seconds)
            duration = end - start

            if duration < config.shorts_min_duration_seconds:
                logger.warning(f"Short #{idx} muito curto ({duration:.1f}s). Pulando.")
                continue

            output_path = output_dir / f"short_{idx:02d}.mp4"
            try:
                extract_segment(video_path, start, end, output_path, config)
                shorts_paths.append(output_path)
                logger.info(f"Short #{idx} extraído: {output_path} ({duration:.1f}s)")
            except Exception as exc:
                logger.error(f"Falha ao extrair short #{idx}: {exc}")

        return shorts_paths

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        cache_dir = get_cache_dir(video_hash)
        timeline_path = cache_dir / "timeline.json"

        if not timeline_path.exists():
            logger.warning("timeline.json não encontrado. Pulando extração de shorts.")
            return

        timeline_data = load_json(timeline_path)
        if not timeline_data:
            return

        content = ContentIntelligenceResult(**timeline_data)

        # Usa vídeo editado se existir, senão vídeo original
        video_id = timeline_data.get("video_id", f"video-{video_hash}")
        edited_video = Path(config.outputs_dir) / video_id / "video_editado.mp4"
        source_video = edited_video if edited_video.exists() else video_path

        output_dir = Path(config.outputs_dir) / video_id / "shorts"
        shorts_paths = self.run(source_video, content, output_dir, config)

        save_json(cache_dir / "shorts.json", {"short_paths": [str(p) for p in shorts_paths]})
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

### 10.10 agents/packaging/agent.py

```python
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from schemas.state import PipelineState, StageResult
from schemas.analytics import AnalyticsReport, StageMetric, ShortMetric, ThumbnailMetric
from schemas.enums import AgentNameEnum
from utils.file_utils import ensure_dir, load_json, save_json
from utils.hash_utils import get_cache_dir
from utils.slugify import generate_video_id

logger = logging.getLogger(__name__)


class PackagingAgent:
    def __init__(self):
        pass

    def run(
        self,
        video_path: Path,
        video_hash: str,
        config: Settings,
        state: PipelineState,
    ) -> AnalyticsReport:
        video_id = generate_video_id(video_path.name, video_hash)
        cache_dir = get_cache_dir(video_hash)
        output_dir = Path(config.outputs_dir) / video_id
        ensure_dir(output_dir)

        # 1. Copia artefatos
        self._copy_if_exists(cache_dir / "edit.json", output_dir / "edit_manifest.json")

        # Vídeo editado
        edited_video = Path(config.outputs_dir) / video_id / "video_editado.mp4"
        if edited_video.exists():
            shutil.copy2(edited_video, output_dir / "video_editado.mp4")

        # Legendas
        for ext in ["srt", "vtt"]:
            src = Path(config.outputs_dir) / video_id / f"legendas.{ext}"
            if src.exists():
                shutil.copy2(src, output_dir / f"legendas.{ext}")

        # Thumbnails
        thumbs_src = Path(config.outputs_dir) / video_id / "thumbnail_frames"
        thumbs_out = output_dir / "thumbnail_frames"
        if thumbs_src.exists():
            shutil.copytree(thumbs_src, thumbs_out, dirs_exist_ok=True)

        # Shorts
        shorts_src = Path(config.outputs_dir) / video_id / "shorts"
        shorts_out = output_dir / "shorts"
        if shorts_src.exists():
            shutil.copytree(shorts_src, shorts_out, dirs_exist_ok=True)

        # 2. Gera relatório Markdown
        self._generate_report(state, output_dir, video_id)

        # 3. Gera analytics.json
        analytics = self._build_analytics(
            video_path, video_hash, video_id, config, state, output_dir
        )
        save_json(output_dir / "analytics.json", analytics.model_dump(mode="json"))

        # 4. Gera ZIP
        zip_path = Path(config.outputs_dir) / f"{video_id}_package.zip"
        shutil.make_archive(
            base_name=str(zip_path.with_suffix("")),
            format="zip",
            root_dir=output_dir,
        )
        logger.info(f"Pacote ZIP criado: {zip_path}")

        logger.info(f"Empacotamento concluído em: {output_dir}")
        return analytics

    def _copy_if_exists(self, src: Path, dst: Path) -> None:
        if src.exists():
            shutil.copy2(src, dst)

    def _generate_report(self, state: PipelineState, output_dir: Path, video_id: str) -> None:
        lines = [
            f"# Relatório de Pós-Produção",
            f"",
            f"**Vídeo:** {state.video_path.name}",
            f"**Hash:** `{state.video_hash}`",
            f"**ID:** `{video_id}`",
            f"**Processado em:** {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            f"**Tempo total:** {sum(s.duration_seconds for s in state.stages):.1f}s",
            f"",
            f"## Etapas Executadas",
            f"",
            "| Status | Etapa | Duração |",
            "|--------|-------|---------|",
        ]
        for s in state.stages:
            icon = "✅" if s.status == "success" else "⏭️" if s.status == "skipped" else "❌"
            lines.append(f"| {icon} | {s.stage} | {s.duration_seconds:.1f}s |")

        lines.extend(
            [
                "",
                "---",
                "*Gerado automaticamente pelo Pipeline de Pós-Produção com IA*",
            ]
        )

        with open(output_dir / "report.md", "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def _build_analytics(
        self,
        video_path: Path,
        video_hash: str,
        video_id: str,
        config: Settings,
        state: PipelineState,
        output_dir: Path,
    ) -> AnalyticsReport:
        cache_dir = get_cache_dir(video_hash)

        # Metadados
        meta_path = cache_dir / "metadata.json"
        video_duration = 0.0
        if meta_path.exists():
            meta = load_json(meta_path) or {}
            video_duration = meta.get("metadata", {}).get("duration_seconds", 0.0)

        # Conteúdo
        content_data = {}
        content_path = cache_dir / "timeline.json"
        if content_path.exists():
            content_data = load_json(content_path) or {}

        # Shorts
        shorts_metrics = []
        for i, s in enumerate(content_data.get("shorts", []), start=1):
            shorts_metrics.append(
                ShortMetric(
                    start=s["start"],
                    end=s["end"],
                    duration_seconds=round(s["end"] - s["start"], 2),
                    score=s.get("score", 0.0),
                    reason=s.get("reason", ""),
                    file_name=f"short_{i:02d}.mp4" if (output_dir / "shorts").exists() else None,
                )
            )

        # Thumbnails
        thumbs_metrics = []
        thumbs_dir = output_dir / "thumbnail_frames"
        if thumbs_dir.exists():
            for frame in sorted(thumbs_dir.glob("*.jpg")):
                thumbs_metrics.append(
                    ThumbnailMetric(
                        file_name=frame.name,
                        sharpness_score=0.0,
                        selected_reason="heurística de histograma + blur",
                    )
                )

        return AnalyticsReport(
            video_hash=video_hash,
            video_name=video_path.name,
            video_duration_seconds=video_duration,
            processed_at=datetime.now(),
            pipeline_version="1.0.0",
            config_snapshot={
                "speech_model": config.whisper_model_size,
                "llm_model": config.ollama_model,
                "shorts_max_duration": config.shorts_max_duration_seconds,
                "vad_filter": config.whisper_vad_filter,
            },
            stages=[
                StageMetric(stage=s.stage, duration_seconds=s.duration_seconds, status=s.status)
                for s in state.stages
            ],
            content={
                "seo_title": content_data.get("seo", {}).get("title", ""),
                "seo_description": content_data.get("seo", {}).get("description", ""),
                "chapter_count": len(content_data.get("seo", {}).get("chapters", [])),
            },
            shorts=shorts_metrics,
            thumbnails=thumbs_metrics,
            total_processing_time_seconds=sum(s.duration_seconds for s in state.stages),
            output_directory=output_dir,
        )

    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState):
        self.run(video_path, video_hash, config, state)
        # NOTA: state.stages.append() é responsabilidade do PipelineRunner.
```

---

## 11. PipelineRunner

### 11.1 pipeline/runner.py

```python
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
from typing import Callable
from enum import Enum, auto

from config.settings import Settings
from schemas.state import PipelineState, StageResult
from utils.hash_utils import compute_video_hash
from utils.file_utils import load_json, save_json, ensure_dir
from shared.exceptions import PipelineError

logger = logging.getLogger("pipeline.runner")

StageHandler = Callable[[Path, str, Settings, PipelineState], None]


class PipelineStage(Enum):
    PRE_FLIGHT = auto()
    VIDEO_PROCESSING = auto()
    SPEECH_RECOGNITION = auto()
    TRANSCRIPT_CLEANING = auto()
    CONTENT_INTELLIGENCE = auto()
    TIMELINE_VALIDATION = auto()
    VIDEO_EDIT = auto()
    SUBTITLE_STYLING = auto()
    THUMBNAIL_FRAMES = auto()
    SHORTS_EXTRACTION = auto()
    PACKAGING = auto()

    @classmethod
    def ordered(cls) -> list["PipelineStage"]:
        return [s for s in cls if s != cls.PRE_FLIGHT]


# Etapas mutuamente independentes: nenhuma delas lê a saída das outras
# (todas partem apenas de cleaned.json / metadata.json / content.json,
# já produzidos pelas etapas anteriores). Por isso podem rodar em
# paralelo em vez de sequencialmente — em CPU multi-core (Ryzen 7),
# isso reduz o tempo total do pipeline sem exigir nenhum framework de
# orquestração adicional. São consecutivas na enumeração acima, o que
# simplifica o agrupamento em _build_execution_plan().
PARALLEL_GROUP: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.SUBTITLE_STYLING,
        PipelineStage.THUMBNAIL_FRAMES,
        PipelineStage.SHORTS_EXTRACTION,
    }
)


class PipelineRunner:
    def __init__(self, config: Settings, max_parallel_workers: int = 3):
        self.config = config
        self.max_parallel_workers = max_parallel_workers
        self._stages: dict[PipelineStage, StageHandler] = {}
        self._state_lock = threading.Lock()

    def register(self, stage: PipelineStage, handler: StageHandler) -> None:
        if stage in self._stages:
            raise ValueError(f"Handler já registrado para {stage.name}")
        self._stages[stage] = handler

    def _state_path(self, video_hash: str) -> Path:
        return Path(self.config.cache_dir) / video_hash / "pipeline_state.json"

    def _load_state(self, video_hash: str, video_path: Path) -> PipelineState:
        state_file = self._state_path(video_hash)
        if state_file.exists():
            data = load_json(state_file)
            if data:
                # Conversão explícita mantida por clareza, mas não é mais
                # estritamente necessária: PipelineState não usa
                # strict=True (ver schemas/state.py), então o Pydantic já
                # coage str -> Path / str -> datetime automaticamente ao
                # validar dados vindos de JSON.
                data["video_path"] = Path(data["video_path"])
                return PipelineState(**data)
        return PipelineState(
            video_hash=video_hash,
            video_path=video_path,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    def _save_state(self, state: PipelineState) -> None:
        state.updated_at = datetime.now()
        state_file = self._state_path(state.video_hash)
        ensure_dir(state_file.parent)
        save_json(state_file, state.model_dump(mode="json"))

    @staticmethod
    def _build_execution_plan(stages: list[PipelineStage]) -> list[list[PipelineStage]]:
        """
        Agrupa estágios consecutivos que pertencem ao PARALLEL_GROUP em
        uma única "onda" de execução concorrente. Estágios fora do
        grupo continuam em listas de tamanho 1 (execução sequencial,
        como antes).
        """
        plan: list[list[PipelineStage]] = []
        i = 0
        while i < len(stages):
            stage = stages[i]
            if stage in PARALLEL_GROUP:
                group = []
                while i < len(stages) and stages[i] in PARALLEL_GROUP:
                    group.append(stages[i])
                    i += 1
                plan.append(group)
            else:
                plan.append([stage])
                i += 1
        return plan

    def _run_single_stage(
        self,
        stage: PipelineStage,
        video_path: Path,
        video_hash: str,
        state: PipelineState,
    ) -> StageResult:
        """
        Executa um único estágio e retorna o StageResult correspondente.
        Não levanta exceção — falhas são capturadas e devolvidas dentro
        do próprio StageResult, para que grupos paralelos possam deixar
        os outros membros do grupo terminarem antes de o chamador
        decidir se aborta o pipeline.
        """
        stage_name = stage.name
        handler = self._stages.get(stage)
        if not handler:
            raise PipelineError(f"Handler não registrado para {stage_name}")

        result = StageResult(stage=stage_name, status="success", started_at=datetime.now())
        try:
            logger.info(f"Iniciando etapa: {stage_name}")
            t0 = datetime.now()
            handler(video_path, video_hash, self.config, state)
            t1 = datetime.now()
            result.finished_at = t1
            result.duration_seconds = (t1 - t0).total_seconds()
            logger.info(f"Etapa {stage_name} concluída em {result.duration_seconds:.1f}s")
        except Exception as exc:
            result.status = "failed"
            result.finished_at = datetime.now()
            result.error_message = str(exc)
            logger.error(f"Etapa {stage_name} falhou: {exc}")

        # state.stages.append() e _save_state() são sempre feitos sob
        # lock: em execução paralela, várias threads podem chamar isto
        # ao mesmo tempo, e PipelineState não é thread-safe por si só.
        with self._state_lock:
            state.stages.append(result)
            self._save_state(state)
        return result

    def run(
        self,
        video_path: Path,
        from_stage: PipelineStage | None = None,
        force: bool = False,
    ) -> PipelineState:
        video_hash = compute_video_hash(video_path)
        state = self._load_state(video_hash, video_path)

        if force:
            logger.info("[--force] Cache ignorado. Reprocessando do zero.")
            state.stages = []
            state.completed = False
            state.current_stage = None

        ordered = PipelineStage.ordered()

        start_idx = 0
        if from_stage:
            try:
                start_idx = ordered.index(from_stage)
                logger.info(f"[--from {from_stage.name}] Pulando etapas anteriores.")
            except ValueError:
                raise PipelineError(f"Etapa de partida inválida: {from_stage.name}")

        plan = self._build_execution_plan(ordered[start_idx:])

        for group in plan:
            pending = [
                stage
                for stage in group
                if not (state.is_stage_done(stage.name) and from_stage != stage)
            ]
            if not pending:
                logger.info(f"Etapa(s) {[s.name for s in group]} já concluída(s). Skipping.")
                continue

            state.current_stage = ",".join(s.name for s in pending)
            self._save_state(state)

            if len(pending) == 1:
                # Caminho sequencial normal (idêntico ao comportamento v1.0).
                result = self._run_single_stage(pending[0], video_path, video_hash, state)
                if result.status == "failed":
                    raise PipelineError(f"Falha em {result.stage}: {result.error_message}")
            else:
                # Grupo paralelo: SUBTITLE_STYLING / THUMBNAIL_FRAMES /
                # SHORTS_EXTRACTION rodando ao mesmo tempo em threads.
                logger.info(f"Executando em paralelo: {[s.name for s in pending]}")
                failures: list[StageResult] = []
                with ThreadPoolExecutor(max_workers=self.max_parallel_workers) as executor:
                    futures = {
                        executor.submit(
                            self._run_single_stage, stage, video_path, video_hash, state
                        ): stage
                        for stage in pending
                    }
                    for future in as_completed(futures):
                        result = future.result()
                        if result.status == "failed":
                            failures.append(result)
                if failures:
                    names = ", ".join(f"{r.stage} ({r.error_message})" for r in failures)
                    raise PipelineError(f"Falha em etapa(s) paralela(s): {names}")

        state.current_stage = None
        state.completed = True
        self._save_state(state)
        logger.info("Pipeline concluído com sucesso.")
        return state
```

---

## 12. CLI

### 12.1 main.py

```python
import argparse
import sys
import logging
from pathlib import Path

from config.settings import Settings
from shared.preflight import PreFlightCheck
from shared.exceptions import PreflightError
from shared.logging_config import setup_logging
from pipeline.runner import PipelineRunner, PipelineStage

# Importa todos os agentes
from agents.video_processing.agent import VideoProcessingAgent
from agents.speech_recognition.agent import SpeechRecognitionAgent
from agents.transcript_cleaner.agent import TranscriptCleanerAgent
from agents.content_intelligence.agent import ContentIntelligenceAgent
from agents.timeline_validator.agent import TimelineValidatorAgent
from agents.video_edit.agent import VideoEditAgent
from agents.subtitle_styling.agent import SubtitleStylingAgent
from agents.thumbnail_frames.agent import ThumbnailFramesAgent
from agents.shorts_extractor.agent import ShortsExtractorAgent
from agents.packaging.agent import PackagingAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-video-pipeline",
        description="Pipeline de pós-produção de vídeo com IA (100% local)",
    )
    parser.add_argument(
        "--video",
        "-v",
        type=Path,
        required=True,
        help="Caminho para o arquivo de vídeo de entrada.",
    )
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        default=Path("config/config.yaml"),
        help="Caminho para o arquivo de configuração.",
    )
    parser.add_argument(
        "--from",
        dest="from_stage",
        type=str,
        choices=[s.name.lower() for s in PipelineStage.ordered()],
        default=None,
        help="Reinicia o pipeline a partir de uma etapa específica.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignora cache e reprocessa todas as etapas do zero.",
    )
    parser.add_argument(
        "--output-dir",
        "-o",
        type=Path,
        default=Path("outputs"),
        help="Diretório raiz para saídas finais.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Loga em nível DEBUG.",
    )
    return parser


def build_runner(config: Settings) -> PipelineRunner:
    runner = PipelineRunner(config=config)
    runner.register(PipelineStage.VIDEO_PROCESSING, VideoProcessingAgent().run_stage)
    runner.register(PipelineStage.SPEECH_RECOGNITION, SpeechRecognitionAgent().run_stage)
    runner.register(PipelineStage.TRANSCRIPT_CLEANING, TranscriptCleanerAgent().run_stage)
    runner.register(PipelineStage.CONTENT_INTELLIGENCE, ContentIntelligenceAgent().run_stage)
    runner.register(PipelineStage.TIMELINE_VALIDATION, TimelineValidatorAgent().run_stage)
    runner.register(PipelineStage.VIDEO_EDIT, VideoEditAgent().run_stage)
    runner.register(PipelineStage.SUBTITLE_STYLING, SubtitleStylingAgent().run_stage)
    runner.register(PipelineStage.THUMBNAIL_FRAMES, ThumbnailFramesAgent().run_stage)
    runner.register(PipelineStage.SHORTS_EXTRACTION, ShortsExtractorAgent().run_stage)
    runner.register(PipelineStage.PACKAGING, PackagingAgent().run_stage)
    return runner


def main():
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    setup_logging(log_level)
    logger = logging.getLogger("main")

    # 1. Carrega config
    try:
        config = Settings(_yaml_file=args.config if args.config.exists() else None)
    except Exception as exc:
        print(f"Erro ao carregar configuração: {exc}", file=sys.stderr)
        sys.exit(1)

    # 2. Pre-flight check
    try:
        PreFlightCheck(config).run()
    except PreflightError as exc:
        print(f"[Pre-Flight Check FALHOU] {exc}", file=sys.stderr)
        sys.exit(2)

    # 3. Resolve stage de partida
    from_stage = None
    if args.from_stage:
        from_stage = PipelineStage[args.from_stage.upper()]

    # 4. Executa pipeline
    runner = build_runner(config)

    try:
        state = runner.run(
            video_path=args.video.resolve(),
            from_stage=from_stage,
            force=args.force,
        )
    except Exception as exc:
        print(f"[PIPELINE FALHOU] {exc}", file=sys.stderr)
        sys.exit(3)

    # 5. Relatório final
    video_id = state.video_hash[:12]
    output_dir = Path(config.outputs_dir) / video_id
    print(f"\n✅ Pipeline concluído!")
    print(f"   Hash do vídeo: {state.video_hash}")
    print(f"   Saídas em: {output_dir}")
    print(f"   Tempo total: {sum(s.duration_seconds for s in state.stages):.1f}s")
    for s in state.stages:
        icon = "✅" if s.status == "success" else "❌"
        print(f"   {icon} {s.stage:<30} {s.duration_seconds:>6.1f}s")


if __name__ == "__main__":
    main()
```

### 12.2 Códigos de Saída

| Código | Significado |
|---|---|
| `0` | Sucesso total. |
| `1` | Erro de configuração. |
| `2` | Pre-flight check falhou. |
| `3` | Falha em etapa do pipeline. |

### 12.3 Exemplos de Uso

```bash
# Execução completa
python main.py --video ~/Videos/aula_01.mp4

# Reaproveita cache anterior; reexecuta a partir de Content Intelligence
python main.py --video ~/Videos/aula_01.mp4 --from content_intelligence

# Apenas reempacota
python main.py --video ~/Videos/aula_01.mp4 --from packaging

# Força reprocessamento total
python main.py --video ~/Videos/aula_01.mp4 --force

# Modo verboso
python main.py --video ~/Videos/aula_01.mp4 --verbose
```

---

## 13. Streamlit Dashboard

### 13.1 app/streamlit_app.py

```python
import streamlit as st
import time
from pathlib import Path
from datetime import datetime

from config.settings import Settings
from shared.preflight import PreFlightCheck
from shared.exceptions import PreflightError
from pipeline.runner import PipelineRunner, PipelineStage
from utils.hash_utils import compute_video_hash
from utils.file_utils import load_json

# Importa agentes para registro
from agents.video_processing.agent import VideoProcessingAgent
from agents.speech_recognition.agent import SpeechRecognitionAgent
from agents.transcript_cleaner.agent import TranscriptCleanerAgent
from agents.content_intelligence.agent import ContentIntelligenceAgent
from agents.timeline_validator.agent import TimelineValidatorAgent
from agents.video_edit.agent import VideoEditAgent
from agents.subtitle_styling.agent import SubtitleStylingAgent
from agents.thumbnail_frames.agent import ThumbnailFramesAgent
from agents.shorts_extractor.agent import ShortsExtractorAgent
from agents.packaging.agent import PackagingAgent

st.set_page_config(
    page_title="Pipeline de Pós-Produção com IA",
    layout="wide",
    initial_sidebar_state="expanded",
)


def build_runner(config: Settings) -> PipelineRunner:
    runner = PipelineRunner(config=config)
    runner.register(PipelineStage.VIDEO_PROCESSING, VideoProcessingAgent().run_stage)
    runner.register(PipelineStage.SPEECH_RECOGNITION, SpeechRecognitionAgent().run_stage)
    runner.register(PipelineStage.TRANSCRIPT_CLEANING, TranscriptCleanerAgent().run_stage)
    runner.register(PipelineStage.CONTENT_INTELLIGENCE, ContentIntelligenceAgent().run_stage)
    runner.register(PipelineStage.TIMELINE_VALIDATION, TimelineValidatorAgent().run_stage)
    runner.register(PipelineStage.VIDEO_EDIT, VideoEditAgent().run_stage)
    runner.register(PipelineStage.SUBTITLE_STYLING, SubtitleStylingAgent().run_stage)
    runner.register(PipelineStage.THUMBNAIL_FRAMES, ThumbnailFramesAgent().run_stage)
    runner.register(PipelineStage.SHORTS_EXTRACTION, ShortsExtractorAgent().run_stage)
    runner.register(PipelineStage.PACKAGING, PackagingAgent().run_stage)
    return runner


# ── Sidebar ──
with st.sidebar:
    st.title("⚙️ Configuração")
    model_whisper = st.selectbox(
        "Modelo Whisper",
        ["tiny", "base", "small", "medium"],
        index=2,
        help="Small é o recomendado para GTX 1650 4GB.",
    )
    model_llm = st.selectbox(
        "Modelo LLM",
        ["qwen2.5:3b", "gemma2:2b"],
        index=0,
    )
    shorts_max = st.slider(
        "Duração máxima dos Shorts (s)",
        min_value=15,
        max_value=90,
        value=60,
        step=5,
    )
    st.markdown("---")
    st.info("Upload o vídeo na aba principal para começar.")

# ── Estado da sessão ──
if "pipeline_state" not in st.session_state:
    st.session_state.pipeline_state = None
if "video_hash" not in st.session_state:
    st.session_state.video_hash = None
if "video_path" not in st.session_state:
    st.session_state.video_path = None

# ── Abas ──
tab_upload, tab_progress, tab_results = st.tabs(["📤 Upload", "⏳ Progresso", "📊 Resultados"])

# ── Aba 1: Upload ──
with tab_upload:
    st.header("🎬 Pipeline de Pós-Produção com IA")
    st.markdown("Envie um vídeo para iniciar o processamento completo.")

    uploaded_file = st.file_uploader(
        "Selecione o vídeo",
        type=["mp4", "mov", "mkv", "avi"],
        help="Formatos suportados: MP4, MOV, MKV, AVI. Máx: 2GB.",
    )

    if uploaded_file:
        temp_dir = Path("data/uploads")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / uploaded_file.name
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        st.session_state.video_path = str(temp_path)
        st.success(f"Vídeo salvo: {uploaded_file.name}")

        if st.button("🚀 Iniciar Processamento", type="primary"):
            st.session_state.pipeline_state = "running"
            st.rerun()

# ── Aba 2: Progresso ──
with tab_progress:
    if st.session_state.pipeline_state != "running":
        st.info("Envie um vídeo na aba 'Upload' para começar.")
    else:
        video_path = Path(st.session_state.video_path)
        video_hash = compute_video_hash(video_path)
        st.session_state.video_hash = video_hash

        config = Settings(
            whisper_model_size=model_whisper,
            ollama_model=model_llm,
            shorts_max_duration_seconds=shorts_max,
        )

        # Pre-flight
        with st.status("Verificando ambiente...", expanded=True) as status:
            try:
                PreFlightCheck(config).run()
                status.update(label="✅ Ambiente OK", state="complete")
            except PreflightError as exc:
                status.update(label=f"❌ Falha: {exc}", state="error")
                st.session_state.pipeline_state = "failed"
                st.stop()

        runner = build_runner(config)
        stages = PipelineStage.ordered()
        progress_bar = st.progress(0, text="Iniciando...")
        log_container = st.container()

        total_stages = len(stages)
        for idx, stage in enumerate(stages):
            progress = idx / total_stages
            progress_bar.progress(
                progress, text=f"Executando: {stage.name.replace('_', ' ').title()}..."
            )

            with log_container:
                st.text(f"⏳ {stage.name}...")

            try:
                runner.run(video_path=video_path, from_stage=stage)
                with log_container:
                    st.text(f"✅ {stage.name} concluído.")
            except Exception as exc:
                with log_container:
                    st.error(f"❌ {stage.name} falhou: {exc}")
                st.session_state.pipeline_state = "failed"
                st.stop()

            time.sleep(0.3)

        progress_bar.progress(1.0, text="Concluído!")
        st.session_state.pipeline_state = "done"
        st.success("Processamento finalizado! Veja os resultados na próxima aba.")

# ── Aba 3: Resultados ──
with tab_results:
    video_hash = st.session_state.get("video_hash")
    if not video_hash:
        st.info("Nenhum processamento encontrado nesta sessão.")
        st.stop()

    cache_dir = Path("cache") / video_hash
    output_dir = Path("outputs") / video_hash[:12]

    st.header("📊 Resultados do Processamento")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Hash", video_hash[:16])
    with col2:
        if output_dir.exists():
            st.metric("Saídas em", str(output_dir))

    r_tab_transcript, r_tab_shorts, r_tab_thumbs, r_tab_download = st.tabs(
        ["📝 Transcrição", "✂️ Shorts", "🖼️ Thumbnails", "📦 Download"]
    )

    with r_tab_transcript:
        cleaned_path = cache_dir / "cleaned.json"
        if cleaned_path.exists():
            data = load_json(cleaned_path)
            st.subheader("Texto Limpo")
            st.text_area("Transcrição", value=data.get("full_text_cleaned", ""), height=300)

            srt_path = output_dir / "legendas.srt"
            if srt_path.exists():
                with open(srt_path, "r", encoding="utf-8") as f:
                    st.download_button("⬇️ Baixar SRT", f.read(), file_name="legendas.srt")

            vtt_path = output_dir / "legendas.vtt"
            if vtt_path.exists():
                with open(vtt_path, "r", encoding="utf-8") as f:
                    st.download_button("⬇️ Baixar VTT", f.read(), file_name="legendas.vtt")

    with r_tab_shorts:
        content_path = cache_dir / "timeline.json"
        if content_path.exists():
            data = load_json(content_path)
            shorts = data.get("shorts", [])
            for i, short in enumerate(shorts, 1):
                with st.expander(
                    f"Short #{i} — {short['start']:.0f}s → {short['end']:.0f}s (score: {short['score']:.2f})"
                ):
                    st.write(f"**Motivo:** {short['reason']}")
                    short_file = output_dir / "shorts" / f"short_{i:02d}.mp4"
                    if short_file.exists():
                        st.video(str(short_file))
                    else:
                        st.info("Arquivo de vídeo não disponível.")

    with r_tab_thumbs:
        thumbs_dir = output_dir / "thumbnail_frames"
        if thumbs_dir.exists():
            frames = sorted(thumbs_dir.glob("*.jpg"))
            cols = st.columns(min(len(frames), 4))
            for col, frame in zip(cols, frames):
                col.image(str(frame), use_container_width=True)
        else:
            st.info("Nenhum frame de thumbnail gerado.")

    with r_tab_download:
        analytics_path = output_dir / "analytics.json"
        if analytics_path.exists():
            with open(analytics_path, "r", encoding="utf-8") as f:
                st.json(f.read())

        zip_path = output_dir / f"{video_hash[:12]}_package.zip"
        if zip_path.exists():
            with open(zip_path, "rb") as f:
                st.download_button(
                    label="⬇️ Baixar Pacote Completo (ZIP)",
                    data=f,
                    file_name=zip_path.name,
                    mime="application/zip",
                )
```

---

## 14. Testes

### 14.1 Estrutura de Testes

```
tests/
├── __init__.py
├── conftest.py
├── test_preflight.py
├── test_settings.py
├── test_cache.py
├── test_runner.py
├── test_packaging.py
├── agents/
│   ├── test_video_processing.py
│   ├── test_speech_recognition.py
│   ├── test_transcript_cleaner.py
│   ├── test_content_intelligence.py
│   ├── test_timeline_validator.py
│   ├── test_video_edit.py
│   ├── test_subtitle_styling.py
│   ├── test_thumbnail_frames.py
│   ├── test_shorts_extractor.py
│   └── test_packaging.py
└── fixtures/
    ├── sample_5s.mp4
    └── sample_5s.wav
```

### 14.2 Exemplos de Testes Unitários

**tests/test_preflight.py:**

```python
import pytest
from unittest.mock import patch, MagicMock
from shared.preflight import run_preflight_checks


def test_preflight_passes_with_mocked_tools():
    with patch("subprocess.run") as mock_run, patch("urllib.request.urlopen") as mock_urlopen:
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
```

**tests/test_cache.py:**

```python
import pytest
from pathlib import Path
from utils.hash_utils import compute_video_hash
from utils.file_utils import save_json, load_json


def test_same_file_same_hash(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    h1 = compute_video_hash(f)
    h2 = compute_video_hash(f)
    assert h1 == h2
    assert len(h1) == 16


def test_different_files_different_hash(tmp_path):
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("hello")
    f2.write_text("world")
    assert compute_video_hash(f1) != compute_video_hash(f2)


def test_save_and_load_json(tmp_path):
    path = tmp_path / "data.json"
    data = {"key": "value", "num": 42}
    save_json(path, data)
    loaded = load_json(path)
    assert loaded == data
```

**tests/agents/test_transcript_cleaner.py:**

```python
import pytest
from agents.transcript_cleaner.agent import apply_regex_cleaning


def test_regex_removes_fillers():
    assert (
        apply_regex_cleaning("hum eu acho que ah isso é importante")
        == "eu acho que isso é importante"
    )
    assert apply_regex_cleaning("ahn deixa eu ver") == "deixa eu ver"
    assert apply_regex_cleaning("ãhn não sei") == "não sei"
    assert apply_regex_cleaning("ehm talvez") == "talvez"


def test_regex_preserves_meaningful_words():
    assert apply_regex_cleaning("esse tipo de coisa") == "esse tipo de coisa"
    assert apply_regex_cleaning("você é legal") == "você é legal"
    assert apply_regex_cleaning("né, isso é verdade") == "né, isso é verdade"


def test_empty_after_regex_returns_original():
    assert apply_regex_cleaning("hum ah") == "hum ah"
```

**tests/agents/test_timeline_validator.py:**

```python
import pytest
from agents.timeline_validator.agent import TimelineValidatorAgent
from schemas.content import (
    ContentIntelligenceResult,
    SeoContent,
    ShortCandidate,
    Chapter,
    SummaryContent,
)
from config.settings import Settings


def test_validator_reorders_chapters():
    agent = TimelineValidatorAgent()
    content = ContentIntelligenceResult(
        video_id="test",
        seo=SeoContent(
            title="T",
            description="D",
            hashtags=[],
            chapters=[
                Chapter(timestamp_seconds=120, title="Cap 2"),
                Chapter(timestamp_seconds=30, title="Cap 1"),
            ],
        ),
        shorts=[],
        thumbnail=[],
        summary=SummaryContent(overview="", key_points=[], next_steps=[]),
    )
    config = Settings()
    result = agent.run(content, 200.0, config)
    assert result.seo.chapters[0].timestamp_seconds == 0.0  # Introdução inserida
    assert result.seo.chapters[1].timestamp_seconds == 30.0
    assert result.seo.chapters[2].timestamp_seconds == 120.0


def test_validator_discards_invalid_shorts():
    agent = TimelineValidatorAgent()
    content = ContentIntelligenceResult(
        video_id="test",
        seo=SeoContent(title="T", description="D", hashtags=[], chapters=[]),
        shorts=[
            ShortCandidate(start=10, end=500, reason="muito longo", score=0.5),
            ShortCandidate(start=50, end=65, reason="ok", score=0.9),
        ],
        thumbnail=[],
        summary=SummaryContent(overview="", key_points=[], next_steps=[]),
    )
    config = Settings()
    result = agent.run(content, 100.0, config)
    assert len(result.shorts) == 1
    assert result.shorts[0].start == 50
```

---

## 15. pyproject.toml

```toml
[project]
name = "ai-video-pipeline"
version = "1.0.0"
description = "Pipeline de pós-produção de vídeo com IA (100% local)"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2",
    "pydantic-settings",
    "faster-whisper",
    "opencv-python",
    "streamlit",
    "python-dotenv",
    "sqlalchemy>=2",
    "requests>=2.31",
    "pytest",
    "ruff",
]

[project.optional-dependencies]
dev = [
    "pytest-cov",
    "mypy",
]

[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "N", "UP", "B", "C4", "SIM"]
ignore = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

---

## 16. Checklist Final de Aprovação

### Fundação

- [ ] `config.yaml` único criado com validação Pydantic (flat).
- [ ] Pasta `prompts/` com 3 arquivos `.md`.
- [ ] `PreFlightCheck` verifica FFmpeg, Ollama, modelos, disco, GPU.
- [ ] Cache por hash com atomicidade (write-temp + rename).
- [ ] SQLite usado **apenas** para analytics.
- [ ] Schemas Pydantic v2 para todos os contratos.
- [ ] `schemas/state.py` com `PipelineState` e `StageResult`.
- [ ] `pyproject.toml` inclui `requests>=2.31`.
- [ ] **(v1.1)** Teste de regressão: salvar `PipelineState` → recarregar do
      disco → todos os campos (`Path`, `datetime`, `output_paths`) batem.
- [ ] **(v1.1)** Teste de regressão: `get_video_hash_from_id(generate_video_id(...))`
      retorna exatamente o hash original, para todo agente que dependa disso.
- [ ] **(v1.1)** Teste de regressão: após `PipelineRunner.run()` completo,
      `state.stages` tem exatamente 1 entrada por etapa (não 2).

### Ingestão e Transcrição

- [ ] `VideoProcessingAgent` extrai áudio WAV 16kHz mono via FFmpeg.
- [ ] `SpeechRecognitionAgent` transcreve com `faster-whisper` `small` + VAD.
- [ ] `TranscriptCleanerAgent` aplica regex (lista fechada) + LLM.
- [ ] Regex NUNCA destrói palavras (word boundaries obrigatórios).
- [ ] Testes unitários para regex em português.

### Inteligência e Validação

- [ ] `ContentIntelligenceAgent` recebe segmentos com timestamps.
- [ ] Output JSON: `seo`, `shorts`, `thumbnail` (lista direta), `summary`.
- [ ] `TimelineValidatorAgent` valida duração, timestamps, ordenação.
- [ ] `VideoEditAgent` corta silêncios via FFmpeg (`-c copy` ou reencode).
- [ ] `SubtitleStylingAgent` gera SRT e VTT (max 4 palavras/linha).
- [ ] `ThumbnailFramesAgent` extrai 3–5 frames via OpenCV.
- [ ] Burn-in removido do escopo.

### Orquestração e Interfaces

- [ ] `PipelineRunner` sequencial com registro de handlers.
- [ ] Cada agente expõe `run_stage(video_path, video_hash, config, state)`.
- [ ] Flags `--from` e `--force` na CLI.
- [ ] CLI retorna códigos de saída corretos (0, 1, 2, 3).
- [ ] Streamlit single-page com abas: Upload, Progresso, Resultados.
- [ ] Dashboard exibe transcrição, shorts (com vídeo), thumbnails, download ZIP.
- [ ] `ShortsExtractorAgent` gera `.mp4` individuais.
- [ ] `PackagingAgent` gera `analytics.json`, `report.md` e ZIP.

### Stack

- [ ] Sem `langgraph`, `moviepy`, `ffmpeg-python`, `redis`, `kubernetes`.
- [ ] Ruff configurado (`line-length = 100`).
- [ ] pytest com cobertura mínima de 70% nos módulos críticos.

### Teste de Viabilidade no Hardware

- [ ] Qwen2.5 3B respondendo em < 60s para prompt de 2000 tokens.
- [ ] faster-whisper `small` processando 30 min de áudio em < 5 min na GTX 1650.
- [ ] FFmpeg cortando silêncios de vídeo 1080p sem erro de sync.

---

## 17. Notas para Vibe Coding

1. **Ordem de implementação:** Entrega 1 → 2 → 3 → 4. Não pule etapas.
2. **Prompts externos:** Sempre carregue de `prompts/*.md` em runtime. Nunca deixe prompt hardcoded > 2 linhas.
3. **Subprocess FFmpeg:** Use listas de argumentos, nunca `shell=True`. Capture `stderr`.
4. **Ollama client:** Use HTTP direto (`requests`) via `POST /api/chat`.
5. **Cache atomicidade:** Escreva em arquivo `.tmp` e renomeie (`os.replace`).
6. **Logging:** Use `logging` padrão do Python.
7. **Testes:** Crie fixtures de vídeo curtos (5s) para testar o runner.
8. **Interface unificada:** Todo agente deve implementar `run_stage(video_path, video_hash, config, state)`.
9. **Config flat:** Não aninhe campos no `Settings` Pydantic.
10. **Não redefina exceções:** Importe `PipelineError` de `shared/exceptions`.
11. **Não use MoviePy:** Apenas FFmpeg subprocess e OpenCV.
12. **Não use LangGraph:** PipelineRunner sequencial é suficiente.
13. **VAD obrigatório:** `vad_filter=True` no faster-whisper.
14. **Regex seguro:** Sempre use word boundaries (`\b`) na lista fechada.
15. **Anti-alucinação:** Valide tamanho do texto antes/depois do LLM (50%–200%).

---

*Fim do Documento de Desenvolvimento Completo — Versão 1.1 Consolidada.*
