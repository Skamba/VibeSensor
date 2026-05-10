"""CLI wrapper for backend static architecture guards."""

from __future__ import annotations

import sys

from static_guards.checks import main


if __name__ == "__main__":
    sys.exit(main())
