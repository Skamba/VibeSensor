# ruff: noqa: F401,F403
"""Compatibility facade for focused test-support modules.

Prefer importing directly from ``test_support`` modules in new tests.
This file remains as a stable surface for the existing suite while the
synthetic builder implementation lives in smaller concern-based modules.
"""

from __future__ import annotations

from test_support.analysis import *
from test_support.assertions import *
from test_support.core import *
from test_support.core import _stable_hash
from test_support.scenarios import *
