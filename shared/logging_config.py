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

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper()))
    root.handlers = [console_handler, file_handler]
