"""
Central logger configuration for bsl_universal.

In addition to the colorized stdout/stderr sinks, ``init_logger`` writes a
machine-readable **JSON-lines** log file per process under
``~/.bsl_universal/logs/`` (override with ``BSL_LOG_DIR``; disable with
``BSL_DISABLE_FILE_LOG``). The web device monitor's log analyzer reads these
files to provide search, level/timeline analytics, and live tailing.
"""

import os
import sys
from pathlib import Path

from loguru import logger

_STDOUT_FORMAT = (
    "<cyan>{time:MM-DD at HH:mm:ss}</cyan> | <level>{level:7}</level> | "
    "{file:15}:{line:4} | <level>{message}</level>"
)
_STDERR_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level}</level> | "
    "{function}:{line} - <level>{message}</level>"
)

_DEFAULT_LOG_DIR = Path.home() / ".bsl_universal" / "logs"


def log_directory() -> Path:
    """Return the directory where JSON-lines log files are written.

    Honors the ``BSL_LOG_DIR`` environment variable; otherwise defaults to
    ``~/.bsl_universal/logs``.

    Returns
    -------
    pathlib.Path
        Resolved log directory (not guaranteed to exist).
    """
    override = os.environ.get("BSL_LOG_DIR", "").strip()
    return Path(override).expanduser() if override else _DEFAULT_LOG_DIR


def init_logger(log_level: str = "DEBUG", *, log_to_file: bool = True) -> None:
    """
    Initialize process-level logging for library usage.

    Parameters
    ----------
    log_level : str, optional
        Loguru log level string, by default ``"DEBUG"``.
    log_to_file : bool, optional
        When True (default), also add a rotating JSON-lines file sink under
        :func:`log_directory` so the device-monitor log analyzer has data.
        Suppressed when the ``BSL_DISABLE_FILE_LOG`` environment variable is set.
    """
    logger.remove()
    logger.add(
        sys.stdout,
        colorize=True,
        format=_STDOUT_FORMAT,
        level=log_level,
        diagnose=False,
    )
    logger.add(
        sys.stderr,
        colorize=True,
        format=_STDERR_FORMAT,
        level=log_level,
        diagnose=False,
    )

    if log_to_file and not os.environ.get("BSL_DISABLE_FILE_LOG"):
        try:
            directory = log_directory()
            directory.mkdir(parents=True, exist_ok=True)
            # One file per process (pid in the name) avoids multi-process write
            # contention; serialize=True emits one JSON object per line for the
            # analyzer; enqueue=True keeps logging off the hardware hot path.
            sink_path = str(directory / ("bsl_%d_{time:YYYYMMDD_HHmmss}.log" % os.getpid()))
            logger.add(
                sink_path,
                level=log_level,
                serialize=True,
                enqueue=True,
                rotation="10 MB",
                retention="10 days",
                diagnose=False,
                backtrace=False,
            )
        except Exception as exc:  # pragma: no cover - logging must never break callers
            logger.warning("File logging disabled (could not initialize log file): {}", exc)

    logger.success(f'Logger initialized with LOG_LEVEL = "{log_level}".')
