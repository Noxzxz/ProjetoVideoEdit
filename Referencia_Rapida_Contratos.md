# Referência Rápida de Contratos — Pipeline de Pós-Produção com IA

> Extraído do **Documento de Desenvolvimento Completo v1.1** + decisões WoD (D16-D30). Apenas schemas (Pydantic) e interfaces (assinaturas de função/método) — sem explicações, prompts ou Epics. Consulta rápida durante implementação/revisão de código.

---

## 1. Enums (`schemas/enums.py`)

```python
class JobStatusEnum(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class AgentNameEnum(str, Enum):
    VIDEO_PROCESSING = "VIDEO_PROCESSING"
    SPEECH_RECOGNITION = "SPEECH_RECOGNITION"
    MARKER_DETECTION = "MARKER_DETECTION"
    TRANSCRIPT_CLEANER = "TRANSCRIPT_CLEANER"
    CONTENT_INTELLIGENCE = "CONTENT_INTELLIGENCE"
    TIMELINE_VALIDATOR = "TIMELINE_VALIDATOR"
    VIDEO_EDIT = "VIDEO_EDIT"
    SUBTITLE_STYLING = "SUBTITLE_STYLING"
    SHORTS_EXTRACTION = "SHORTS_EXTRACTION"
    PACKAGING = "PACKAGING"
```

> `THUMBNAIL_FRAMES` foi **removido** (D16 — conteúdo *audio-first*). Não reintroduzir.

## 2. Vídeo (`schemas/video.py`)

```python
class VideoMetadata(BaseModel):  # strict=True
    duration_seconds: float
    fps: float
    width: int
    height: int
    codec: str
    has_audio_track: bool


class VideoIngestResult(BaseModel):  # strict=True
    video_id: str
    original_path: str
    audio_path: str
    metadata: VideoMetadata
```

## 3. Transcrição (`schemas/transcript.py`)

```python
class TranscriptSegment(BaseModel):  # strict=True
    id: int
    start: float
    end: float
    text: str
    confidence: float = Field(ge=0, le=1)


class TranscriptRaw(BaseModel):  # strict=True
    video_id: str
    language: str
    segments: list[TranscriptSegment]
    full_text: str = ""  # computado via @model_validator(mode="after")


class TranscriptCleaned(BaseModel):  # strict=True
    video_id: str
    segments: list[TranscriptSegment]
    full_text_cleaned: str
```

## 4. Marcadores (`schemas/marker.py`)

```python
class MarkerPair(BaseModel):  # strict=True
    start: float
    end: float
    cut_word: str
    resume_word: str
    kind: Literal["erro_fala", "ooc"] = "erro_fala"
```

> `kind="ooc"` (D25) identifica trechos fora de personagem — excluídos do corte físico **e** da curadoria de shorts. Os dois pares (`erro_fala`/`ooc`) têm palavras-chave distintas e configuráveis; nunca misturar a lógica.

## 5. Content Intelligence (`schemas/content.py`)

```python
class Chapter(BaseModel):  # strict=True
    timestamp_seconds: float
    title: str = Field(max_length=60)


class ShortCandidate(BaseModel):  # strict=True
    start: float
    end: float
    reason: str
    score: float = Field(default=0.5, ge=0, le=1)
    hook_strength: float = Field(default=0.5, ge=0, le=1)   # D18
    gancho: str = ""                                          # D18 (texto literal da transcrição)
    payoff: str = ""                                          # D18
    emocao: str = ""                                          # D18
    standalone_score: float = Field(default=0.5, ge=0, le=1)  # D19
    standalone_notes: str = ""                                # D19


class SeoContent(BaseModel):  # strict=True
    title: str = Field(max_length=100)
    description: str
    hashtags: list[str]
    chapters: list[Chapter]


class SummaryContent(BaseModel):  # strict=True
    overview: str
    key_points: list[str]
    next_steps: list[str]


class ContentIntelligenceResult(BaseModel):  # strict=True
    video_id: str
    seo: SeoContent
    shorts: list[ShortCandidate]
    thumbnail_suggestions: list[str] = Field(default_factory=list)  # textual desde D16
    summary: SummaryContent
```

## 6. Edição (`schemas/edit.py`)

