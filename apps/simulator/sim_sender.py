from __future__ import annotations

import argparse
import asyncio
import json
import random
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "apps" / "server"))

from vibesensor.analysis_settings import (  # noqa: E402
    DEFAULT_ANALYSIS_SETTINGS,
    tire_circumference_m_from_spec,
    wheel_hz_from_speed_mps,
)
from vibesensor.constants import KMH_TO_MPS  # noqa: E402
from vibesensor.protocol import (  # noqa: E402
    CMD_IDENTIFY,
    MSG_CMD,
    client_id_mac,
    pack_ack,
    pack_data,
    pack_hello,
    parse_cmd,
)

DEFAULT_SPEED_KMH = 100.0
# Vehicle defaults imported from the canonical source of truth.
DEFAULT_TIRE_WIDTH_MM = DEFAULT_ANALYSIS_SETTINGS["tire_width_mm"]
DEFAULT_TIRE_ASPECT_PCT = DEFAULT_ANALYSIS_SETTINGS["tire_aspect_pct"]
DEFAULT_RIM_IN = DEFAULT_ANALYSIS_SETTINGS["rim_in"]
DEFAULT_FINAL_DRIVE = DEFAULT_ANALYSIS_SETTINGS["final_drive_ratio"]
DEFAULT_GEAR_RATIO = DEFAULT_ANALYSIS_SETTINGS["current_gear_ratio"]


def _calc_default_orders() -> dict[str, float]:
    speed_mps = DEFAULT_SPEED_KMH * KMH_TO_MPS
    circumference = tire_circumference_m_from_spec(
        DEFAULT_TIRE_WIDTH_MM, DEFAULT_TIRE_ASPECT_PCT, DEFAULT_RIM_IN
    )
    if circumference is None:
        raise ValueError("Failed to compute tire circumference from default specs")
    whz = wheel_hz_from_speed_mps(speed_mps, circumference)
    if whz is None:
        raise ValueError("Failed to compute wheel Hz from default speed/circumference")
    wheel_1x = whz
    shaft_1x = wheel_1x * DEFAULT_FINAL_DRIVE
    engine_1x = shaft_1x * DEFAULT_GEAR_RATIO
    return {
        "wheel_1x": float(wheel_1x),
        "wheel_2x": float(wheel_1x * 2.0),
        "shaft_1x": float(shaft_1x),
        "engine_1x": float(engine_1x),
        "engine_2x": float(engine_1x * 2.0),
    }


DEFAULT_ORDER_HZ = _calc_default_orders()
LOCAL_SERVER_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    tones: tuple[tuple[float, tuple[float, float, float]], ...]
    noise_std: float
    bump_probability: float
    bump_decay: float
    bump_strength: tuple[float, float, float]
    modulation_hz: float
    modulation_depth: float


