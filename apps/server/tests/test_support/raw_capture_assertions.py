from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol


class _WarningWithCode(Protocol):
    code: str


def warning_codes(warnings: Iterable[_WarningWithCode]) -> list[str]:
    return [str(warning.code) for warning in warnings]
