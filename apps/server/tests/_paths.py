"""Stable path constants for test files.

These constants remain valid regardless of which subdirectory a test
lives in, eliminating fragile ``Path(__file__).parents[N]`` chains.
"""

from __future__ import annotations

from pathlib import Path

# tests/ directory (this file's parent)
TESTS_DIR = Path(__file__).resolve().parent

# apps/server/  (one level above tests/)
SERVER_ROOT = TESTS_DIR.parent

# repository root (apps/server/ → apps/ → repo)
REPO_ROOT = SERVER_ROOT.parent.parent
