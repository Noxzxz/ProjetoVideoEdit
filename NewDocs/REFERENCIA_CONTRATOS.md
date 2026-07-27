# Referência Rápida de Contratos — Pipeline de Pós-Produção com IA

> Extraído do **Documento de Desenvolvimento Completo v1.1** + atualizações da Segunda Rodada de Implementação (B8/B9/B11, D10-D15). Apenas schemas (Pydantic) e interfaces (assinaturas de função/método) — sem explicações, prompts ou Epics. Consulta rápida durante implementação/revisão de código.

---

## 1. Enums — Estágios do Pipeline (`pipeline/runner.py`)

```python
class PipelineStage(Enum):
    PRE_FLIGHT = auto()
    VIDEO_PROCESSING = auto()
    SPEECH_RECOGNITION = auto()
    MARKER_DETECTION = auto()          # D14 — novo estágio para marcadores "corte"/"início"
    TRANSCRIPT_CLEANING = auto()
    CONTENT_INTELLIGENCE = auto()
    TIMELINE_VALIDATION = auto()
    VIDEO_EDIT = auto()
    SUBTITLE_STYLING = auto()
    THUMBNAIL_FRAMES = auto()
    SHORTS_EXTRACTION = auto()
    PACKAGING = auto()

# Rodam em paralelo via ThreadPoolExecutor (mutuamente independentes):
PARALLEL_GROUP = frozenset({
    PipelineStage.SUBTITLE_STYLING,
    PipelineStage.THUMBNAIL_FRAMES,
    PipelineStage.SHORTS_EXTRACTION,
})
```

## 2. Marcadores (`schemas/marker.py`) — D14

```python
class MarkerPair(BaseModel):               # strict=True
    start: float                            # timestamp do marcador "corte"
    end: float                              # timestamp do marcador "volta"
    cut_word: str = "corte"
    resume_word: str = "início"
```

Usado por `VideoEditAgent.build_cut_list()` para consumir pares e trimmá-los das bordas dos intervalos VAD.

---

## 3. Shorts (`schemas/shorts.py`) — D12

```python
class ShortCandidate(BaseModel):            # strict=True
    start: float
    end: float
    reason: str
    score: float = Field(ge=0, le=1)
    hook_strength: float = Field(default=0.0, ge=0, le=1)   # D12 — força do gancho inicial
```

---

## 4. Vídeo (`schemas/video.py`)

```python
class VideoMetadata(BaseModel):          # strict=True
    duration_seconds: float
    fps: float
    width: int
    height: int
    codec: str
    has_audio_track: bool

class VideoIngestResult(BaseModel):      # strict=True
    video_id: str
    original_path: str
    audio_path: str
    metadata: VideoMetadata
```

## 3. Transcrição (`schemas/transcript.py`)

```python
class TranscriptSegment(BaseModel):      # strict=True
    id: int
    start: float
    end: float
    text: str
    confidence: float = Field(ge=0, le=1)

class TranscriptRaw(BaseModel):          # strict=True
    video_id: str
    language: str
    segments: list[TranscriptSegment]
    full_text: str = ""                  # computado via @model_validator(mode="after")

class TranscriptCleaned(BaseModel):      # strict=True
    video_id: str
    segments: list[TranscriptSegment]
    full_text_cleaned: str
```

## 4. Content Intelligence (`schemas/content.py`)

```python
class Chapter(BaseModel):                # strict=True
    timestamp_seconds: float
    title: str = Field(max_length=60)

class ShortCandidate(BaseModel):         # strict=True
    start: float
    end: float
    reason: str
    score: float = Field(ge=0, le=1)
    hook_strength: float = Field(default=0.0, ge=0, le=1)  # D12

class ThumbnailPromptItem(BaseModel):    # strict=True
    prompt_pt: str
    prompt_en: str
    mood: str

class SeoContent(BaseModel):             # strict=True
    title: str = Field(max_length=100)
    description: str
    hashtags: list[str]
    chapters: list[Chapter]

class SummaryContent(BaseModel):         # strict=True
    overview: str
    key_points: list[str]
    next_steps: list[str]

class ContentIntelligenceResult(BaseModel):  # strict=True
    video_id: str
    seo: SeoContent
    shorts: list[ShortCandidate]
    thumbnail: list[ThumbnailPromptItem]
    summary: SummaryContent
```

