"""Helpers for tracing-focused tests that inspect exported JSONL spans."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from vibesensor.app.config_schema import TracingConfig
from vibesensor.shared.tracing import (
    configure_tracing,
    force_flush_tracing,
    shutdown_tracing,
)


@contextmanager
def configured_trace_output(tmp_path: Path, filename: str = "traces.jsonl") -> Iterator[Path]:
    """Enable tracing to a temp JSONL file for the duration of a test block."""

    trace_path = tmp_path / filename
    configure_tracing(TracingConfig(enabled=True, output_path=trace_path))
    try:
        yield trace_path
    finally:
        try:
            force_flush_tracing()
        finally:
            shutdown_tracing()


def read_trace_output(path: Path) -> list[dict[str, object]]:
    """Parse exported JSONL spans from *path* into Python dicts."""

    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
