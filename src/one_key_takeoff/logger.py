import logging
import os
from datetime import UTC, datetime

from .config import settings

_log_file_path: str | None = None


def setup_logging(prefix: str = "one_key_takeoff") -> logging.Logger:
    """Configures centralized logging for console and timestamped log files."""
    global _log_file_path

    logger = logging.getLogger("one_key_takeoff")

    # Avoid duplicate handler configuration if already initialized
    if logger.handlers:
        return logger

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger.setLevel(log_level)

    # Formatter configuration
    log_format = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(log_format)
    logger.addHandler(console_handler)

    # 2. File Handler (Timestamped log file)
    try:
        os.makedirs(settings.log_dir, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        _log_file_path = os.path.join(settings.log_dir, f"{prefix}_{timestamp}.log")

        file_handler = logging.FileHandler(_log_file_path, encoding="utf-8")
        file_handler.setLevel(log_level)
        file_handler.setFormatter(log_format)
        logger.addHandler(file_handler)

        logger.info(f"Logging initialized. Log file: {_log_file_path}")
    except OSError as e:
        logger.warning(
            f"Could not create file log handler in '{settings.log_dir}': {e}"
        )

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Returns a module logger child of the main application logger."""
    base_logger = setup_logging(prefix=name or "one_key_takeoff")
    if name:
        return logging.getLogger(f"one_key_takeoff.{name}")
    return base_logger