## 5. Edição (`schemas/edit.py`)

```python
class CutInstruction(BaseModel):         # strict=True
    start: float
    end: float

class CutList(BaseModel):                # strict=True
    video_id: str
    segments_to_keep: list[CutInstruction]
    total_duration_kept: float

class EditResult(BaseModel):             # strict=True
    video_id: str
    output_path: str
    cut_list: CutList
```

## 6. Legendas (`schemas/subtitle.py`)

```python
class SubtitleStyle(BaseModel):          # strict=True
    max_words_per_line: int = 4
    font_size: int = 48

class SubtitleResult(BaseModel):         # strict=True
    video_id: str
    srt_path: str
    vtt_path: str
```

## 7. Analytics (`schemas/analytics.py`)

```python
class StageMetric(BaseModel):            # strict=True
    stage: str
    duration_seconds: float
    status: Literal["success", "skipped", "failed"]

class ShortMetric(BaseModel):            # strict=True
    start: float
    end: float
    duration_seconds: float
    score: float
    reason: str
    file_name: str | None = None

class ThumbnailMetric(BaseModel):        # strict=True
    file_name: str
    sharpness_score: float
    selected_reason: str

class AnalyticsReport(BaseModel):        # strict=True
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

## 8. Estado do Pipeline (`schemas/state.py`)

> ⚠️ **Únicos dois schemas SEM `strict=True`** — persistidos em `cache/<hash>/pipeline_state.json` e recarregados a cada execução (suporte a `--from`/resume). `strict=True` quebraria a coerção `str→Path`/`str→datetime` que o JSON força no round-trip disco→objeto.

```python
class StageResult(BaseModel):            # NÃO strict
    stage: str
    status: Literal["success", "skipped", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    output_paths: list[Path] = Field(default_factory=list)
    error_message: str | None = None

class PipelineState(BaseModel):          # NÃO strict
    video_hash: str
    video_path: Path
    created_at: datetime
    updated_at: datetime
    stages: list[StageResult] = Field(default_factory=list)
    current_stage: str | None = None
    completed: bool = False

    def last_successful_stage(self) -> str | None: ...
    def is_stage_done(self, stage_name: str) -> bool: ...
```

---

## 9. Configuração (`config/settings.py`)

```python
class Settings(BaseSettings):
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
    shorts_target_count: int = 4               # D12 — alvo de shorts por capítulo
    shorts_min_spacing_seconds: float = 20.0   # D12 — espaçamento mínimo entre shorts

    # Edição
    silence_threshold_db: float = -35.0
    min_gap_seconds: float = 0.6
    silence_pre_padding_ms: int = 100          # D13 — padding antes de silêncio
    silence_post_padding_ms: int = 150         # D13 — padding depois de silêncio
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_preset: str = "fast"

    # Marcadores (D14)
    marker_cut_word: str = "corte"
    marker_resume_word: str = "início"

    # LLM Provider (D10)
    llm_provider: Literal["ollama", "gemini", "groq"] = "ollama"

    # Groq (D10)
    groq_api_key: str = ""
    groq_model: str = "mixtral-8x7b-32768"

    # Gemini (D10)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Legendas
    max_words_per_line: int = 4

settings = Settings()   # instância pronta para uso
```

**Regra de ouro:** `Settings` é **flat** — nunca aninhar campos.

---

## 10. Exceções (`shared/exceptions.py`)

```python
class PipelineError(Exception): ...              # base — nunca redefinir em outro módulo

class VideoNotFoundError(PipelineError): ...       # arquivo de vídeo ausente/inacessível
class AudioExtractionError(PipelineError): ...     # falha ao extrair áudio via FFmpeg
class TranscriptionError(PipelineError): ...       # falha na transcrição Whisper
class CleaningError(PipelineError): ...            # falha na limpeza de transcrição
class ContentGenerationError(PipelineError): ...   # falha no Content Intelligence
class TimelineValidationError(PipelineError): ...  # falha na validação de timeline
class EditingError(PipelineError): ...             # falha na edição de vídeo
class ExportError(PipelineError): ...              # falha na exportação de artefatos
class ExternalServiceError(PipelineError): ...     # Ollama/FFmpeg indisponível ou erro
class PreflightError(PipelineError): ...           # ambiente inadequado no Pre-flight Check
```

---

## 11. Interface Comum de Agente

Todo agente implementa **dois métodos**: `run()` (lógica de domínio pura/testável) e `run_stage()` (adapter que integra com cache/estado — chamado pelo `PipelineRunner`). `run_stage()` **nunca** faz `state.stages.append(...)` — isso é responsabilidade exclusiva do `PipelineRunner`.

```python
def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState) -> None: ...
```

### 11.1 `VideoProcessingAgent` — `agents/video_processing/agent.py`
```python
class VideoProcessingAgent:
    def run(self, video_path: str) -> VideoIngestResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.2 `SpeechRecognitionAgent` — `agents/speech_recognition/agent.py`