PROFILE_LIBRARY: dict[str, Profile] = {
    "engine_idle": Profile(
        name="engine_idle",
        tones=(
            (13.0, (170.0, 120.0, 250.0)),
            (26.0, (55.0, 40.0, 85.0)),
            (39.0, (30.0, 24.0, 45.0)),
        ),
        noise_std=22.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(18.0, 15.0, 28.0),
        modulation_hz=0.35,
        modulation_depth=0.10,
    ),
    "rough_road": Profile(
        name="rough_road",
        tones=(
            (8.0, (80.0, 90.0, 130.0)),
            (15.0, (105.0, 95.0, 140.0)),
            (34.0, (55.0, 45.0, 85.0)),
        ),
        noise_std=28.0,
        bump_probability=0.012,
        bump_decay=0.92,
        bump_strength=(45.0, 55.0, 80.0),
        modulation_hz=0.45,
        modulation_depth=0.16,
    ),
    "wheel_imbalance": Profile(
        name="wheel_imbalance",
        tones=(
            # Keep wheel signatures aligned to the same order model used by
            # live/report diagnostics so simulated wheel faults classify reliably.
            (DEFAULT_ORDER_HZ["wheel_1x"], (220.0, 125.0, 170.0)),
            (DEFAULT_ORDER_HZ["wheel_2x"], (80.0, 52.0, 72.0)),
            (DEFAULT_ORDER_HZ["wheel_1x"] * 0.52, (24.0, 18.0, 30.0)),
        ),
        noise_std=24.0,
        bump_probability=0.004,
        bump_decay=0.94,
        bump_strength=(30.0, 24.0, 45.0),
        modulation_hz=0.22,
        modulation_depth=0.12,
    ),
    "wheel_mild_imbalance": Profile(
        name="wheel_mild_imbalance",
        tones=(
            # Slight wheel issue: mostly a stable 1x wheel-order tone with
            # a weaker 2x harmonic and very low subharmonic content.
            (DEFAULT_ORDER_HZ["wheel_1x"], (105.0, 62.0, 80.0)),
            (DEFAULT_ORDER_HZ["wheel_2x"], (28.0, 18.0, 24.0)),
            (DEFAULT_ORDER_HZ["wheel_1x"] * 0.52, (8.0, 6.0, 10.0)),
        ),
        noise_std=14.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(10.0, 8.0, 14.0),
        modulation_hz=0.18,
        modulation_depth=0.08,
    ),
    "rear_body": Profile(
        name="rear_body",
        tones=(
            (6.5, (70.0, 88.0, 120.0)),
            (14.0, (48.0, 60.0, 82.0)),
            (28.0, (34.0, 28.0, 50.0)),
        ),
        noise_std=22.0,
        bump_probability=0.006,
        bump_decay=0.95,
        bump_strength=(30.0, 34.0, 50.0),
        modulation_hz=0.28,
        modulation_depth=0.14,
    ),
}


