"""
Central logger configuration for bsl_universal.
"""

import sys

from loguru import logger

_STDOUT_FORMAT = (
    "<cyan>{time:MM-DD at HH:mm:ss}</cyan> | <level>{level:7}</level> | "
    "{file:15}:{line:4} | <level>{message}</level>"
)
_STDERR_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level}</level> | "
    "{function}:{line} - <level>{message}</level>"
)


def init_logger(log_level: str = "DEBUG") -> None:
    """
    Initialize process-level logging for library usage.

    Parameters
    ----------
    log_level : str, optional
        Loguru log level string, by default ``"DEBUG"``.
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
    logger.success(f'Logger initialized with LOG_LEVEL = "{log_level}".')