```python
class SpeechRecognitionAgent:
    def run(self, video_id: str, audio_path: str) -> TranscriptRaw: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.3 `TranscriptCleanerAgent` — `agents/transcript_cleaner/agent.py`
```python
def apply_regex_cleaning(text: str) -> str: ...   # função pura de módulo, lista fechada + \b

class TranscriptCleanerAgent:
    def run(self, transcript: TranscriptRaw) -> TranscriptCleaned: ...   # batches de 15 segmentos/chamada (valor real confirmado em RELATORIO_IMPLEMENTACAO.md)
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.4 `MarkerDetectionAgent` — `agents/marker_detection/agent.py` — D14
```python
class MarkerDetectionAgent:
    def run(self, transcript: TranscriptCleaned, config: Settings) -> list[MarkerPair]: ...
    # Detecta palavras de corte/reinício (cut_word/resume_word) nos segmentos de transcrição
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.5 `ContentIntelligenceAgent` — `agents/content_intelligence/agent.py`
```python
class ContentIntelligenceAgent:
    def _format_transcript(self, transcript_data: dict, max_segments: int = 400) -> str: ...
    # D12 — 2 fases: 1 = SEO+chapters+summary+thumbnail, 2 = shorts por capítulo
    def run(self, transcript: dict, video_duration_seconds: float, config: Settings) -> ContentIntelligenceResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.6 `TimelineValidatorAgent` — `agents/timeline_validator/agent.py`
```python
class TimelineValidatorAgent:
    def run(
        self,
        content: ContentIntelligenceResult,
        video_duration_seconds: float,
        config: Settings,
        transcript: dict | None = None,             # D12 — para snap-to-phrase boundary
    ) -> ContentIntelligenceResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.7 `VideoEditAgent` — `agents/video_edit/agent.py`
```python
def build_cut_list(
    video: dict,
    transcript: dict,
    config: Settings,
    marker_pairs: list[MarkerPair] | None = None,   # D14 — trimm de marcadores
) -> CutList: ...
# build_cut_list aplica silence_pre_padding_ms/silence_post_padding_ms nos intervalos VAD
# e remove intervalos sobrepostos com marker_pairs

class VideoEditAgent:
    def run(self, video_ingest: dict, transcript: dict, config: Settings) -> EditResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.8 `SubtitleStylingAgent` — `agents/subtitle_styling/agent.py`
