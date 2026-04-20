"""Optional OpenTelemetry tracing helpers for backend runtime flows."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

LOGGER = logging.getLogger(__name__)

_SERVICE_NAME = "vibesensor-server"
_EXPORT_BATCH_SIZE = 256
_EXPORT_DELAY_MS = 200
_SHUTDOWN_TIMEOUT_MS = 3_000

type TracingAttributeValue = (
    str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]
)


class TracingSettings(Protocol):
    enabled: bool
    output_path: Path


def _json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)


def _span_hex(span_id: int) -> str:
    return f"{span_id:016x}"


def _trace_hex(trace_id: int) -> str:
    return f"{trace_id:032x}"


def _span_payload(span: ReadableSpan) -> dict[str, object]:
    parent = span.parent
    duration_ms: float | None = None
    if span.start_time is not None and span.end_time is not None:
        duration_ms = round((span.end_time - span.start_time) / 1_000_000, 3)
    return {
        "name": span.name,
        "trace_id": _trace_hex(span.context.trace_id),
        "span_id": _span_hex(span.context.span_id),
        "parent_span_id": _span_hex(parent.span_id) if parent is not None else None,
        "kind": span.kind.name.lower(),
        "start_time_unix_nano": span.start_time,
        "end_time_unix_nano": span.end_time,
        "duration_ms": duration_ms,
        "status": span.status.status_code.name.lower(),
        "status_description": span.status.description or None,
        "attributes": {key: _json_value(value) for key, value in (span.attributes or {}).items()},
        "events": [
            {
                "name": event.name,
                "timestamp_unix_nano": event.timestamp,
                "attributes": {
                    key: _json_value(value) for key, value in (event.attributes or {}).items()
                },
            }
            for event in span.events
        ],
        "resource": {
            str(key): _json_value(value) for key, value in span.resource.attributes.items()
        },
    }


class JsonlSpanExporter(SpanExporter):
    """Append completed spans to a JSONL file for offline inspection."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock, self._path.open("a", encoding="utf-8") as handle:
                for span in spans:
                    handle.write(json.dumps(_span_payload(span), ensure_ascii=True, sort_keys=True))
                    handle.write("\n")
        except OSError:
            LOGGER.warning(
                "Failed to export spans to %s",
                self._path,
                exc_info=True,
            )
            return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        return None


@dataclass(slots=True)
class _TracingRuntime:
    provider: TracerProvider
    processor: BatchSpanProcessor | None
    exporter: JsonlSpanExporter | None
    enabled: bool


def _build_runtime(*, enabled: bool, output_path: Path | None) -> _TracingRuntime:
    provider = TracerProvider(
        sampler=ALWAYS_ON if enabled else ALWAYS_OFF,
        resource=Resource.create({"service.name": _SERVICE_NAME}),
    )
    processor: BatchSpanProcessor | None = None
    exporter: JsonlSpanExporter | None = None
    if enabled and output_path is not None:
        exporter = JsonlSpanExporter(output_path)
        processor = BatchSpanProcessor(
            exporter,
            max_export_batch_size=_EXPORT_BATCH_SIZE,
            schedule_delay_millis=_EXPORT_DELAY_MS,
        )
        provider.add_span_processor(processor)
    return _TracingRuntime(
        provider=provider,
        processor=processor,
        exporter=exporter,
        enabled=enabled,
    )


_RUNTIME = _build_runtime(enabled=False, output_path=None)


def configure_tracing(settings: TracingSettings | None) -> None:
    """Install the canonical tracing runtime from *settings*."""

    global _RUNTIME
    previous = _RUNTIME
    enabled = bool(settings.enabled) if settings is not None else False
    output_path = settings.output_path if settings is not None else None
    _RUNTIME = _build_runtime(enabled=enabled, output_path=output_path)
    previous.provider.shutdown()


def force_flush_tracing() -> None:
    """Flush completed spans to disk when tracing is enabled."""

    if _RUNTIME.processor is None:
        return
    _RUNTIME.processor.force_flush(timeout_millis=_SHUTDOWN_TIMEOUT_MS)


def shutdown_tracing() -> None:
    """Flush and stop the current tracing runtime."""

    global _RUNTIME
    current = _RUNTIME
    _RUNTIME = _build_runtime(enabled=False, output_path=None)
    current.provider.shutdown()


def tracing_enabled() -> bool:
    """Return whether span export is currently enabled."""

    return _RUNTIME.enabled


def _coerce_span_attribute(value: object) -> TracingAttributeValue:
    if isinstance(value, str | bool | int | float):
        return value
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if all(isinstance(item, str) for item in value):
            return [item for item in value]
        if all(isinstance(item, bool) for item in value):
            return [item for item in value]
        if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
            return [item for item in value]
        if all(isinstance(item, float) for item in value):
            return [item for item in value]
    return str(value)


@contextmanager
def start_span(
    tracer_name: str,
    span_name: str,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    attributes: Mapping[str, object] | None = None,
) -> Iterator[Span]:
    tracer = _RUNTIME.provider.get_tracer(tracer_name)
    with tracer.start_as_current_span(span_name, kind=kind) as span:
        for key, value in (attributes or {}).items():
            span.set_attribute(key, _coerce_span_attribute(value))
        yield span


def mark_span_error(span: Span, exc: BaseException) -> None:
    """Record *exc* on *span* and mark it failed when the span is recording."""

    if not span.is_recording():
        return
    span.record_exception(exc)
    span.set_status(Status(StatusCode.ERROR, str(exc)))
