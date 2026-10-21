"""Keep the computer from idle-sleeping while a long run is in progress.

On Windows this is a per-process request (``SetThreadExecutionState``), the same
mechanism media players and installers use: it changes no system settings and
ends automatically when the context exits or the process dies. Elsewhere it is a
no-op. It does not prevent sleep from a closed lid or an explicit "Sleep".
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _default_setter() -> Callable[[int], int] | None:
    if sys.platform != "win32":
        return None
    import ctypes

    return ctypes.windll.kernel32.SetThreadExecutionState  # type: ignore[attr-defined,no-any-return]


@contextmanager
def keep_awake(enabled: bool = True, *, setter: Callable[[int], int] | None = None) -> Iterator[bool]:
    """Hold an idle-sleep block for the duration of the ``with`` block.

    Yields whether a block is actually held. ``setter`` is injectable for tests.
    """
    set_state = setter if setter is not None else (_default_setter() if enabled else None)
    if not enabled or set_state is None:
        yield False
        return
    if not set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED):
        logger.warning("could not prevent idle sleep; a long run may be interrupted")
        yield False
        return
    logger.info("preventing idle sleep until the run finishes")
    try:
        yield True
    finally:
        set_state(ES_CONTINUOUS)
