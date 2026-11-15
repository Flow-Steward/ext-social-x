"""Absolute socket/DNS/body-read budget for the single-threaded subprocess."""

import signal
from collections.abc import Iterator
from contextlib import contextmanager


def _expired(_signal: int, _frame: object) -> None:
    raise TimeoutError("X request deadline elapsed")


@contextmanager
def network_timer(seconds: float) -> Iterator[None]:
    previous_handler = signal.signal(signal.SIGALRM, _expired)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0]:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)