```python
def split_into_caption_chunks(...) -> list[TranscriptSegment]: ...  # função pura de módulo
def to_srt(chunks: list[TranscriptSegment]) -> str: ...
def to_vtt(chunks: list[TranscriptSegment]) -> str: ...

class SubtitleStylingAgent:
    def run(self, video_id: str, transcript: TranscriptCleaned, config: Settings) -> SubtitleResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.9 `ThumbnailFramesAgent` — `agents/thumbnail_frames/agent.py`
```python
class ThumbnailFramesAgent:
    def run(self, video_id: str, original_video_path: str, config: Settings) -> list[Path]: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.10 `ShortsExtractorAgent` — `agents/shorts_extractor/agent.py`
```python
class ShortsExtractorAgent:
    def run(
        self,
        video_path: Path,
        content: ContentIntelligenceResult,
        output_dir: Path,
        config: Settings,
    ) -> list[Path]: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

### 11.11 `PackagingAgent` — `agents/packaging/agent.py`
```python
class PackagingAgent:
    def run(
        self,
        video_path: Path,
        video_hash: str,
        config: Settings,
        state: PipelineState,
    ) -> AnalyticsReport: ...
    def _copy_if_exists(self, src: Path, dst: Path) -> None: ...
    def _generate_report(self, state: PipelineState, output_dir: Path, video_id: str) -> None: ...
    def _build_analytics(...) -> AnalyticsReport: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings, state: PipelineState): ...
```

---

## 12. Serviços de Infraestrutura

### 12.1 `services/ffmpeg_service.py`
```python
def get_video_metadata(video_path: Path) -> VideoMetadata: ...
def extract_audio(video_path: Path, output_path: Path) -> Path: ...
def get_video_duration(video_path: Path) -> float: ...
def apply_cut_list(video_path: Path, cut_list: CutList, output_path: Path) -> Path: ...
def extract_segment(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    output_path: Path,
    config: Settings,
) -> Path: ...
```

### 12.2 `services/whisper_service.py`
```python
def transcribe(audio_path: Path, video_id: str) -> TranscriptRaw: ...
def unload_whisper_model() -> None: ...   # libera VRAM — chamado ao fim de SPEECH_RECOGNITION
```

### 12.3 `services/ollama_service.py`
```python
def generate(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    json_mode: bool = False,
    timeout: int = 120,
) -> str: ...
```

### 12.3.1 `services/llm_provider.py` — abstração confirmada em implementação real (D10)

> Substitui o acesso direto a `services/ollama_service.generate()` nos agentes — nenhum agente deve chamar um provedor de LLM diretamente.

```python
class LLMProvider(ABC):
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str: ...

class OllamaProvider(LLMProvider): ...   # HTTP para http://localhost:11434/api/chat
class GeminiProvider(LLMProvider): ...   # HTTP para API Google Gemini
class GroqProvider(LLMProvider): ...     # HTTP compatível OpenAI, retry automático em HTTP 429

def get_provider() -> LLMProvider: ...   # factory; lê settings.llm_provider; cacheia a instância
```

### 12.3.2 Importação de Transcrição Externa — confirmado em implementação real (D11)

```python
# CLI: --transcript <path> | --srt <path> | --vtt <path>

class PipelineRunner:
    def _import_transcript(self, path: Path, video_hash: str) -> None: ...
    # parseia SRT/VTT/JSON -> cache/<hash>/transcript.json
    # gera metadata.json mínimo (duração inferida dos timestamps — NÃO é metadata completo de vídeo)
    # marca VIDEO_PROCESSING + SPEECH_RECOGNITION como concluídos
    # ajusta current_stage = TRANSCRIPT_CLEANING
```

### 12.4 `services/transcript_import.py` — D11
```python
def parse_srt(path: Path) -> TranscriptRaw: ...
def parse_vtt(path: Path) -> TranscriptRaw: ...
def parse_json(path: Path) -> TranscriptRaw: ...
```

---

### 12.5 `services/opencv_service.py`
```python
def extract_candidate_frames(
    video_path: Path,
    output_dir: Path,
    max_frames: int = 5,
    min_spacing_percent: float = 5.0,
) -> list[Path]: ...
```

---

## 13. Cache, Hash e Utilitários (`utils/`)

```python
# utils/hash_utils.py
def compute_video_hash(video_path: Path) -> str: ...
def get_cache_dir(video_hash: str) -> Path: ...
def get_video_hash_from_id(video_id: str) -> str: ...   # ÚNICA fonte de verdade do hash — usar sempre, nunca reimplementar