@dataclass(slots=True)
class SimClient:
    name: str
    client_id: bytes
    control_port: int
    sample_rate_hz: int
    frame_samples: int
    server_host: str
    server_data_port: int
    server_control_port: int
    profile_name: str
    seq: int = 0
    phase_s: float = 0.0
    amp_scale: float = 1.0
    noise_scale: float = 1.0
    scene_gain: float = 1.0
    scene_noise_gain: float = 1.0
    scene_mode: str = "all"
    common_event_gain: float = 0.0
    paused: bool = False
    send_period_scale: float = 1.0
    send_jitter_s: float = 0.0
    start_offset_s: float = 0.0
    control_transport: asyncio.DatagramTransport | None = None
    data_transport: asyncio.DatagramTransport | None = None
    bump_state: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=np.float32)
    )
    phase_offsets: np.ndarray = field(
        default_factory=lambda: np.zeros(3, dtype=np.float32)
    )
    rng: np.random.Generator | None = None

    def __post_init__(self) -> None:
        seed = int.from_bytes(self.client_id, "little")
        self.rng = np.random.default_rng(seed)
        self.phase_offsets = np.asarray(
            self.rng.uniform(0.0, np.pi, size=3), dtype=np.float32
        )
        # Intentional slight timing mismatch between sensors to mimic real deployments.
        self.send_period_scale = float(self.rng.uniform(0.997, 1.003))
        self.send_jitter_s = float(self.rng.uniform(0.001, 0.007))
        self.start_offset_s = float(self.rng.uniform(0.0, 0.045))

    @property
    def profile(self) -> Profile:
        return PROFILE_LIBRARY[self.profile_name]

    @property
    def mac_address(self) -> str:
        return client_id_mac(self.client_id)

    def pulse(self, strength: float) -> None:
        vec = np.asarray(self.profile.bump_strength, dtype=np.float32)
        self.bump_state += vec * np.float32(strength)

    def summary(self) -> str:
        return (
            f"{self.name} id={self.client_id.hex()} mac={self.mac_address} profile={self.profile_name} "
            f"amp={self.amp_scale:.2f} noise={self.noise_scale:.2f} "
            f"scene={self.scene_mode}:{self.scene_gain:.2f} "
            f"common={self.common_event_gain:.2f} paused={self.paused} "
            f"tx_scale={self.send_period_scale:.5f} "
            f"tx_jitter={self.send_jitter_s * 1000:.1f}ms "
            f"offset={self.start_offset_s * 1000:.1f}ms"
        )

    def make_frame(self) -> np.ndarray:
        if self.paused:
            self.phase_s += self.frame_samples / self.sample_rate_hz
            return np.zeros((self.frame_samples, 3), dtype=np.int16)

        assert self.rng is not None  # guaranteed by __post_init__
        profile = self.profile

        dt = 1.0 / self.sample_rate_hz
        t = self.phase_s + np.arange(self.frame_samples, dtype=np.float32) * dt

        modulation = 1.0 + profile.modulation_depth * np.sin(
            2 * np.pi * profile.modulation_hz * t
        )
        signal = np.zeros((self.frame_samples, 3), dtype=np.float32)

        for freq_hz, amps_xyz in profile.tones:
            omega_t = 2.0 * np.pi * freq_hz * t
            signal[:, 0] += amps_xyz[0] * np.sin(omega_t + self.phase_offsets[0])
            signal[:, 1] += amps_xyz[1] * np.sin(omega_t + self.phase_offsets[1])
            signal[:, 2] += amps_xyz[2] * np.sin(omega_t + self.phase_offsets[2])

        if self.common_event_gain > 0:
            # Exact orders for defaults: 285/30R21, 3.15 FD, 1.0 gear, 100 km/h.
            common_tones = (
                (DEFAULT_ORDER_HZ["wheel_1x"], (70.0, 58.0, 82.0)),
                (DEFAULT_ORDER_HZ["wheel_2x"], (46.0, 38.0, 54.0)),
                (DEFAULT_ORDER_HZ["shaft_1x"], (95.0, 76.0, 110.0)),
                (DEFAULT_ORDER_HZ["engine_2x"], (64.0, 52.0, 78.0)),
            )
            for freq_hz, amps_xyz in common_tones:
                omega_t = 2.0 * np.pi * freq_hz * t
                signal[:, 0] += self.common_event_gain * amps_xyz[0] * np.sin(omega_t)
                signal[:, 1] += (
                    self.common_event_gain * amps_xyz[1] * np.sin(omega_t + 0.2)
                )
                signal[:, 2] += (
                    self.common_event_gain * amps_xyz[2] * np.sin(omega_t + 0.4)
                )

        signal *= modulation[:, None]

        for i in range(self.frame_samples):
            if self.rng.random() < profile.bump_probability:
                jitter = self.rng.uniform(0.85, 1.15, size=3).astype(np.float32)
                self.bump_state += (
                    np.asarray(profile.bump_strength, dtype=np.float32) * jitter
                )
            signal[i] += self.bump_state
            self.bump_state *= profile.bump_decay

        noise = self.rng.normal(
            0.0,
            profile.noise_std * self.noise_scale * self.scene_noise_gain,
            size=signal.shape,
        ).astype(np.float32)
        signal += noise
        signal *= self.amp_scale * self.scene_gain

        self.phase_s = float(t[-1] + dt)
        return np.clip(signal, -32768, 32767).astype(np.int16)


class ClientProtocol(asyncio.DatagramProtocol):
    def __init__(self, sim: SimClient):
        self.sim = sim

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.sim.control_transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if not data or data[0] != MSG_CMD:
            return
        try:
            cmd = parse_cmd(data)
        except Exception as exc:
            print(
                f"{self.sim.name}: ignoring unparseable command from {addr[0]}:{addr[1]}: {exc}"
            )
            return
        if cmd.client_id != self.sim.client_id:
            return
        if cmd.cmd_id == CMD_IDENTIFY:
            duration_ms = (
                int.from_bytes(cmd.params[:2], "little")
                if len(cmd.params) >= 2
                else 1000
            )
            print(f"{self.sim.name}: identify {duration_ms}ms from {addr[0]}:{addr[1]}")
            self.sim.pulse(1.4)
            ack = pack_ack(self.sim.client_id, cmd.cmd_seq, status=0)
            if self.sim.control_transport is not None:
                self.sim.control_transport.sendto(
                    ack, (self.sim.server_host, self.sim.server_control_port)
                )


class DataProtocol(asyncio.DatagramProtocol):
    def __init__(self, sim: SimClient):
        self.sim = sim

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.sim.data_transport = transport  # type: ignore[assignment]


