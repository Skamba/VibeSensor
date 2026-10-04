from __future__ import annotations

import hashlib
import json
from pathlib import Path


def partition_entry(label: str, kind: int, subtype: int, offset: int, size: int) -> bytes:
    """One 32-byte ESP-IDF partition table entry."""
    return (
        b"\xaa\x50"
        + bytes([kind, subtype])
        + offset.to_bytes(4, "little")
        + size.to_bytes(4, "little")
        + label.encode().ljust(16, b"\0")
        + b"\0" * 4
    )


# Arduino-ESP32 default table head: nvs, otadata, app0.
DEFAULT_PARTITION_TABLE = (
    partition_entry("nvs", 0x01, 0x02, 0x9000, 0x5000)
    + partition_entry("otadata", 0x01, 0x00, 0xE000, 0x2000)
    + partition_entry("app0", 0x00, 0x10, 0x10000, 0x140000)
    + b"\xff" * 32
)


# Where each chip's ROM loads the second-stage bootloader from.
_BOOTLOADER_OFFSET = {"esp32": "0x1000", "esp32c3": "0x0000"}


def write_firmware_bundle(
    bundle_dir: Path,
    *,
    environments: tuple[tuple[str, str], ...] = (("m5stack_atom", "esp32"),),
) -> None:
    """Write a release-shaped bundle with one ``(env name, chip)`` build per entry."""
    manifest_envs = []
    for name, chip in environments:
        env_dir = bundle_dir / name
        env_dir.mkdir(parents=True, exist_ok=True)
        segments = []
        for file_name, offset in (
            ("bootloader.bin", _BOOTLOADER_OFFSET[chip]),
            ("partitions.bin", "0x8000"),
            ("firmware.bin", "0x10000"),
        ):
            content = (
                DEFAULT_PARTITION_TABLE
                if file_name == "partitions.bin"
                else f"fake-{name}-{file_name}".encode()
            )
            (env_dir / file_name).write_bytes(content)
            segments.append(
                {
                    "file": f"{name}/{file_name}",
                    "offset": offset,
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        manifest_envs.append({"name": name, "chip": chip, "segments": segments})

    manifest = {"generated_from": "test", "environments": manifest_envs}
    (bundle_dir / "flash.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
