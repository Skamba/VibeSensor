"""VibeSensor server package."""

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if (_REPO_ROOT / "libs").exists() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

__all__ = ["__version__"]

try:
    __version__: str = version("vibesensor")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
