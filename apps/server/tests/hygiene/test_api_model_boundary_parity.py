"""Source-driven ownership checks for HTTP history contract aliases."""

from __future__ import annotations

from types import ModuleType
from typing import is_typeddict

from vibesensor.adapters.http.models import history as history_models
from vibesensor.shared.types import analysis_views, data_quality_contracts
from vibesensor.shared.types import history_analysis_contracts as history_contracts

_SHARED_CONTRACT_MODULES: tuple[ModuleType, ...] = (
    analysis_views,
    data_quality_contracts,
    history_contracts,
)


def _exported_contract(module: ModuleType, name: str) -> object | None:
    if name not in getattr(module, "__all__", ()):
        return None
    return getattr(module, name, None)


def test_http_history_reexports_shared_typed_dict_contracts() -> None:
    """HTTP history aliases must point at shared owners, not duplicate them."""

    assert history_models.__all__
    for name in history_models.__all__:
        api_contract = getattr(history_models, name)
        shared_contracts = {
            contract
            for module in _SHARED_CONTRACT_MODULES
            if (contract := _exported_contract(module, name)) is not None
        }

        assert is_typeddict(api_contract), f"{name} should be a TypedDict contract"
        assert shared_contracts == {api_contract}, (
            f"{name} should be re-exported from a shared contract owner instead of "
            "duplicated in adapters.http.models.history"
        )
