"""CLI wrapper for repository hygiene checks."""

from __future__ import annotations

import sys

from hygiene.checks import main


if __name__ == "__main__":
    sys.exit(main())
