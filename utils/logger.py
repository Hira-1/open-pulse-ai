"""
Centralised logging configuration for OpenPulse AI.

Import and call setup_logging() once at every entry point
(collect.py, tests, dashboard/app.py).
"""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """
    Configure root logger with a timestamp-prefixed format.

    Format: 2026-05-21 20:08:10 | INFO     | module_name | message
    """
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=level,
        format=fmt,
        datefmt=datefmt,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # Quieten noisy third-party loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("github").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