def make_client_id(seed: int) -> bytes:
    rng = random.Random(seed)
    return bytes(
        [
            0x02,  # locally administered unicast
            0x5A,
            rng.randrange(0, 255),
            rng.randrange(0, 255),
            rng.randrange(0, 255),
            seed & 0xFF,
        ]
    )


def _normalize_http_host(host: str) -> str:
    if host == "0.0.0.0":
        return "127.0.0.1"
    return host


def _server_health_url(host: str, port: int) -> str:
    return f"http://{_normalize_http_host(host)}:{port}/api/clients"


def _speed_override_url(host: str, port: int) -> str:
    return f"http://{_normalize_http_host(host)}:{port}/api/simulator/speed-override"


def _check_server_running(host: str, port: int, timeout_s: float = 1.0) -> bool:
    url = _server_health_url(host, port)
    try:
        with urlopen(url, timeout=timeout_s) as resp:
            return resp.status == 200
    except (URLError, OSError, TimeoutError):
        return False


def set_server_speed_override_kmh(
    host: str, port: int, speed_kmh: float, timeout_s: float
) -> float | None:
    payload = json.dumps({"speed_kmh": float(speed_kmh)}).encode("utf-8")
    req = Request(
        _speed_override_url(host, port),
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout_s) as resp:
        body = resp.read()
    parsed = json.loads(body.decode("utf-8")) if body else {}
    value = parsed.get("speed_kmh")
    return float(value) if isinstance(value, (int, float)) else None


def _start_local_server(config_path: Path) -> subprocess.Popen[str]:
    cmd = [sys.executable, "-m", "vibesensor.app", "--config", str(config_path)]
    return subprocess.Popen(cmd, cwd=str(ROOT / "pi"))


def maybe_start_server(args: argparse.Namespace) -> subprocess.Popen[str] | None:
    host = args.server_host.strip().lower()
    if host not in LOCAL_SERVER_HOSTS:
        print(
            f"Auto-start skipped: server host {args.server_host!r} is not local. "
            "Start the server manually on that host."
        )
        return None

    for _ in range(5):
        if _check_server_running(
            args.server_host,
            args.server_http_port,
            timeout_s=args.server_check_timeout,
        ):
            print(
                "Server already running at "
                f"{_server_health_url(args.server_host, args.server_http_port)}"
            )
            return None
        time.sleep(0.2)

    if _check_server_running(
        args.server_host, args.server_http_port, timeout_s=args.server_check_timeout
    ):
        print(
            f"Server already running at {_server_health_url(args.server_host, args.server_http_port)}"
        )
        return None

    config_path = Path(args.server_config)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    print(f"Server not reachable. Starting local app with config: {config_path}")
    proc = _start_local_server(config_path)
    deadline = time.monotonic() + args.server_start_timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            # If another process already owns the port, a second start can fail
            # quickly even though the original server is healthy.
            if _check_server_running(
                args.server_host,
                args.server_http_port,
                timeout_s=args.server_check_timeout,
            ):
                print(
                    "Detected existing healthy server after auto-start race at "
                    f"{_server_health_url(args.server_host, args.server_http_port)}"
                )
                return None
            raise RuntimeError(
                f"Auto-started server exited early with code {proc.returncode}"
            )
        if _check_server_running(
            args.server_host, args.server_http_port, timeout_s=args.server_check_timeout
        ):
            print(
                f"Server is now reachable at {_server_health_url(args.server_host, args.server_http_port)}"
            )
            return proc
        time.sleep(0.3)
    proc.terminate()
    raise RuntimeError("Auto-started server did not become ready before timeout")


def choose_default_profile(index: int) -> str:
    ordered = ("engine_idle", "wheel_imbalance", "rear_body", "rough_road")
    return ordered[index % len(ordered)]


def apply_one_wheel_mild_scenario(clients: list[SimClient], fault_wheel: str) -> None:
    """Configure a deterministic scenario with one slight wheel fault.

    Non-fault sensors remain quiet/low-gain while the selected wheel carries
    a mild 1x-dominant wheel-order signature.
    """
    target = fault_wheel.strip().lower()
    for client in clients:
        normalized_name = client.name.strip().lower()
        client.common_event_gain = 0.0
        client.scene_mode = "one-wheel-mild"
        if normalized_name == target:
            client.profile_name = "wheel_mild_imbalance"
            client.scene_gain = 0.58
            client.scene_noise_gain = 0.82
            client.amp_scale = 1.0
            client.noise_scale = 1.0
            client.pulse(0.35)
        else:
            client.profile_name = "engine_idle"
            client.scene_gain = 0.05
            client.scene_noise_gain = 0.75
            client.amp_scale = 0.18
            client.noise_scale = 0.85


