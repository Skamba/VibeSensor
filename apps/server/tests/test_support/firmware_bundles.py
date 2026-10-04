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


def write_firmware_bundle(bundle_dir: Path, *, environment: str = "m5stack_atom") -> None:
    env_dir = bundle_dir / environment
    env_dir.mkdir(parents=True, exist_ok=True)
    binaries = {}
    for name in ("bootloader.bin", "partitions.bin", "firmware.bin"):
        content = DEFAULT_PARTITION_TABLE if name == "partitions.bin" else f"fake-{name}".encode()
        (env_dir / name).write_bytes(content)
        binaries[name] = hashlib.sha256(content).hexdigest()

    manifest = {
        "generated_from": "test",
        "environments": [
            {
                "name": environment,
                "segments": [
                    {
                        "file": f"{environment}/firmware.bin",
                        "offset": "0x10000",
                        "sha256": binaries["firmware.bin"],
                    },
                    {
                        "file": f"{environment}/bootloader.bin",
                        "offset": "0x1000",
                        "sha256": binaries["bootloader.bin"],
                    },
                    {
                        "file": f"{environment}/partitions.bin",
                        "offset": "0x8000",
                        "sha256": binaries["partitions.bin"],
                    },
                ],
            },
        ],
    }
    (bundle_dir / "flash.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
