"""Lightweight application package facade for explicit startup entrypoints."""

from .bootstrap import create_app, create_app_from_env, main

__all__ = ["create_app", "create_app_from_env", "main"]
