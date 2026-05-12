"""Per-stage latency tracking. Thread-safe via deque; no external deps."""
from __future__ import annotations

import contextlib
import time
from collections import defaultdict, deque
from typing import Generator

# Stage names used throughout the codebase
STAGE_TOTAL    = "total_request"
STAGE_CACHE    = "cache_lookup"
STAGE_RETRIEVE = "retrieval"
STAGE_LLM      = "llm_call"
STAGE_DB_WRITE = "db_write"
STAGE_RENDER   = "response_render"

_MAX_SAMPLES = 500
_store: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))


def record(stage: str, ms: float) -> None:
    _store[stage].append(ms)


@contextlib.contextmanager
def measure(stage: str) -> Generator[None, None, None]:
    """Context manager that records wall-clock ms for a stage."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        record(stage, (time.perf_counter() - t0) * 1000)


def get_stats() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for stage, samples in _store.items():
        if not samples:
            continue
        s = sorted(samples)
        n = len(s)
        result[stage] = {
            "count": n,
            "p50_ms": round(s[n // 2], 1),
            "p95_ms": round(s[max(0, int(n * 0.95) - 1)], 1),
            "p99_ms": round(s[max(0, int(n * 0.99) - 1)], 1),
            "avg_ms": round(sum(s) / n, 1),
        }
    return result
