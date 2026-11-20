"""Optional timing probes for evaluation task profiling."""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from time import perf_counter

TimingProbe = Callable[[str, float], None]


@contextmanager
def timed(probe: TimingProbe | None, name: str) -> Generator[None, None, None]:
    """Measure a block when a probe is supplied; keep normal calls lightweight."""
    if probe is None:
        yield
        return

    started = perf_counter()
    try:
        yield
    finally:
        probe(name, perf_counter() - started)