def find_targets(clients: list[SimClient], token: str) -> list[SimClient]:
    target = token.strip().lower()
    if target == "all":
        return clients
    by_name = [c for c in clients if c.name.lower() == target]
    if by_name:
        return by_name
    by_id = [c for c in clients if c.client_id.hex() == target]
    if by_id:
        return by_id
    by_mac = [c for c in clients if c.mac_address == target]
    if by_mac:
        return by_mac
    return []


def apply_command(
    clients: list[SimClient], line: str, stop_event: asyncio.Event
) -> str:
    parts = shlex.split(line)
    if not parts:
        return ""

    cmd = parts[0].lower()
    if cmd in {"quit", "exit"}:
        stop_event.set()
        return "Stopping simulator..."
    if cmd == "help":
        return (
            "Commands: list | profiles | pause <target> | resume <target> | "
            "pulse <target> [strength] | set <target> profile <name> | "
            "set <target> amp <float> | set <target> noise <float> | quit"
        )
    if cmd == "list":
        return "\n".join(c.summary() for c in clients)
    if cmd == "profiles":
        return "Available profiles: " + ", ".join(PROFILE_LIBRARY.keys())

    if len(parts) < 2:
        return "Missing target. Try: help"

    targets = find_targets(clients, parts[1])
    if not targets:
        return f"No client matches target: {parts[1]!r}"

    if cmd == "pause":
        for c in targets:
            c.paused = True
        return f"Paused {len(targets)} client(s)."

    if cmd == "resume":
        for c in targets:
            c.paused = False
        return f"Resumed {len(targets)} client(s)."

    if cmd == "pulse":
        strength = 1.0
        if len(parts) >= 3:
            strength = max(0.1, float(parts[2]))
        for c in targets:
            c.pulse(strength)
        return f"Injected pulse into {len(targets)} client(s), strength={strength:.2f}."

    if cmd == "set":
        if len(parts) < 4:
            return "Usage: set <target> profile|amp|noise <value>"
        field = parts[2].lower()
        value = parts[3]

        if field == "profile":
            if value not in PROFILE_LIBRARY:
                return f"Unknown profile {value!r}. Use: profiles"
            for c in targets:
                c.profile_name = value
            return f"Set profile={value} for {len(targets)} client(s)."
        if field == "amp":
            amp = max(0.0, float(value))
            for c in targets:
                c.amp_scale = amp
            return f"Set amp={amp:.2f} for {len(targets)} client(s)."
        if field == "noise":
            noise = max(0.0, float(value))
            for c in targets:
                c.noise_scale = noise
            return f"Set noise={noise:.2f} for {len(targets)} client(s)."
        return f"Unknown field {field!r}. Use profile|amp|noise"

    return f"Unknown command: {cmd!r}. Try: help"


async def command_loop(clients: list[SimClient], stop_event: asyncio.Event) -> None:
    print("Interactive mode enabled. Type 'help' for commands.")
    while not stop_event.is_set():
        try:
            line = await asyncio.to_thread(input, "sim> ")
        except (EOFError, KeyboardInterrupt):
            stop_event.set()
            break
        try:
            out = apply_command(clients, line, stop_event)
        except Exception as exc:
            print(f"Command error: {exc}")
            continue
        if out:
            print(out)