# utils/file_utils.py
def ensure_dir(path: Path) -> Path: ...
def load_json(path: Path) -> dict | None: ...
def save_json(path: Path, data: dict) -> None: ...       # atomicidade: escreve .tmp + os.replace()

# utils/time_utils.py
def seconds_to_hms(seconds: float) -> str: ...
def seconds_to_srt_timestamp(seconds: float) -> str: ...
def seconds_to_vtt_timestamp(seconds: float) -> str: ...
def hms_to_seconds(hms: str) -> float: ...

# utils/slugify.py
def slugify_filename(filename: str) -> str: ...
def generate_video_id(filename: str, video_hash: str) -> str: ...
```

**Estrutura de cache em disco:**
```
cache/<video_hash>/
├── metadata.json
├── transcript.json
├── markers.json                        # D14 — pares de marcador detectados
├── cleaned.json          (+ cleaned.partial.json durante processamento em lote)
├── content.json
├── timeline.json
├── shorts.json
└── pipeline_state.json
```

---

## 14. Pre-flight Check (`shared/preflight.py`)

```python
def run_preflight_checks() -> list[str]: ...   # retorna lista de problemas encontrados (vazia = OK)

class PreFlightCheck:
    def __init__(self, config: Settings): ...
    def run(self) -> None: ...                  # levanta PreflightError se ambiente inadequado
```

---

## 15. Persistência — Analytics/Histórico (`shared/db/`)

```python
# shared/db/database.py
class PipelineRun(Base): ...       # ORM: id, video_hash, video_name, status, started_at, finished_at, ...
class AgentMetric(Base): ...       # ORM: id, run_id (FK), agent_name, duration_seconds, status, ...
def init_db() -> None: ...

# shared/db/repositories.py
class AnalyticsRepository:
    def create_run(self, video_hash: str, video_name: str) -> int: ...
    def mark_run_done(self, run_id: int, total_duration: float) -> None: ...
    def mark_run_failed(self, run_id: int, error: str) -> None: ...
    def log_metric(self, ...) -> None: ...
    def get_run_history(self, limit: int = 20) -> list[PipelineRun]: ...
```

> SQLite é usado **apenas** para histórico/analytics — nunca como fonte de verdade do progresso do pipeline (isso é papel do `PipelineState` em cache JSON).

---

## 16. Orquestração (`pipeline/runner.py`)

```python
StageHandler = Callable[[Path, str, Settings, PipelineState], None]

class PipelineStage(Enum):
    PRE_FLIGHT = auto()
    VIDEO_PROCESSING = auto()
    SPEECH_RECOGNITION = auto()
    MARKER_DETECTION = auto()            # D14
    TRANSCRIPT_CLEANING = auto()
    CONTENT_INTELLIGENCE = auto()
    TIMELINE_VALIDATION = auto()
    VIDEO_EDIT = auto()
    SUBTITLE_STYLING = auto()
    THUMBNAIL_FRAMES = auto()
    SHORTS_EXTRACTION = auto()
    PACKAGING = auto()

    @classmethod
    def ordered(cls) -> list["PipelineStage"]: ...   # todas exceto PRE_FLIGHT

# Rodam em paralelo via ThreadPoolExecutor (mutuamente independentes):
PARALLEL_GROUP: frozenset[PipelineStage] = frozenset({
    PipelineStage.SUBTITLE_STYLING,
    PipelineStage.THUMBNAIL_FRAMES,
    PipelineStage.SHORTS_EXTRACTION,
})

