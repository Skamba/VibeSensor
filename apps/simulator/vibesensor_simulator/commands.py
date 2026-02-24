from __future__ import annotations

import asyncio
import shlex
from typing import Any


def _normalize_wheel_slot(name: str) -> str | None:
    normalized = name.strip().lower().replace("_", "-").replace(" ", "-")
    alias = {
        "fl": "front-left",
        "fr": "front-right",
        "rl": "rear-left",
        "rr": "rear-right",
    }
    if normalized in alias:
        return alias[normalized]
    axle = (
        "front" if "front" in normalized else "rear" if "rear" in normalized else None
    )
    side = (
        "left" if "left" in normalized else "right" if "right" in normalized else None
    )
    if axle and side:
        return f"{axle}-{side}"
    return None


def _cross_corner_coupling(fault_wheel: str, sensor_name: str) -> float:
    """Return deterministic single-wheel coupling for non-fault corners.

    Values are chosen to keep transfer-path realism:
    - same-side front↔rear coupling strongest,
    - same-axle opposite side moderate,
    - diagonal weakest but still clearly above floor.
    """
    fault = _normalize_wheel_slot(fault_wheel)
    sensor = _normalize_wheel_slot(sensor_name)
    if fault is None or sensor is None:
        return 0.34
    if fault == sensor:
        return 1.0
    fault_axle, fault_side = fault.split("-", maxsplit=1)
    sensor_axle, sensor_side = sensor.split("-", maxsplit=1)
    if fault_side == sensor_side and fault_axle != sensor_axle:
        return 0.52
    if fault_axle == sensor_axle and fault_side != sensor_side:
        return 0.48
    return 0.40


def choose_default_profile(index: int) -> str:
    ordered = ("engine_idle", "wheel_imbalance", "rear_body", "rough_road")
    return ordered[index % len(ordered)]


def apply_one_wheel_mild_scenario(clients: list[Any], fault_wheel: str) -> None:
    target = fault_wheel.strip().lower()
    target_slot = _normalize_wheel_slot(target)
    for client in clients:
        normalized_name = client.name.strip().lower()
        client_slot = _normalize_wheel_slot(normalized_name)
        is_fault = normalized_name == target or (
            target_slot is not None and client_slot == target_slot
        )
        client.scene_mode = "one-wheel-mild"
        if is_fault:
            client.profile_name = "wheel_mild_imbalance"
            client.scene_gain = 0.78
            client.scene_noise_gain = 1.04
            client.amp_scale = 1.0
            client.noise_scale = 1.04
            client.common_event_gain = 0.18
            client.pulse(0.40)
        else:
            coupling = _cross_corner_coupling(fault_wheel, client.name)
            client.profile_name = (
                "wheel_mild_imbalance" if client_slot is not None else "rear_body"
            )
            # Keep non-fault sensors active (real coupling), but clearly below fault.
            client.scene_gain = 0.30 + 0.20 * coupling
            client.scene_noise_gain = 0.96 + 0.12 * coupling
            client.amp_scale = 0.58 + 0.30 * coupling
            client.noise_scale = 0.96 + 0.06 * coupling
            client.common_event_gain = 0.08 + 0.08 * coupling


def apply_road_fixed_scenario(clients: list[Any]) -> None:
    """Apply a deterministic baseline road scene for scripted scenarios.

    Unlike the ``road`` scenario, this does NOT start a background randomizer
    loop.  All clients receive identical, stable gains that produce a mild
    road-noise baseline without stochastic scene transitions.  This makes
    scripted multi-phase runs fully reproducible.
    """
    for client in clients:
        client.profile_name = "rough_road"
        client.scene_mode = "road-fixed"
        client.scene_gain = 0.28
        client.scene_noise_gain = 1.02
        client.common_event_gain = 0.10
        client.amp_scale = 0.52
        client.noise_scale = 1.00


def find_targets(clients: list[Any], token: str) -> list[Any]:
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
    clients: list[Any], line: str, stop_event: asyncio.Event, profile_names: list[str]
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
        return "Available profiles: " + ", ".join(profile_names)

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
            if value not in profile_names:
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
