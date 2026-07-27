import logging
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from config.settings import Settings
from schemas.analytics import AnalyticsReport
from schemas.state import PipelineState
from utils.file_utils import ensure_dir
from utils.hash_utils import get_cache_dir

logger = logging.getLogger(__name__)


class PackagingAgent:
    def _copy_if_exists(self, src: Path, dst: Path) -> None:
        if src.exists():
            shutil.copy2(str(src), str(dst))

    def _generate_report(self, state: PipelineState, output_dir: Path, video_id: str) -> None:
        lines = [
            f"# Relatorio de Processamento - {video_id}",
            "",
            f"**Video:** {state.video_path.name}",
            f"**Processado em:** {datetime.now().isoformat()}",
            f"**Status:** {'Concluido' if state.completed else 'Incompleto'}",
            "",
            "## Etapas",
        ]
        for stage in state.stages:
            status_emoji = {
                "success": "✅",
                "skipped": "⏭️",
                "failed": "❌",
            }.get(stage.status, "❓")
            duration = stage.duration_seconds
            lines.append(f"- {status_emoji} **{stage.stage}** - {duration:.1f}s")
            if stage.error_message:
                lines.append(f"  - Erro: {stage.error_message}")

        (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")

    def _build_analytics(
        self, state: PipelineState, output_dir: Path, video_id: str
    ) -> AnalyticsReport:
        stages = []
        for s in state.stages:
            stages.append(
                {
                    "stage": s.stage,
                    "duration_seconds": s.duration_seconds,
                    "status": s.status,
                }
            )

        total_time = sum(s.duration_seconds for s in state.stages)
        video_name = state.video_path.name

        return AnalyticsReport(
            video_hash=state.video_hash,
            video_name=video_name,
            video_duration_seconds=0.0,  # would need metadata
            processed_at=datetime.now(),
            config_snapshot={},
            stages=stages,
            total_processing_time_seconds=total_time,
            output_directory=output_dir,
        )

    def run(
        self,
        video_path: Path,
        video_hash: str,
        config: Settings,
        state: PipelineState,
    ) -> AnalyticsReport:
        cache_dir = get_cache_dir(video_hash)
        output_dir = Path(config.outputs_dir) / state.video_path.stem
        ensure_dir(output_dir)

        # Copy artifacts
        artifacts_dir = cache_dir
        if artifacts_dir.exists():
            for item in artifacts_dir.iterdir():
                if item.is_file() and item.suffix in (".json", ".srt", ".vtt"):
                    self._copy_if_exists(item, output_dir / item.name)

        # Copy edited video
        edited = output_dir / "edited.mp4"
        if edited.exists():
            self._copy_if_exists(edited, output_dir / edited.name)

        # Copy shorts
        shorts_dir = cache_dir / "shorts"
        if shorts_dir.exists():
            shorts_out = output_dir / "shorts"
            shorts_out.mkdir(parents=True, exist_ok=True)
            for f in shorts_dir.glob("*.mp4"):
                self._copy_if_exists(f, shorts_out / f.name)

        # Copy thumbnails
        thumbs_dir = cache_dir / "thumbnails"
        if thumbs_dir.exists():
            thumbs_out = output_dir / "thumbnails"
            thumbs_out.mkdir(parents=True, exist_ok=True)
            for f in thumbs_dir.glob("*.jpg"):
                self._copy_if_exists(f, thumbs_out / f.name)

        # Build and save analytics
        analytics = self._build_analytics(state, output_dir, video_hash)
        analytics_path = output_dir / "analytics.json"
        analytics_path.write_text(analytics.model_dump_json(indent=2), encoding="utf-8")

        # Generate report
        self._generate_report(state, output_dir, video_hash)

        # Create ZIP
        zip_path = output_dir.parent / f"{state.video_path.stem}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in output_dir.rglob("*"):
                if f.is_file():
                    arcname = str(f.relative_to(output_dir.parent))
                    zf.write(str(f), arcname)

        logger.info(f"Pacote gerado: {zip_path}")
        return analytics

    def run_stage(
        self, video_path: Path, video_hash: str, config: Settings, state: PipelineState
    ) -> None:
        self.run(video_path, video_hash, config, state)