class PipelineRunner:
    def __init__(self, config: Settings, max_parallel_workers: int = 3): ...
    # registro de StageResult em state.stages é responsabilidade EXCLUSIVA desta classe
    # B8: armazenamento de futures usa stage.name (string), não valor bruto do enum
    # B9: state.completed = True é definido antes do estágio PACKAGING, não após o loop
    def _import_transcript(self, path: Path, video_hash: str) -> None: ...   # D11
```

---

## 17. Prompts Externos (`prompts/*.md`)

| Arquivo | Usado por |
|---|---|
| `prompts/cleaning_llm.md` | `TranscriptCleanerAgent` |
| `prompts/content_intelligence.md` | `ContentIntelligenceAgent` (fase 1 = SEO+chapters+summary+thumbnail) |
| `prompts/shorts_prompt.md` | `ContentIntelligenceAgent` (fase 2 = shorts por capítulo) — D12 |
| `prompts/thumbnail_prompt.md` | `ContentIntelligenceAgent` (seção de thumbnail) |

Regra: nenhum prompt hardcoded no código com mais de 2 linhas — sempre carregado desses arquivos em runtime.

---

## 18. Regras Fixas (não-negociáveis, independente do módulo)

- `run_stage()` de agente **nunca** chama `state.stages.append(...)` — só o `PipelineRunner` faz isso.
- Hash de vídeo: **sempre** via `get_video_hash_from_id()` / `compute_video_hash()` de `utils/hash_utils.py` — nunca reimplementar em outro módulo.
- `PipelineState`/`StageResult`: sem `strict=True`. Todos os demais schemas: com `strict=True`.
- Parsing de FPS: `fractions.Fraction`, nunca `eval()`.
- Regex de limpeza: lista fechada (`hum`, `ah`, `ahn`, `ãhn`, `ehm`) com `\b`, nunca `é`/`tipo`/`né` (esses só via LLM, com contexto).
- `TranscriptCleanerAgent`: batches de 15 segmentos por chamada LLM, nunca 1 por segmento.
- `TranscriptSegment.confidence` deve ser repassado do segmento original em TODOS os caminhos de saída do cleaner (regex e LLM), não só no fallback.
- Registro de estágio (sequencial ou paralelo, incl. dentro de `ThreadPoolExecutor`): sempre `PipelineStage(x).name`, nunca o valor bruto do enum.
- Chamada a provedor de LLM: sempre via `LLMProvider`/`get_provider()` — nunca requisição direta a uma API específica dentro de um agente. (D10)
- VAD: `whisper_vad_filter=True` sempre — não exposto como opção desabilitável na V1.
- Cache: escrita atômica (`.tmp` + `os.replace()`).
- Sem `langgraph`, `moviepy`, `ffmpeg-python`, `redis`, `kubernetes` no `pyproject.toml`.
- Subprocess do FFmpeg: sempre lista de argumentos, nunca `shell=True`.
- Transcrição externa: via `--transcript`/`--srt`/`--vtt` na CLI, parseada por `services/transcript_import.py`, marca `VIDEO_PROCESSING` + `SPEECH_RECOGNITION` como concluídos. (D11)
- Shorts por capítulo: gerados na fase 2 do `ContentIntelligenceAgent` (1 chamada LLM/capítulo), com `hook_strength` e espaçamento mínimo validado pelo `TimelineValidatorAgent`. (D12)
- Silêncio: padding `silence_pre_padding_ms`/`silence_post_padding_ms` aplicado em `build_cut_list()` ao redor de intervalos VAD. (D13)
- Marcadores: `MarkerDetectionAgent` detecta palavras de corte/retorno no transcript; `marker_pairs` são consumidos por `build_cut_list()` para trimm. (D14)
- Laplacian threshold para thumbnails: 50 (não 100) — evita rejeição excessiva de quadros válidos. (B11/D15)
- `state.completed`: definido como `True` antes de executar o estágio `PACKAGING`, não após o loop de estágios. (B9)

---

*Fim da Referência Rápida de Contratos.*
