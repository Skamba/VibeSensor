"""Resolved repository paths shared by config schema and loader modules."""

from __future__ import annotations

from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[2]
"""Root of the ``apps/server/`` package tree."""

REPO_DIR = SERVER_DIR.parents[1]

__all__ = ["REPO_DIR", "SERVER_DIR"]