```python
class CutInstruction(BaseModel):  # strict=True
    start: float
    end: float


class CutList(BaseModel):  # strict=True
    video_id: str
    segments_to_keep: list[CutInstruction]
    total_duration_kept: float


class EditResult(BaseModel):  # strict=True
    video_id: str
    output_path: str
    cut_list: CutList
```

## 7. Legendas (`schemas/subtitle.py`)

```python
class SubtitleStyle(BaseModel):  # strict=True
    max_words_per_line: int = 4
    font_size: int = 48


class SubtitleResult(BaseModel):  # strict=True
    video_id: str
    srt_path: str
    vtt_path: str
```

## 8. Analytics (`schemas/analytics.py`)

```python
class StageMetric(BaseModel):  # strict=True
    stage: str
    duration_seconds: float
    status: Literal["success", "skipped", "failed"]


class ShortMetric(BaseModel):  # strict=True
    start: float
    end: float
    duration_seconds: float
    score: float
    reason: str
    file_name: str | None = None


class ThumbnailMetric(BaseModel):  # strict=True  (legado — não populado desde D16)
    file_name: str
    sharpness_score: float
    selected_reason: str


class AnalyticsReport(BaseModel):  # strict=True
    video_hash: str
    video_name: str
    video_duration_seconds: float  # vem do metadata.json (B15)
    processed_at: datetime
    pipeline_version: str = "1.0.0"
    config_snapshot: dict  # sanitizado: sem chaves com "key"/"token" no nome (B15)
    stages: list[StageMetric]
    transcript_stats: dict = Field(default_factory=dict)
    content: dict = Field(default_factory=dict)
    shorts: list[ShortMetric] = Field(default_factory=list)
    thumbnails: list[ThumbnailMetric] = Field(default_factory=list)
    total_processing_time_seconds: float
    output_directory: Path
```

## 9. Estado do Pipeline (`schemas/state.py`)

> ⚠️ **Únicos dois schemas SEM `strict=True`** — persistidos em `cache/<hash>/pipeline_state.json` e recarregados a cada execução (suporte a `--from`/resume). `strict=True` quebraria a coerção `str→Path`/`str→datetime` que o JSON força no round-trip disco→objeto.

```python
class StageResult(BaseModel):  # NÃO strict
    stage: str
    status: Literal["success", "skipped", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float = 0.0
    output_paths: list[Path] = Field(default_factory=list)
    error_message: str | None = None


class PipelineState(BaseModel):  # NÃO strict
    video_hash: str
    video_path: Path
    created_at: datetime
    updated_at: datetime
    stages: list[StageResult] = Field(default_factory=list)
    current_stage: str | None = None
    completed: bool = False
    stage_fingerprints: dict[str, str] = Field(default_factory=dict)  # D27

    def last_successful_stage(self) -> str | None: ...
    def is_stage_done(self, stage_name: str) -> bool: ...
```

---

## 10. Configuração (`config/settings.py`)

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Diretórios
    data_dir: str = "data"
    outputs_dir: str = "outputs"
    cache_dir: str = "cache"
    logs_dir: str = "logs"
    prompts_dir: str = "prompts"
    glossaries_dir: str = "glossaries"

    # Whisper
    whisper_model_size: Literal["tiny", "base", "small", "medium", "large-v3"] = "small"
    whisper_device: Literal["cuda", "cpu"] = "cuda"
    whisper_vad_filter: bool = True
    whisper_vad_threshold: float = 0.5
    whisper_initial_prompt: str = ""  # hotwords; vazio = usa o glossário (D20)

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    ollama_temperature: float = 0.2

    # Provedor LLM
    llm_provider: Literal["ollama", "gemini", "groq"] = "ollama"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    # LLM geral (D29)
    llm_call_delay_seconds: float = 3.0
    llm_max_retries: int = 3
    llm_retry_backoff_seconds: float = 2.0

    # Shorts
    shorts_max_duration_seconds: int = 60
    shorts_min_duration_seconds: int = 15
    shorts_target_count: int = 4
    shorts_min_spacing_seconds: float = 30.0
    shorts_min_standalone_score: float = 0.5  # D19

    # Edição / silêncio
    silence_threshold_db: float = -35.0
    min_gap_seconds: float = 0.6
    silence_pre_padding_ms: int = 100
    silence_post_padding_ms: int = 150

    # Marcadores de fala (D14) e OOC (D25)
    marker_cut_word: str = "corte"
    marker_resume_word: str = "inicio"
    ooc_pause_word: str = "pausa"
    ooc_resume_word: str = "retomando"

    # Nicho WoD
    glossary_name: str = ""        # D20
    campaign_context_file: str = ""  # D23
    hashtags_file: str = ""        # D24
    content_type: Literal["sessao", "mecanica", "lore", "podcast"] = "sessao"  # D22

    # Codecs
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    video_preset: str = "fast"

    # Legendas
    max_words_per_line: int = 4


