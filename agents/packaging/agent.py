import logging
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from config.settings import Settings
from schemas.analytics import AnalyticsReport
from schemas.state import PipelineState
from utils.file_utils import atomic_write_text, ensure_dir, load_json
from utils.hash_utils import get_cache_dir
from utils.slugify import generate_video_id

logger = logging.getLogger(__name__)


class PackagingAgent:
    def _copy_if_exists(self, src: Path, dst: Path) -> None:
        if src.exists():
            shutil.copy2(str(src), str(dst))

    def _resolve_edited_video(
        self, cache_dir: Path, output_dir: Path, video_hash: str
    ) -> Path | None:
        """Localiza o video editado, que o VideoEditAgent grava em outputs/{video_id}/.

        O video_id e derivado do nome do arquivo + hash (utils.slugify), portanto
        difere do stem usado em output_dir. Fallback para o proprio output_dir.
        """
        metadata = load_json(cache_dir / "metadata.json") or {}
        video_id = metadata.get("video_id") or generate_video_id(
            output_dir.name, video_hash
        )
        candidates = [
            output_dir / "edited.mp4",
            output_dir.parent / video_id / "edited.mp4",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

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

        atomic_write_text(output_dir / "report.md", "\n".join(lines))

    def _build_analytics(
        self,
        state: PipelineState,
        output_dir: Path,
        video_id: str,
        config: Settings,
        cache_dir: Path,
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

        metadata = load_json(cache_dir / "metadata.json") or {}
        duration = metadata.get("metadata", {}).get("duration_seconds", 0.0)

        # B13: config_snapshot sem segredos (api keys / tokens)
        snapshot = {
            k: v
            for k, v in config.model_dump(mode="json").items()
            if "key" not in k.lower() and "token" not in k.lower()
        }

        return AnalyticsReport(
            video_hash=state.video_hash,
            video_name=video_name,
            video_duration_seconds=duration,
            processed_at=datetime.now(),
            config_snapshot=snapshot,
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

        # Copy edited video (grava em outputs/{video_id}/edited.mp4)
        edited_src = self._resolve_edited_video(cache_dir, output_dir, video_hash)
        if edited_src is not None:
            self._copy_if_exists(edited_src, output_dir / "edited.mp4")

        # Copy shorts
        shorts_dir = cache_dir / "shorts"
        if shorts_dir.exists():
            shorts_out = output_dir / "shorts"
            shorts_out.mkdir(parents=True, exist_ok=True)
            for f in shorts_dir.glob("*.mp4"):
                self._copy_if_exists(f, shorts_out / f.name)

        # Build and save analytics
        analytics = self._build_analytics(state, output_dir, video_hash, config, cache_dir)
        analytics_path = output_dir / "analytics.json"
        atomic_write_text(analytics_path, analytics.model_dump_json(indent=2))

        # Generate report
        self._generate_report(state, output_dir, video_hash)

        # Create ZIP (atomico via tmp)
        zip_dest = output_dir.parent / f"{state.video_path.stem}.zip"
        tmp_zip = zip_dest.with_name(f"{zip_dest.name}.{os.getpid()}.tmp")
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in output_dir.rglob("*"):
                if f.is_file():
                    arcname = str(f.relative_to(output_dir.parent))
                    zf.write(str(f), arcname)
        os.replace(str(tmp_zip), str(zip_dest))

        logger.info(f"Pacote gerado: {zip_dest}")
        return analytics

    def run_stage(self, video_path: Path, video_hash: str, config: Settings) -> None:
        # D30: leitura do estado persistido (read-only), sem receber state mutavel
        cache_dir = get_cache_dir(video_hash)
        state_data = load_json(cache_dir / "pipeline_state.json")
        if not state_data:
            raise FileNotFoundError(
                f"Estado do pipeline nao encontrado no cache para hash {video_hash}"
            )
        state = PipelineState(**state_data)
        self.run(video_path, video_hash, config, state)
