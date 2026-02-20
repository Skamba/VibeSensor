"""VibeSensor server package."""

from importlib.metadata import PackageNotFoundError, version

__all__ = ["__version__"]

try:
    __version__: str = version("vibesensor")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