class RoadSceneController:
    def __init__(self, clients: list[SimClient]):
        self.clients = clients
        self.rng = random.Random(2026)

    def _apply_quiet(self) -> None:
        for client in self.clients:
            client.scene_mode = "quiet"
            client.scene_gain = self.rng.uniform(0.0, 0.05)
            client.scene_noise_gain = self.rng.uniform(0.5, 0.9)
            client.common_event_gain = 0.0

    def _apply_single_active(self) -> None:
        active_idx = self.rng.randrange(0, len(self.clients))
        for i, client in enumerate(self.clients):
            client.scene_mode = "single"
            client.common_event_gain = 0.0
            if i == active_idx:
                client.scene_gain = self.rng.uniform(0.85, 1.3)
                client.scene_noise_gain = self.rng.uniform(0.9, 1.2)
                client.pulse(self.rng.uniform(0.4, 1.1))
            else:
                client.scene_gain = self.rng.uniform(0.02, 0.09)
                client.scene_noise_gain = self.rng.uniform(0.55, 0.95)

    def _apply_all_active(self) -> None:
        pulse_strength = self.rng.uniform(0.3, 0.9)
        for client in self.clients:
            client.scene_mode = "all"
            client.scene_gain = self.rng.uniform(0.65, 1.05)
            client.scene_noise_gain = self.rng.uniform(0.85, 1.2)
            # Keep a mild coherent component so all-sensor events appear together occasionally.
            client.common_event_gain = self.rng.uniform(0.18, 0.42)
            client.pulse(pulse_strength)

    def _apply_all_sync_event(self) -> None:
        # Explicit synchronized but moderate all-sensor event for multi-sensor detection testing.
        base = self.rng.uniform(0.5, 0.85)
        for client in self.clients:
            client.scene_mode = "all-sync"
            client.scene_gain = self.rng.uniform(0.7, 1.0)
            client.scene_noise_gain = self.rng.uniform(0.8, 1.1)
            client.common_event_gain = base
            client.pulse(self.rng.uniform(0.35, 0.8))

    def _apply_highway_100_sync(self) -> None:
        # 640i-like synchronized event around 100 km/h across all sensors.
        base = self.rng.uniform(0.6, 0.95)
        for client in self.clients:
            client.scene_mode = "highway100-sync"
            client.scene_gain = self.rng.uniform(0.65, 0.95)
            client.scene_noise_gain = self.rng.uniform(0.8, 1.1)
            client.common_event_gain = base
            client.pulse(self.rng.uniform(0.35, 0.8))

    def next_scene(self) -> tuple[str, float]:
        mode = self.rng.choices(
            ["quiet", "single", "all", "all_sync", "highway100"],
            weights=[0.34, 0.29, 0.16, 0.11, 0.10],
            k=1,
        )[0]
        if mode == "quiet":
            self._apply_quiet()
            return mode, self.rng.uniform(4.0, 9.0)
        if mode == "single":
            self._apply_single_active()
            return mode, self.rng.uniform(5.0, 11.0)
        if mode == "all_sync":
            self._apply_all_sync_event()
            return mode, self.rng.uniform(2.6, 5.4)
        if mode == "highway100":
            self._apply_highway_100_sync()
            return mode, self.rng.uniform(3.0, 6.0)
        self._apply_all_active()
        return mode, self.rng.uniform(4.0, 8.0)


async def road_scene_loop(clients: list[SimClient], stop_event: asyncio.Event) -> None:
    if not clients:
        return
    controller = RoadSceneController(clients)
    while not stop_event.is_set():
        mode, duration = controller.next_scene()
        print(f"[road-scene] mode={mode} duration={duration:.1f}s")
        await asyncio.sleep(duration)


async def run_client(
    sim: SimClient, hello_interval_s: float, stop_event: asyncio.Event
) -> None:
    loop = asyncio.get_running_loop()
    control_transport, _ = await loop.create_datagram_endpoint(
        lambda: ClientProtocol(sim),
        local_addr=("0.0.0.0", sim.control_port),
    )
    data_transport, _ = await loop.create_datagram_endpoint(
        lambda: DataProtocol(sim),
        local_addr=("0.0.0.0", 0),
    )
    sim.control_transport = control_transport
    sim.data_transport = data_transport
    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(hello_loop(sim, hello_interval_s, stop_event))
            tg.create_task(data_loop(sim, stop_event))
            tg.create_task(wait_stop(stop_event))
    finally:
        control_transport.close()
        data_transport.close()


async def wait_stop(stop_event: asyncio.Event) -> None:
    await stop_event.wait()
    raise asyncio.CancelledError()


async def hello_loop(
    sim: SimClient, hello_interval_s: float, stop_event: asyncio.Event
) -> None:
    while not stop_event.is_set():
        if sim.control_transport is not None:
            packet = pack_hello(
                client_id=sim.client_id,
                control_port=sim.control_port,
                sample_rate_hz=sim.sample_rate_hz,
                name=sim.name,
                firmware_version="sim-0.2",
            )
            sim.control_transport.sendto(
                packet, (sim.server_host, sim.server_control_port)
            )
        await asyncio.sleep(hello_interval_s)


async def data_loop(sim: SimClient, stop_event: asyncio.Event) -> None:
    if sim.rng is None:
        raise RuntimeError("SimClient.rng must be initialised before data_loop")
    frame_period = (sim.frame_samples / sim.sample_rate_hz) * sim.send_period_scale
    loop = asyncio.get_running_loop()
    next_send = loop.time() + sim.start_offset_s
    while not stop_event.is_set():
        if sim.data_transport is not None:
            samples = sim.make_frame()
            packet = pack_data(
                client_id=sim.client_id,
                seq=sim.seq,
                t0_us=time.monotonic_ns() // 1000,
                samples=samples,
            )
            sim.data_transport.sendto(packet, (sim.server_host, sim.server_data_port))
            sim.seq = (sim.seq + 1) & 0xFFFFFFFF
        next_send += frame_period
        jitter = float(sim.rng.uniform(-sim.send_jitter_s, sim.send_jitter_s))
        await asyncio.sleep(max(0.0, (next_send + jitter) - loop.time()))


async def auto_stop(delay_s: float, stop_event: asyncio.Event) -> None:
    await asyncio.sleep(delay_s)
    stop_event.set()


async def async_main(args: argparse.Namespace) -> None:
    managed_server: subprocess.Popen[str] | None = None
    if not args.no_auto_server:
        managed_server = maybe_start_server(args)

    names = (
        [n.strip() for n in args.names.split(",") if n.strip()] if args.names else []
    )
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
        )
        for i in range(args.count)
    ]

    if args.scenario == "one-wheel-mild":
        apply_one_wheel_mild_scenario(clients, args.fault_wheel)

    override_speed_kmh = max(0.0, float(args.speed_kmh))
    if override_speed_kmh > 0.0:
        applied_speed = set_server_speed_override_kmh(
            args.server_host,
            args.server_http_port,
            override_speed_kmh,
            args.server_check_timeout,
        )
        shown_speed = applied_speed if applied_speed is not None else override_speed_kmh
        print(f"Applied server speed override: {shown_speed:.1f} km/h")

    interactive = args.interactive or (
        not args.no_interactive and args.duration <= 0 and sys.stdin.isatty()
    )
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task[Any]] = []

    print(
        f"Starting {len(clients)} simulated clients -> "
        f"{args.server_host}:{args.server_data_port} (open http://{args.server_host}:8000) "
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
        for client in clients:
            tasks.append(
                asyncio.create_task(run_client(client, args.hello_interval, stop_event))
            )
        if args.scenario == "road":
            tasks.append(asyncio.create_task(road_scene_loop(clients, stop_event)))
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
    parser = argparse.ArgumentParser(description="VibeSensor UDP simulator")
    parser.add_argument("--server-host", default="127.0.0.1")
    parser.add_argument("--server-data-port", type=int, default=9000)
    parser.add_argument("--server-control-port", type=int, default=9001)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument(
        "--names", default="front-left,front-right,rear-left,rear-right,trunk"
    )
    parser.add_argument("--sample-rate-hz", type=int, default=800)
    parser.add_argument("--frame-samples", type=int, default=200)
    parser.add_argument("--hello-interval", type=float, default=2.0)
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
        choices=("road", "one-wheel-mild"),
        default="road",
        help="Simulation scenario: random road scene or deterministic mild single-wheel fault",
    )
    parser.add_argument(
        "--fault-wheel",
        default="front-right",
        help="Client name to apply the mild wheel fault to when --scenario one-wheel-mild",
    )
    parser.add_argument(
        "--interactive", action="store_true", help="Force interactive command mode"
    )
    parser.add_argument(
        "--no-interactive", action="store_true", help="Disable interactive command mode"
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
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
