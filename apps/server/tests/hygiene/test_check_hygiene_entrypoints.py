"""Pytest entrypoint for the repository hygiene runner."""

from __future__ import annotations

from types import ModuleType

import pytest
from test_support.check_hygiene_loader import load_check_hygiene_module


@pytest.fixture(scope="module")
def hygiene_module() -> ModuleType:
    return load_check_hygiene_module("check_hygiene_test_entrypoints")


def test_check_hygiene_main_passes(hygiene_module: ModuleType) -> None:
    assert hygiene_module.main() == 0
