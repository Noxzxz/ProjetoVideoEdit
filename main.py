#!/usr/bin/env python3
"""Entry point da CLI do pipeline de video."""

import logging
import sys
from pathlib import Path

from app.cli import parse_args
from config.settings import Settings
from pipeline.runner import PipelineRunner, PipelineStage
from shared.logging_config import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    args = parse_args()

    log_level = "DEBUG" if args.verbose else "INFO"
    setup_logging(log_level)

    config = Settings()
    video_path = Path(args.video)

    if not video_path.exists():
        logger.error(f"Arquivo nao encontrado: {video_path}")
        return 1

    transcript_path: Path | None = None
    if args.transcript:
        transcript_path = Path(args.transcript)
    elif args.srt:
        transcript_path = Path(args.srt)
    elif args.vtt:
        transcript_path = Path(args.vtt)

    if transcript_path and not transcript_path.exists():
        logger.error(f"Transcricao nao encontrada: {transcript_path}")
        return 1

    runner = PipelineRunner(config)

    # Register all agents
    try:
        from agents.content_intelligence.agent import ContentIntelligenceAgent
        from agents.packaging.agent import PackagingAgent
        from agents.shorts_extractor.agent import ShortsExtractorAgent
        from agents.speech_recognition.agent import SpeechRecognitionAgent
        from agents.subtitle_styling.agent import SubtitleStylingAgent
        from agents.thumbnail_frames.agent import ThumbnailFramesAgent
        from agents.timeline_validator.agent import TimelineValidatorAgent
        from agents.transcript_cleaner.agent import TranscriptCleanerAgent
        from agents.video_edit.agent import VideoEditAgent
        from agents.video_processing.agent import VideoProcessingAgent
    except ImportError as e:
        logger.error(f"Erro ao carregar agentes: {e}")
        return 1

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

    try:
        state = runner.run(
            video_path=video_path,
            from_stage=args.from_stage,
            force=args.force,
            transcript_path=transcript_path,
        )
        if state.completed:
            logger.info("Pipeline concluido com sucesso!")
            return 0
        else:
            logger.warning("Pipeline incompleto.")
            return 2
    except Exception as e:
        logger.error(f"Pipeline falhou: {e}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