settings = Settings()  # singleton — usado apenas como fallback (D28); no pipeline, o config é injetado
```

**Regra de ouro:** `Settings` é **flat** — nunca aninhar campos.

---

## 11. Exceções (`shared/exceptions.py`)

```python
class PipelineError(Exception): ...  # base — nunca redefinir em outro módulo


class VideoNotFoundError(PipelineError): ...  # arquivo de vídeo ausente/inacessível
class AudioExtractionError(PipelineError): ...  # falha ao extrair áudio via FFmpeg
class TranscriptionError(PipelineError): ...  # falha na transcrição Whisper
class CleaningError(PipelineError): ...  # falha na limpeza de transcrição
class ContentGenerationError(PipelineError): ...  # falha no Content Intelligence
class TimelineValidationError(PipelineError): ...  # falha na validação de timeline
class EditingError(PipelineError): ...  # falha na edição de vídeo
class ExportError(PipelineError): ...  # falha na exportação de artefatos
class ExternalServiceError(PipelineError): ...  # Ollama/FFmpeg indisponível ou erro
class PreflightError(PipelineError): ...  # ambiente inadequado no Pre-flight Check
```

---

## 12. Interface Comum de Agente

Todo agente implementa **dois métodos**: `run()` (lógica de domínio pura/testável) e `run_stage()` (adapter que integra com cache — chamado pelo `PipelineRunner`). Desde o **D30**, `run_stage` recebe apenas `(video_path, video_hash, config)` — **sem `state`**. Quem precisar do estado lê o arquivo persistido (`cache/<hash>/pipeline_state.json`).

```python
def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.1 `VideoProcessingAgent` — `agents/video_processing/agent.py`
```python
class VideoProcessingAgent:
    def run(self, video_path: str, video_hash: str | None = None) -> VideoIngestResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.2 `SpeechRecognitionAgent` — `agents/speech_recognition/agent.py`
```python
class SpeechRecognitionAgent:
    def run(self, video_id: str, audio_path: str, config: Settings | None = None) -> TranscriptRaw: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.3 `MarkerDetectionAgent` — `agents/marker_detection/agent.py`
```python
def detect_markers(
    transcript: TranscriptRaw,
    cut_word: str,
    resume_word: str,
    ooc_pause_word: str | None = None,
    ooc_resume_word: str | None = None,
) -> list[MarkerPair]: ...  # função pura de módulo

class MarkerDetectionAgent:
    def run(self, transcript: TranscriptRaw, config: Settings) -> list[MarkerPair]: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.4 `TranscriptCleanerAgent` — `agents/transcript_cleaner/agent.py`
```python
def apply_regex_cleaning(text: str) -> str: ...  # função pura de módulo, lista fechada + \b

