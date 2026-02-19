from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    cursor = (start or Path(__file__).resolve()).resolve()
    for candidate in [cursor, *cursor.parents]:
        if (candidate / "libs" / "shared" / "contracts").is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not locate repository root containing libs/shared/contracts"
    )


def shared_contracts_dir(start: Path | None = None) -> Path:
    return find_repo_root(start) / "libs" / "shared" / "contracts"
