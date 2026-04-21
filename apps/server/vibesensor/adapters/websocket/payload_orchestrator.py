"""Per-tick payload build and cache orchestration for WebSocket broadcasts."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Mapping

import anyio

from vibesensor.shared.json_utils import json_text_dumps, sanitize_for_json
from vibesensor.shared.structured_logging import log_extra
from vibesensor.shared.types.payload_types import LiveWsPayload, WsErrorPayload

LOGGER = logging.getLogger("vibesensor.adapters.websocket.hub")

__all__ = ["PayloadBuildOrchestrator"]

_ERROR_PAYLOAD_BODY: WsErrorPayload = {"error": "payload_build_failed"}
_ERROR_PAYLOAD: str = json_text_dumps(_ERROR_PAYLOAD_BODY)
_SELECTED_CLIENT_ID_NULL_JSON = '"selected_client_id":null'


def _dump_json_text(value: object) -> str:
    return json_text_dumps(value)


class PayloadBuildOrchestrator:
    """Own payload build, serialization, cache reuse, and fallback state for one tick."""

    def __init__(
        self,
        payload_builder: Callable[[str | None], LiveWsPayload],
        *,
        capture_debug: bool,
    ) -> None:
        self._payload_builder = payload_builder
        self._payload_cache: dict[str | None, str] = {}
        self._payload_template_cache: dict[tuple[tuple[str, object], ...], str] = {}
        self._pending_payload_events: dict[str | None, anyio.Event] = {}
        self._failed_client_ids: set[str | None] = set()
        self._debug_info: dict[str | None, bool] | None = {} if capture_debug else None

    @property
    def payload_cache(self) -> Mapping[str | None, str]:
        return self._payload_cache

    @property
    def failed_client_ids(self) -> set[str | None]:
        return self._failed_client_ids

    @property
    def debug_info(self) -> dict[str | None, bool] | None:
        return self._debug_info

    def _build_raw_payload(self, selected_client_id: str | None) -> LiveWsPayload | None:
        """Build the raw payload for *selected_client_id* on the event-loop thread."""

        try:
            return self._payload_builder(selected_client_id)
        except (TypeError, ValueError, OverflowError, KeyError, AttributeError, RuntimeError):
            LOGGER.error(
                "WebSocket payload build failed for client %r; "
                "sending error payload to affected connections.",
                selected_client_id,
                exc_info=True,
                extra=log_extra(
                    event="ws_payload_build_failed",
                    selected_client_id=selected_client_id,
                ),
            )
            self._failed_client_ids.add(selected_client_id)
            return None

    @staticmethod
    def _payload_has_per_client_freq(payload: object) -> bool:
        """Return True when *payload* contains per-client frequency data."""

        try:
            spectra = payload.get("spectra") if isinstance(payload, dict) else None
            if isinstance(spectra, dict):
                for _cid, cs in (spectra.get("clients") or {}).items():
                    if isinstance(cs, dict) and cs.get("freq"):
                        return True
        except (AttributeError, TypeError, ValueError, KeyError):
            LOGGER.debug("Debug freq-inspection failed", exc_info=True)
        return False

    def _serialize_payload(
        self,
        selected_client_id: str | None,
        raw_payload: LiveWsPayload,
    ) -> tuple[str, bool, bool | None]:
        """Serialize *raw_payload* off the event loop and report debug metadata."""

        payload_for_debug: object = raw_payload
        _dumps = _dump_json_text
        try:
            try:
                text = self._serialize_selected_client_payload(
                    selected_client_id,
                    raw_payload,
                    _dumps,
                )
            except (TypeError, ValueError, OverflowError):
                payload_for_debug, had_non_finite = sanitize_for_json(raw_payload)
                if had_non_finite:
                    LOGGER.warning(
                        "WebSocket payload for client %r contained NaN/Inf values; "
                        "replaced with null.",
                        selected_client_id,
                        extra=log_extra(
                            event="ws_payload_non_finite_replaced",
                            selected_client_id=selected_client_id,
                        ),
                    )
                text = self._serialize_selected_client_payload(
                    selected_client_id,
                    payload_for_debug,
                    _dumps,
                )
            has_freq = (
                self._payload_has_per_client_freq(payload_for_debug)
                if self._debug_info is not None
                else None
            )
            return text, False, has_freq
        except (TypeError, ValueError, OverflowError, KeyError, AttributeError, RuntimeError):
            LOGGER.error(
                "WebSocket payload build failed for client %r; "
                "sending error payload to affected connections.",
                selected_client_id,
                exc_info=True,
                extra=log_extra(
                    event="ws_payload_serialize_failed",
                    selected_client_id=selected_client_id,
                ),
            )
            return _ERROR_PAYLOAD, True, None

    @staticmethod
    def _payload_template_key(raw_payload: Mapping[str, object]) -> tuple[tuple[str, object], ...]:
        key_parts: list[tuple[str, object]] = []
        for field, value in raw_payload.items():
            if field == "selected_client_id":
                continue
            if value is None or isinstance(value, str | int | float | bool):
                key_parts.append((field, value))
            else:
                key_parts.append((field, id(value)))
        return tuple(key_parts)

    def _serialize_selected_client_payload(
        self,
        selected_client_id: str | None,
        raw_payload: object,
        dumps: Callable[[object], str],
    ) -> str:
        if not isinstance(raw_payload, dict) or "selected_client_id" not in raw_payload:
            return dumps(raw_payload)
        template_key = self._payload_template_key(raw_payload)
        template_text = self._payload_template_cache.get(template_key)
        if template_text is None:
            template_text = dumps(
                {
                    **raw_payload,
                    "selected_client_id": None,
                },
            )
            self._payload_template_cache[template_key] = template_text
        if selected_client_id is None:
            return template_text
        selected_client_text = dumps(selected_client_id)
        selected_client_payload = template_text.replace(
            _SELECTED_CLIENT_ID_NULL_JSON,
            f'"selected_client_id":{selected_client_text}',
            1,
        )
        if selected_client_payload != template_text:
            return selected_client_payload
        return dumps(raw_payload)

    async def prepare(self, selected_client_ids: Iterable[str | None]) -> None:
        """Prime cached payloads for the current snapshot's unique client selections."""

        unique_selected_ids = list(dict.fromkeys(selected_client_ids))
        raw_payloads: dict[str | None, LiveWsPayload] = {}

        for selected_client_id in unique_selected_ids:
            raw_payload = self._build_raw_payload(selected_client_id)
            if raw_payload is None:
                self._payload_cache[selected_client_id] = _ERROR_PAYLOAD
                continue
            raw_payloads[selected_client_id] = raw_payload

        if not raw_payloads:
            return

        serialized_payloads: dict[str | None, tuple[str, bool, bool | None]] = {}

        async def _serialize_one(
            selected_client_id: str | None,
            raw_payload: LiveWsPayload,
        ) -> None:
            serialized_payloads[selected_client_id] = await anyio.to_thread.run_sync(
                self._serialize_payload,
                selected_client_id,
                raw_payload,
            )

        async with anyio.create_task_group() as task_group:
            for selected_client_id, raw_payload in raw_payloads.items():
                task_group.start_soon(_serialize_one, selected_client_id, raw_payload)

        for selected_client_id in raw_payloads:
            text, failed, has_freq = serialized_payloads[selected_client_id]
            self._payload_cache[selected_client_id] = text
            if failed:
                self._failed_client_ids.add(selected_client_id)
            if self._debug_info is not None and has_freq is not None:
                self._debug_info[selected_client_id] = has_freq

    async def _build_payload_text(self, selected_client_id: str | None) -> str:
        """Build and serialize payload text for *selected_client_id* once for the tick."""

        raw_payload = self._build_raw_payload(selected_client_id)
        if raw_payload is None:
            self._payload_cache[selected_client_id] = _ERROR_PAYLOAD
            return _ERROR_PAYLOAD
        text, failed, has_freq = await anyio.to_thread.run_sync(
            self._serialize_payload,
            selected_client_id,
            raw_payload,
        )
        self._payload_cache[selected_client_id] = text
        if failed:
            self._failed_client_ids.add(selected_client_id)
        if self._debug_info is not None and has_freq is not None:
            self._debug_info[selected_client_id] = has_freq
        return text

    async def get_or_build_payload_text(self, selected_client_id: str | None) -> str:
        """Return cached payload text or build it once for the current tick."""

        cached = self._payload_cache.get(selected_client_id)
        if cached is not None:
            return cached
        pending = self._pending_payload_events.get(selected_client_id)
        if pending is None:
            pending = anyio.Event()
            self._pending_payload_events[selected_client_id] = pending
            try:
                return await self._build_payload_text(selected_client_id)
            finally:
                pending.set()
                if self._pending_payload_events.get(selected_client_id) is pending:
                    self._pending_payload_events.pop(selected_client_id, None)
        await pending.wait()
        return self._payload_cache.get(selected_client_id, _ERROR_PAYLOAD)