class TranscriptCleanerAgent:
    def run(self, transcript: TranscriptRaw, config: Settings | None = None) -> TranscriptCleaned: ...
    # batches LLM + correção de glossário (D20)
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.5 `ContentIntelligenceAgent` — `agents/content_intelligence/agent.py`
```python
class ContentIntelligenceAgent:
    def run(
        self,
        transcript: dict,
        video_duration_seconds: float,
        config: Settings,
        video_hash: str | None = None,
        audio_path: str | None = None,
    ) -> ContentIntelligenceResult: ...
    # map-reduce (D17) + checkpoint por chunk (D29) + picos RMS (D21/B16)
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.6 `TimelineValidatorAgent` — `agents/timeline_validator/agent.py`
```python
class TimelineValidatorAgent:
    def run(
        self,
        content: ContentIntelligenceResult,
        video_duration_seconds: float,
        transcript: list[dict] | None = None,
        config: Settings | None = None,
    ) -> ContentIntelligenceResult: ...
    # ajusta timestamps via model_copy(update=...) — preserva campos D19/D21 (B12)
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.7 `VideoEditAgent` — `agents/video_edit/agent.py`
```python
def build_cut_list(...) -> CutList: ...  # função pura de módulo

class VideoEditAgent:
    def run(
        self,
        video_ingest: dict,
        transcript: dict,
        config: Settings,
        marker_pairs: list[dict] | None = None,
    ) -> EditResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.8 `SubtitleStylingAgent` — `agents/subtitle_styling/agent.py`
```python
def split_into_caption_chunks(...) -> list[TranscriptSegment]: ...  # função pura de módulo
def to_srt(chunks: list[TranscriptSegment]) -> str: ...
def to_vtt(chunks: list[TranscriptSegment]) -> str: ...

class SubtitleStylingAgent:
    def run(self, video_id: str, transcript: TranscriptCleaned, config: Settings) -> SubtitleResult: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.9 `ShortsExtractorAgent` — `agents/shorts_extractor/agent.py`
```python
class ShortsExtractorAgent:
    def run(
        self,
        video_path: Path,
        content: ContentIntelligenceResult,
        output_dir: Path,
        config: Settings,
    ) -> list[Path]: ...
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

### 12.10 `PackagingAgent` — `agents/packaging/agent.py`
```python
class PackagingAgent:
    def run(
        self,
        video_path: Path,
        video_hash: str,
        config: Settings,
        state: PipelineState,
    ) -> AnalyticsReport: ...  # state lido do arquivo persistido pelo run_stage (D30)
    def _resolve_edited_video(self, cache_dir: Path, output_dir: Path, video_hash: str) -> Path | None: ...  # B13
    def _build_analytics(
        self, state: PipelineState, output_dir: Path, video_id: str, config: Settings, cache_dir: Path
    ) -> AnalyticsReport: ...  # B15: duração via metadata + snapshot sanitizado
    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None: ...
```

---

## 13. Serviços de Infraestrutura

### 13.1 `services/ffmpeg_service.py`
```python
def get_video_metadata(video_path: Path) -> VideoMetadata: ...  # fps via fractions.Fraction (B4)
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

### 13.2 `services/whisper_service.py`
```python
def transcribe(
    audio_path: Path, video_id: str, config: Settings | None = None
) -> TranscriptRaw: ...  # VAD obrigatório (D6); hotwords/glossário (D20)
def unload_whisper_model() -> None: ...  # libera VRAM — chamado ao fim de SPEECH_RECOGNITION
```

### 13.3 `services/llm_provider.py` (novo — D29)
```python
class LLMProvider(ABC):  # OllamaProvider | GeminiProvider | GroqProvider
    def __init__(self, config: Settings): ...
    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
        json_mode: bool = False,
        timeout: int = 120,
    ) -> str: ...
    def _post(self, url: str, *, payload: dict, headers: dict | None = None, timeout: int = 120) -> requests.Response:
        ...  # retry/backoff em 429/5xx/ConnectionError (nunca em 401/403/404)


def get_provider(config: Settings | None = None) -> LLMProvider: ...


def generate(
    system_prompt: str,
    user_prompt: str,
    temperature: float | None = None,
    json_mode: bool = False,
    timeout: int = 120,
    config: Settings | None = None,
) -> str: ...
```

> `services/ollama_service.py` é **legado** — toda geração deve passar por `services/llm_provider.py`.

### 13.4 `services/audio_analysis_service.py` (D21/B16)
```python
def find_energy_peaks(audio_path: Path, ...) -> list[tuple[float, float]]: ...  # stdlib wave, sem numpy
def get_energy_peaks_cached(audio_path: Path, cache_dir: Path | None, ...) -> list[tuple[float, float]]:
    ...  # cache em cache/<hash>/audio_peaks.json, invalidado por tamanho+mtime
```

### 13.5 `services/transcript_import.py`
```python
def import_transcript(path: Path, video_id: str) -> TranscriptRaw: ...  # JSON/SRT/VTT
```

---

## 14. Cache, Hash e Utilitários (`utils/`)

