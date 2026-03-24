"""Lightweight application package facade for explicit startup entrypoints."""

__all__ = ["create_app", "create_app_from_env", "main"]


def __getattr__(name: str) -> object:
    from importlib import import_module

    bootstrap = import_module(".bootstrap", __name__)

    try:
        return getattr(bootstrap, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc
