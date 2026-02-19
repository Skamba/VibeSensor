#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "--cached"],
        check=True,
        capture_output=True,
        text=True,
    )
    bad = [
        line
        for line in result.stdout.splitlines()
        if "__pycache__/" in line or line.endswith(".pyc")
    ]
    if bad:
        print("Found forbidden Python cache artifacts:")
        for path in bad:
            print(path)
        return 1
    print("No tracked __pycache__/ or .pyc artifacts found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
