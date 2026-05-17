from __future__ import annotations

import logging
from pathlib import Path


LOGGER_NAME = "osmind"


def configure_file_logging(notes_vault: Path) -> Path:
    log_path = notes_vault / "osmind" / ".cache" / "osmind.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == log_path
        for handler in logger.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)

    return log_path


def log_exception(notes_vault: Path, message: str) -> Path:
    log_path = configure_file_logging(notes_vault)
    logging.getLogger(LOGGER_NAME).exception(message)
    return log_path
