from __future__ import annotations

from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RELATIVE_POINTER_RE = re.compile(r"^(?:\./|\.\./)\S+$")
PY_PATH_HACK_RE = re.compile(r"sys\.path\.(?:insert|append)\(|PYTHONPATH=")


def _iter_repo_files() -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "-z"],
            text=False,
        )
        return [
            ROOT / rel_path
            for rel_path in output.decode("utf-8", errors="ignore").split("\0")
            if rel_path
        ]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [path for path in ROOT.rglob("*") if path.is_file()]


def _is_pointer_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) == 1 and bool(RELATIVE_POINTER_RE.fullmatch(lines[0]))


def main() -> int:
    pointer_files: list[str] = []
    python_path_hacks: list[str] = []
    for path in _iter_repo_files():
        if ".git" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        if _is_pointer_file(path):
            pointer_files.append(rel)
        if path.suffix == ".py" and rel != "tools/dev/verify_no_path_indirections.py":
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if PY_PATH_HACK_RE.search(text):
                python_path_hacks.append(rel)

    if pointer_files or python_path_hacks:
        if pointer_files:
            print("Pointer-style files found:")
            for item in pointer_files:
                print(f"- {item}")
        if python_path_hacks:
            print("sys.path/PYTHONPATH hacks found in Python files:")
            for item in python_path_hacks:
                print(f"- {item}")
        return 1
    print("No path-indirection files or sys.path/PYTHONPATH hacks found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
