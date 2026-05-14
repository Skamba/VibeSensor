from __future__ import annotations

import hashlib
import json
from pathlib import Path


def write_firmware_bundle(bundle_dir: Path, *, environment: str = "m5stack_atom") -> None:
    env_dir = bundle_dir / environment
    env_dir.mkdir(parents=True, exist_ok=True)
    binaries = {}
    for name in ("bootloader.bin", "partitions.bin", "firmware.bin"):
        content = f"fake-{name}".encode()
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