```python
# utils/hash_utils.py
def compute_video_hash(video_path: Path) -> str: ...
    # B12/B14: hash por amostra (tamanho + mtime_ns + 1º/último MB) — NUNCA ler o arquivo inteiro
def get_cache_dir(video_hash: str) -> Path: ...
def get_video_hash_from_id(video_id: str) -> str: ...
    # ÚNICA fonte de verdade do hash — usar sempre, nunca reimplementar


# utils/file_utils.py
def ensure_dir(path: Path) -> Path: ...
def load_json(path: Path) -> dict | None: ...
def save_json(path: Path, data: dict) -> None: ...  # atomicidade: escreve .tmp + os.replace()


# utils/time_utils.py
def seconds_to_hms(seconds: float) -> str: ...
def seconds_to_srt_timestamp(seconds: float) -> str: ...
def seconds_to_vtt_timestamp(seconds: float) -> str: ...
def hms_to_seconds(hms: str) -> float: ...


# utils/slugify.py
def slugify_filename(filename: str) -> str: ...
def generate_video_id(filename: str, video_hash: str) -> str: ...


# utils/shorts_anchoring.py (D18)
def anchor_short_candidate(
    cand: dict,
    segments: list,
    video_duration_seconds: float,
    min_duration: float,
    max_duration: float,
) -> dict | None: ...  # similaridade gancho/payoff contra segmentos cronometrados


# utils/glossary_correction.py (D20)
def load_glossary(name: str, glossaries_dir: Path | None = None) -> dict | None: ...
def apply_glossary_to_segments(segments, glossary) -> list: ...
def build_initial_prompt_from_glossary(glossary, max_words: int = 200) -> str: ...
def correct_segment_text(text: str, glossary: dict) -> str: ...
```

**Estrutura de cache em disco:**
```
cache/<video_hash>/
├── metadata.json
├── transcript.json
├── markers.json
├── cleaned.json          (+ cleaned.partial.json durante processamento em lote)
├── content.json
├── shorts.json
├── audio_peaks.json      (B16)
├── chunks_<fingerprint>/ (D29 — checkpoint do map-reduce)
│   ├── chunk_000.json
│   └── ...
└── pipeline_state.json   (inclui stage_fingerprints — D27)
```

---

## 15. Fingerprint por Etapa (`pipeline/fingerprint.py` — D27)

```python
def compute_stage_fingerprint(stage_name: str, config: Settings) -> str:
    ...  # sha256 (16 hex) do JSON ordenado de settings + snapshot size/mtime dos arquivos da etapa
def compute_stage_fingerprints(config: Settings) -> dict[str, str]: ...
```

Etapas mapeadas: `SPEECH_RECOGNITION`, `MARKER_DETECTION`, `TRANSCRIPT_CLEANING`, `CONTENT_INTELLIGENCE`, `TIMELINE_VALIDATION`, `VIDEO_EDIT`, `SUBTITLE_STYLING`, `SHORTS_EXTRACTION`. `VIDEO_PROCESSING`/`PACKAGING` têm lista vazia (insensíveis a config).

---

## 16. Pre-flight Check (`shared/preflight.py`)

```python
def run_preflight_checks(config: Settings | None = None) -> list[str]:
    ...  # instancia Settings() quando None; retorna lista de problemas (vazia = OK)


class PreFlightCheck:
    def __init__(self, config: Settings): ...
    def run(self) -> None: ...  # levanta PreflightError se ambiente inadequado
```

---

## 17. Persistência — Analytics/Histórico (`shared/db/`)

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

## 18. Orquestração (`pipeline/runner.py`)

```python
# D30: handlers são funções puras — sem state mutável compartilhado
StageHandler = Callable[[Path, str, Settings], None]


class PipelineStage(Enum):
    PRE_FLIGHT = auto()
    VIDEO_PROCESSING = auto()
    SPEECH_RECOGNITION = auto()
    MARKER_DETECTION = auto()
    TRANSCRIPT_CLEANING = auto()
    CONTENT_INTELLIGENCE = auto()
    TIMELINE_VALIDATION = auto()
    VIDEO_EDIT = auto()
    SUBTITLE_STYLING = auto()
    SHORTS_EXTRACTION = auto()
    PACKAGING = auto()

    @classmethod
    def ordered(cls) -> list["PipelineStage"]: ...  # todas exceto PRE_FLIGHT


# Rodam em paralelo via ThreadPoolExecutor (mutuamente independentes):
PARALLEL_GROUP: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.SUBTITLE_STYLING,
        PipelineStage.SHORTS_EXTRACTION,
    }
)


class PipelineRunner:
    def __init__(self, config: Settings, max_parallel_workers: int = 3): ...
    def register(self, stage: PipelineStage, handler: StageHandler) -> None: ...
    def run(
        self,
        video_path: Path,
        from_stage: str | None = None,
        force: bool = False,
        transcript_path: Path | None = None,
    ) -> PipelineState: ...
    def _invalidate_stale_stages(self, state: PipelineState) -> None:
        ...  # D27: invalida etapa com fingerprint alterado + todas as subsequentes (cascata)

    # registro de StageResult em state.stages é responsabilidade EXCLUSIVA desta classe
```

---

## 19. Prompts Externos (`prompts/*.md`)

| Arquivo | Usado por |
|---|---|
| `prompts/cleaning_llm.md` | `TranscriptCleanerAgent` |
| `prompts/content_intelligence.md` | `ContentIntelligenceAgent` (map: SEO/capítulos por chunk) |
| `prompts/content_consolidation.md` | `ContentIntelligenceAgent` (reduce: consolidação global + campanha + hashtags) |
| `prompts/shorts_prompt.md` | `ContentIntelligenceAgent` (shorts por capítulo, com picos de energia) |
| `prompts/standalone_check_prompt.md` | `ContentIntelligenceAgent` (crítico de autocontenção, D19) |

Regra: nenhum prompt hardcoded no código com mais de 2 linhas — sempre carregado desses arquivos em runtime.

---

## 20. Regras Fixas (não-negociáveis, independente do módulo)

- `run_stage()` de agente **nunca** recebe `state` (D30) nem chama `state.stages.append(...)` — só o `PipelineRunner` registra `StageResult`.
- `run_stage()` de agente **nunca** recria `Settings()` — usa o `config` injetado (D28). O singleton é só fallback fora do pipeline.
- Hash de vídeo: **sempre** via `get_video_hash_from_id()` / `compute_video_hash()` de `utils/hash_utils.py` — nunca reimplementar em outro módulo. `compute_video_hash` lê **apenas amostra** (tamanho+mtime+1º/último MB).
- `PipelineState`/`StageResult`: sem `strict=True`. Todos os demais schemas: com `strict=True`.
- Parsing de FPS: `fractions.Fraction`, nunca `eval()`.
- Regex de limpeza: lista fechada (`hum`, `ah`, `ahn`, `ãhn`, `ehm`) com `\b`, nunca `é`/`tipo`/`né` (esses só via LLM, com contexto).
- `TranscriptCleanerAgent`: batches de 25 segmentos por chamada LLM, nunca 1 por segmento.
- Retry de LLM (D29): apenas em 429/5xx/`ConnectionError`; 401/403/404 são erros imediatos com mensagem clara.
- Checkpoint de chunk (D29): sempre chaveado por fingerprint de config — nunca reutilizar checkpoint de uma config diferente.
- Ao "ajustar" um modelo Pydantic, usar `model_copy(update=...)` — nunca reconstruir com campos parciais (protege B12).
- Ao copiar artefatos entre cache/outputs, derivar caminhos do `video_id` oficial (`utils/slugify`), nunca do `stem` do arquivo (protege B13).
- `config_snapshot` do analytics nunca inclui campos com `key`/`token` no nome (protege B15).
- VAD: `whisper_vad_filter=True` sempre — não exposto como opção desabilitável na V1.
- Cache: escrita atômica (`.tmp` + `os.replace()`).
- Sem `langgraph`, `moviepy`, `ffmpeg-python`, `redis`, `kubernetes`, `opencv-python` no `pyproject.toml`.
- Subprocess do FFmpeg: sempre lista de argumentos, nunca `shell=True`.
- Novo setting no `Settings`: mapeá-lo em `_SETTINGS_BY_STAGE` (D27) para a etapa que ele afeta.

---

*Fim da Referência Rápida de Contratos.*
