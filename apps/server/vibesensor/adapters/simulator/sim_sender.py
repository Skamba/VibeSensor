from __future__ import annotations

import argparse
import asyncio
import contextlib
import subprocess
import sys
from pathlib import Path
from typing import Any

from vibesensor.adapters.simulator.commands import (
    apply_engine_order_scenario,
    apply_one_wheel_mild_scenario,
    apply_road_fixed_scenario,
    choose_default_profile,
)
from vibesensor.adapters.simulator.profiles import DEFAULT_ORDER_HZ, DEFAULT_SPEED_KMH
from vibesensor.adapters.simulator.scripted_scenario_library import (
    SCRIPTED_SCENARIOS,
    is_scripted_scenario,
    scripted_scenario_help,
    scripted_scenario_names,
)
from vibesensor.adapters.simulator.scripted_scenarios import run_scripted_scenario
from vibesensor.adapters.simulator.scripted_targeting import apply_phase
from vibesensor.adapters.simulator.server_http import (
    maybe_start_server,
    set_server_speed_override_kmh,
)
from vibesensor.adapters.simulator.sim_client import SimClient, make_client_id
from vibesensor.adapters.simulator.sim_runtime import (
    auto_stop,
    command_loop,
    road_scene_loop,
    run_client,
)

ROOT = Path(__file__).resolve().parents[3]
_STATIC_SCENARIOS: tuple[str, ...] = ("road", "one-wheel-mild", "engine-order", "road-fixed")


