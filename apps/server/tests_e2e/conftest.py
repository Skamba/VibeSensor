from __future__ import annotations

import os

import pytest


@pytest.fixture
def e2e_env() -> dict[str, str]:
    return {
        "base_url": os.environ["VIBESENSOR_BASE_URL"],
        "sim_host": os.environ["VIBESENSOR_SIM_SERVER_HOST"],
        "sim_data_port": os.environ["VIBESENSOR_SIM_DATA_PORT"],
        "sim_control_port": os.environ["VIBESENSOR_SIM_CONTROL_PORT"],
        "sim_duration": os.environ["VIBESENSOR_SIM_DURATION"],
        "sim_duration_long": os.environ.get("VIBESENSOR_SIM_DURATION_LONG", "20"),
    }
