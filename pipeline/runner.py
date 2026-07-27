import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from config.settings import Settings
from schemas.state import PipelineState, StageResult
from shared.preflight import PreFlightCheck
from utils.file_utils import load_json, save_json
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)

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


PARALLEL_GROUP = frozenset(
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
        self._handlers: dict[PipelineStage, StageHandler] = {}

    def register(self, stage: PipelineStage, handler: StageHandler) -> None:
        self._handlers[stage] = handler

    def _load_or_create_state(self, video_path: Path) -> PipelineState:
        video_hash = self._compute_hash(video_path)
        cache_dir = get_cache_dir(video_hash)
        state_path = cache_dir / "pipeline_state.json"

        cached = load_json(state_path)
        if cached:
            logger.info(f"Estado carregado do cache: {state_path}")
            return PipelineState(**cached)

        now = datetime.now()
        return PipelineState(
            video_hash=video_hash,
            video_path=video_path,
            created_at=now,
            updated_at=now,
        )

    def _compute_hash(self, video_path: Path) -> str:
        from utils.hash_utils import compute_video_hash

        return compute_video_hash(video_path)

    def _save_state(self, state: PipelineState) -> None:
        cache_dir = get_cache_dir(state.video_hash)
        state_path = cache_dir / "pipeline_state.json"
        save_json(state_path, state.model_dump(mode="json"))
        logger.debug(f"Estado salvo em {state_path}")

    def _record_stage_result(
        self,
        state: PipelineState,
        stage_name: str,
        status: str,
        started_at: datetime,
        finished_at: datetime | None = None,
        error_message: str | None = None,
    ) -> None:
        """Registra StageResult no estado. Responsabilidade EXCLUSIVA desta classe."""
        if finished_at is None:
            finished_at = datetime.now()
        duration = (finished_at - started_at).total_seconds()

        stage_result = StageResult(
            stage=stage_name,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_seconds=duration,
            error_message=error_message,
        )
        # Remove any previous result for same stage (avoids duplicates)
        state.stages = [s for s in state.stages if s.stage != stage_name]
        state.stages.append(stage_result)
        state.updated_at = datetime.now()
        self._save_state(state)

    def run(
        self,
        video_path: Path,
        from_stage: str | None = None,
        force: bool = False,
        transcript_path: Path | None = None,
    ) -> PipelineState:
        state = self._load_or_create_state(video_path)

        if force:
            state.stages = []
            state.completed = False
            state.current_stage = None

        if from_stage and not force:
            state.current_stage = from_stage

        # Pre-flight check
        preflight = PreFlightCheck(self.config)
        preflight.run()

        # Import external transcript if provided
        if transcript_path is not None:
            self._import_transcript(transcript_path, state)

        stages = PipelineStage.ordered()
        # Find starting point
        start_idx = 0
        if state.current_stage is not None:
            for i, s in enumerate(stages):
                if s.name == state.current_stage:
                    start_idx = i
                    break

        i = start_idx
        while i < len(stages):
            stage = stages[i]

            if state.is_stage_done(stage.name) and not force:
                logger.info(f"Etapa {stage.name} ja concluida. Pulando.")
                state.current_stage = stage.name
                i += 1
                continue

            if stage in PARALLEL_GROUP:
                parallel_batch = [s for s in stages[i:] if s in PARALLEL_GROUP]
                self._run_parallel_group(state, parallel_batch, video_path)
                i += len(parallel_batch)
                continue

            self._run_single_stage(state, stage, video_path)
            i += 1

        state.completed = True
        state.current_stage = None
        self._save_state(state)
        logger.info("Pipeline concluido com sucesso.")
        return state

    def _import_transcript(self, transcript_path: Path, state: PipelineState) -> None:
        from services.transcript_import import import_transcript
        from utils.slugify import generate_video_id

        cache_dir = get_cache_dir(state.video_hash)
        video_id = generate_video_id(state.video_path)
        transcript = import_transcript(transcript_path, video_id)
        save_json(cache_dir / "transcript.json", transcript.model_dump())

        duration = transcript.duration_seconds
        metadata_path = cache_dir / "metadata.json"
        existing = load_json(metadata_path)
        if existing:
            existing.setdefault("metadata", {})["duration_seconds"] = duration
            save_json(metadata_path, existing)
        else:
            save_json(
                metadata_path,
                {
                    "video_id": video_id,
                    "audio_path": str(state.video_path),
                    "metadata": {"duration_seconds": duration},
                },
            )

        now = datetime.now()
        for stage_name in ("VIDEO_PROCESSING", "SPEECH_RECOGNITION"):
            result = StageResult(
                stage=stage_name,
                status="success",
                started_at=now,
                finished_at=now,
                duration_seconds=0.0,
                error_message="Transcricao importada externamente",
            )
            state.stages = [s for s in state.stages if s.stage != stage_name]
            state.stages.append(result)

        state.current_stage = "TRANSCRIPT_CLEANING"
        state.updated_at = now
        self._save_state(state)
        logger.info(
            f"Transcricao importada de {transcript_path.name}: "
            f"{len(transcript.segments)} segmentos, {duration:.1f}s"
        )

    def _run_single_stage(
        self, state: PipelineState, stage: PipelineStage, video_path: Path
    ) -> None:
        handler = self._handlers.get(stage)
        if handler is None:
            logger.warning(f"Nenhum handler registrado para {stage.name}. Pulando.")
            return

        logger.info(f"Iniciando etapa: {stage.name}")
        started_at = datetime.now()
        state.current_stage = stage.name

        try:
            handler(video_path, state.video_hash, self.config, state)
            finished_at = datetime.now()
            self._record_stage_result(state, stage.name, "success", started_at, finished_at)
            logger.info(f"Etapa {stage.name} concluida com sucesso.")
        except Exception as e:
            finished_at = datetime.now()
            self._record_stage_result(state, stage.name, "failed", started_at, finished_at, str(e))
            logger.error(f"Etapa {stage.name} falhou: {e}")
            raise

    def _run_parallel_group(
        self,
        state: PipelineState,
        stages: list[PipelineStage],
        video_path: Path,
    ) -> None:
        logger.info(f"Executando grupo paralelo: {[s.name for s in stages]}")
        with ThreadPoolExecutor(max_workers=self.max_parallel_workers) as executor:
            future_to_stage = {}
            for stage in stages:
                handler = self._handlers.get(stage)
                if handler is None:
                    logger.warning(f"Nenhum handler para {stage.name}")
                    continue
                started_at = datetime.now()
                state.current_stage = stage.name
                future = executor.submit(handler, video_path, state.video_hash, self.config, state)
                future_to_stage[future] = (stage, started_at)

            for future in as_completed(future_to_stage):
                stage_name, started_at = future_to_stage[future]
                try:
                    future.result()
                    finished_at = datetime.now()
                    self._record_stage_result(state, stage_name, "success", started_at, finished_at)
                    logger.info(f"Etapa {stage_name} concluida (paralelo).")
                except Exception as e:
                    finished_at = datetime.now()
                    self._record_stage_result(
                        state, stage_name, "failed", started_at, finished_at, str(e)
                    )
                    logger.error(f"Etapa {stage_name} falhou (paralelo): {e}")