async def async_main(args: argparse.Namespace) -> None:
    managed_server: subprocess.Popen[str] | None = None
    if not args.no_auto_server:
        managed_server = maybe_start_server(args, ROOT)

    names = [n.strip() for n in args.names.split(",") if n.strip()] if args.names else []
    while len(names) < args.count:
        names.append(f"sim-{len(names) + 1}")

    clients = [
        SimClient(
            name=names[i],
            client_id=make_client_id(i + 1),
            control_port=args.client_control_base + i,
            sample_rate_hz=args.sample_rate_hz,
            frame_samples=args.frame_samples,
            server_host=args.server_host,
            server_data_port=args.server_data_port,
            server_control_port=args.server_control_port,
            profile_name=choose_default_profile(i),
            noise_floor_std=args.sensor_noise_floor,
        )
        for i in range(args.count)
    ]

    if args.scenario == "one-wheel-mild":
        apply_one_wheel_mild_scenario(clients, args.fault_wheel)
    elif args.scenario == "engine-order":
        apply_engine_order_scenario(clients)
    elif args.scenario == "road-fixed":
        apply_road_fixed_scenario(clients)
    elif is_scripted_scenario(args.scenario):
        initial_phase = SCRIPTED_SCENARIOS[args.scenario].phases[0]
        apply_phase(clients, args.scenario, initial_phase)
        for client in clients:
            client.current_speed_kmh = initial_phase.speed_start_kmh

    override_speed_kmh = max(0.0, float(args.speed_kmh))
    if override_speed_kmh > 0.0 and not is_scripted_scenario(args.scenario):
        applied_speed = set_server_speed_override_kmh(
            args.server_host,
            args.server_http_port,
            override_speed_kmh,
            args.server_check_timeout,
        )
        shown_speed = applied_speed if applied_speed is not None else override_speed_kmh
        # Propagate speed to all clients so order-based profiles scale tones.
        for client in clients:
            client.current_speed_kmh = override_speed_kmh
        print(f"Applied server speed override: {shown_speed:.1f} km/h")

    interactive = args.interactive or (
        not args.no_interactive and args.duration <= 0 and sys.stdin.isatty()
    )
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task[Any]] = []
    server_url = f"http://{args.server_host}"
    if int(args.server_http_port) != 80:
        server_url = f"{server_url}:{args.server_http_port}"

    print(
        f"Starting {len(clients)} simulated clients -> "
        f"{args.server_host}:{args.server_data_port} (open {server_url}) "
        f"rate={args.sample_rate_hz}Hz frame={args.frame_samples} samples "
        f"({args.sample_rate_hz / max(1, args.frame_samples):.2f} fps)"
    )
    print(
        "Default order tones: "
        f"wheel1={DEFAULT_ORDER_HZ['wheel_1x']:.3f}Hz "
        f"wheel2={DEFAULT_ORDER_HZ['wheel_2x']:.3f}Hz "
        f"shaft1={DEFAULT_ORDER_HZ['shaft_1x']:.3f}Hz "
        f"engine1={DEFAULT_ORDER_HZ['engine_1x']:.3f}Hz "
        f"engine2={DEFAULT_ORDER_HZ['engine_2x']:.3f}Hz"
    )
    print("\n".join(c.summary() for c in clients))

    try:
        if is_scripted_scenario(args.scenario):
            tasks.append(
                asyncio.create_task(
                    run_scripted_scenario(
                        clients,
                        args.scenario,
                        stop_event,
                        server_host=args.server_host,
                        server_http_port=args.server_http_port,
                        server_check_timeout=args.server_check_timeout,
                    )
                )
            )
        for client in clients:
            tasks.append(asyncio.create_task(run_client(client, args.hello_interval, stop_event)))
        if args.scenario == "road" and not args.no_road_scene:
            tasks.append(asyncio.create_task(road_scene_loop(clients, stop_event)))
        elif is_scripted_scenario(args.scenario):
            print(f"[scenario] scripted={args.scenario} (complex speed/profile timeline enabled)")
        else:
            print(
                f"[scenario] fixed={args.scenario} fault_wheel={args.fault_wheel} "
                "(no road-scene randomization)"
            )
        if args.duration > 0:
            tasks.append(asyncio.create_task(auto_stop(args.duration, stop_event)))
        if interactive:
            tasks.append(asyncio.create_task(command_loop(clients, stop_event)))
        await stop_event.wait()
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if managed_server is not None:
            managed_server.terminate()
            try:
                managed_server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                managed_server.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="VibeSensor UDP simulator",
        epilog=(
            "Scripted scenarios with temporary vibrations and speed sweeps:\n"
            f"{scripted_scenario_help()}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--server-host", default="127.0.0.1")
    parser.add_argument("--server-data-port", type=int, default=9000)
    parser.add_argument("--server-control-port", type=int, default=9001)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--names", default="front-left,front-right,rear-left,rear-right,trunk")
    parser.add_argument("--sample-rate-hz", type=int, default=800)
    parser.add_argument("--frame-samples", type=int, default=200)
    parser.add_argument("--hello-interval", type=float, default=2.0)
    parser.add_argument(
        "--sensor-noise-floor",
        type=float,
        default=3.5,
        help="Per-sensor always-on broadband noise floor (raw sample units).",
    )
    parser.add_argument("--client-control-base", type=int, default=9100)
    parser.add_argument(
        "--duration", type=float, default=0.0, help="Optional run duration in seconds"
    )
    parser.add_argument(
        "--speed-kmh",
        type=float,
        default=DEFAULT_SPEED_KMH,
        help="Server manual speed override (km/h) applied before run",
    )
    parser.add_argument(
        "--scenario",
        choices=(*_STATIC_SCENARIOS, *scripted_scenario_names()),
        default="road",
        help=(
            "Simulation scenario: random road scene, deterministic mild "
            "single-wheel fault, deterministic engine-order excitation, "
            "fixed road baseline, or one of the scripted multi-phase runs"
        ),
    )
    parser.add_argument(
        "--fault-wheel",
        default="front-right",
        help="Client name to apply the mild wheel fault to when --scenario one-wheel-mild",
    )
    parser.add_argument("--interactive", action="store_true", help="Force interactive command mode")
    parser.add_argument(
        "--no-interactive", action="store_true", help="Disable interactive command mode"
    )
    parser.add_argument(
        "--no-road-scene",
        action="store_true",
        help="Disable the road-scene randomization loop (for scripted/deterministic runs)",
    )
    parser.add_argument(
        "--no-auto-server",
        action="store_true",
        help="Disable local server auto-start check",
    )
    parser.add_argument(
        "--server-http-port",
        type=int,
        default=8000,
        help="HTTP port for server health check",
    )
    parser.add_argument(
        "--server-config",
        default="apps/server/config.dev.yaml",
        help="Config path used when auto-starting server",
    )
    parser.add_argument(
        "--server-start-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for auto-started server readiness",
    )
    parser.add_argument(
        "--server-check-timeout",
        type=float,
        default=1.0,
        help="Per-check HTTP timeout in seconds",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
