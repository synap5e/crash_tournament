"""
Logging configuration for crash tournament.

Sets up loguru with appropriate levels and formatting.
"""

import sys

from loguru import logger
from typing import Any


def setup_logging(level: str = "INFO", debug: bool = False) -> None:
    """
    Configure loguru logging.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        debug: If True, enable debug logging and more verbose output
    """
    # Remove default handler
    logger.remove()

    # Set log level
    log_level = "DEBUG" if debug else level

    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>",
    )

    # Add file handler for important events (INFO and above)
    logger.add(
        "crash_tournament.log",
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="7 days",
        compression="zip",
    )

    # Add debug file handler if debug mode
    if debug:
        logger.add(
            "crash_tournament_debug.log",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
            rotation="50 MB",
            retention="3 days",
            compression="zip",
        )


def get_logger(name: str | None = None) -> Any:
    """
    Get a logger instance.

    Args:
        name: Optional name for the logger (defaults to calling module)

    Returns:
        Logger instance
    """
    if name:
        return logger.bind(name=name)
    return logger
