from __future__ import annotations

import argparse
import asyncio
import json
import time

import websockets


async def run(uri: str, min_clients: int, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(uri) as ws:
                while time.monotonic() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    payload = json.loads(raw)
                    clients = payload.get("clients", [])
                    if isinstance(clients, list) and len(clients) >= min_clients:
                        print(f"WS smoke OK: {len(clients)} clients visible")
                        return
        except Exception:
            await asyncio.sleep(0.5)
    raise RuntimeError(f"Did not receive ws payload with at least {min_clients} clients within timeout")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WebSocket smoke test for VibeSenser")
    parser.add_argument("--uri", default="ws://127.0.0.1:8000/ws")
    parser.add_argument("--min-clients", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run(args.uri, args.min_clients, args.timeout))


if __name__ == "__main__":
    main()

