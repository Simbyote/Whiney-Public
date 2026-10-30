"""
A stand-in for a module's `time` (installed with monkeypatch.setattr(module,
"time", clock)): time() is a counter that sleep() advances instantly, running
whatever was scheduled with at() on the way. strftime, mktime and the rest are
the real ones, so only the module under test sees the fake.
"""
import time as real_time
from collections.abc import Callable


class FakeClock:
    """time() and sleep() over a counter; at(when, fn) runs fn once the clock reaches `when`."""

    def __init__(self, start: float = 1000.0):
        self.now = start
        self._scheduled: list[tuple[float, Callable[[], object]]] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        due = sorted((s for s in self._scheduled if s[0] <= self.now), key=lambda s: s[0])
        self._scheduled = [s for s in self._scheduled if s[0] > self.now]
        for _, fn in due:
            fn()

    def at(self, when: float, fn: Callable[[], object]) -> None:
        self._scheduled.append((when, fn))

    def __getattr__(self, name):
        return getattr(real_time, name)
