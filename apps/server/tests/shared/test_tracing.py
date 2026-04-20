"""Focused tests for the shared OpenTelemetry tracing helpers."""

from __future__ import annotations

import asyncio
from pathlib import Path

from opentelemetry.trace import SpanKind
from test_support.tracing import configured_trace_output, read_trace_output

from vibesensor.shared.tracing import start_span


def test_configured_tracing_writes_jsonl_spans(tmp_path: Path) -> None:
    with configured_trace_output(tmp_path, "app-traces.jsonl") as trace_path:
        with start_span(
            __name__,
            "unit.test.span",
            kind=SpanKind.INTERNAL,
            attributes={"test.value": "ok"},
        ):
            pass
    spans = read_trace_output(trace_path)

    assert len(spans) == 1
    span = spans[0]
    assert span["name"] == "unit.test.span"
    assert span["kind"] == "internal"
    assert span["attributes"]["test.value"] == "ok"
    assert span["resource"]["service.name"] == "vibesensor-server"


def test_async_tasks_keep_parent_trace_context(tmp_path: Path) -> None:
    with configured_trace_output(tmp_path, "app-traces.jsonl") as trace_path:

        async def _run() -> None:
            with start_span(__name__, "trace.parent"):

                async def _child() -> None:
                    with start_span(__name__, "trace.child"):
                        return None

                await asyncio.create_task(_child())

        asyncio.run(_run())
    spans = {span["name"]: span for span in read_trace_output(trace_path)}

    parent = spans["trace.parent"]
    child = spans["trace.child"]
    assert child["trace_id"] == parent["trace_id"]
    assert child["parent_span_id"] == parent["span_id"]
