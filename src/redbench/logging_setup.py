"""Logging configuration.

Only the CLI calls these functions; library modules just use ``logging.getLogger``.
"""

import logging
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str = "INFO") -> None:
    """Send log records at ``level`` and above to stderr."""
    logging.basicConfig(level=level.upper(), format=_FORMAT, force=True)
    # httpx logs every request at INFO, which drowns out run progress.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def add_file_handler(path: Path) -> logging.Handler:
    """Also write log records to ``path`` (e.g. a run's ``run.log``).

    Returns the handler so the caller can detach it with :func:`remove_handler`.
    """
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler


def remove_handler(handler: logging.Handler) -> None:
    """Detach and close a handler added by :func:`add_file_handler`."""
    logging.getLogger().removeHandler(handler)
    handler.close()
