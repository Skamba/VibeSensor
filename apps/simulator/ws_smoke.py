from __future__ import annotations

import argparse
import asyncio
import json
import time
from typing import Any

import websockets


def _client_ids(payload: dict[str, Any]) -> list[str]:
    clients = payload.get("clients")
    if not isinstance(clients, list):
        return []
    out: list[str] = []
    for row in clients:
        if isinstance(row, dict):
            client_id = row.get("id")
            if isinstance(client_id, str):
                out.append(client_id)
    return out


async def run(
    uri: str,
    min_clients: int,
    timeout_s: float,
    debug: bool,
    report_every_s: float,
) -> None:
    deadline = time.monotonic() + timeout_s
    attempt = 0
    recv_count = 0
    last_report_ts = 0.0
    last_exception: str | None = None
    last_payload_summary = "no payload received"
    while time.monotonic() < deadline:
        attempt += 1
        if debug:
            remaining = max(0.0, deadline - time.monotonic())
            print(
                f"[ws_smoke] connect attempt={attempt} uri={uri} remaining={remaining:.1f}s",
            )
        try:
            async with websockets.connect(uri) as ws:
                while time.monotonic() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    payload = json.loads(raw)
                    recv_count += 1
                    client_ids = _client_ids(payload)
                    last_payload_summary = (
                        f"clients={len(client_ids)} ids={client_ids} "
                        f"selected={payload.get('selected_client_id')!r}"
                    )
                    if debug and (
                        (time.monotonic() - last_report_ts) >= max(0.1, report_every_s)
                    ):
                        last_report_ts = time.monotonic()
                        print(f"[ws_smoke] recv#{recv_count} {last_payload_summary}")
                    if len(client_ids) >= min_clients:
                        print(f"WS smoke OK: {len(client_ids)} clients visible")
                        return
        except Exception as exc:  # noqa: BLE001
            last_exception = f"{type(exc).__name__}: {exc}"
            if debug:
                print(f"[ws_smoke] connection/read error: {last_exception}")
            await asyncio.sleep(0.5)
    raise RuntimeError(
        "Did not receive ws payload with at least "
        f"{min_clients} clients within timeout. "
        f"attempts={attempt} recv_count={recv_count} "
        f"last_exception={last_exception!r} last_payload={last_payload_summary}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WebSocket smoke test for VibeSensor")
    parser.add_argument("--uri", default="ws://127.0.0.1:8000/ws")
    parser.add_argument("--min-clients", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--report-every", type=float, default=2.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(
        run(
            args.uri,
            args.min_clients,
            args.timeout,
            args.debug,
            args.report_every,
        )
    )


if __name__ == "__main__":
    main()
