"""Application bootstrap and wiring."""

__all__ = ["create_app", "main"]


def __getattr__(name: str) -> object:
    from importlib import import_module

    bootstrap = import_module(".bootstrap", __name__)

    try:
        return getattr(bootstrap, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc
