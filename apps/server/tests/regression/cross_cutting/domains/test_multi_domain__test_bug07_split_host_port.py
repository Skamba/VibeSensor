"""Cross-cutting multi-domain regressions.

Each test verifies the specific bug fix by reproducing the original failure
condition and asserting the corrected behavior.
"""

from __future__ import annotations

import pytest

from vibesensor.config import _split_host_port
from vibesensor.release_fetcher import ReleaseInfo


def _make_release_info(version: str) -> ReleaseInfo:
    """Build a ReleaseInfo stub for version comparison tests."""
    return ReleaseInfo(
        tag=f"server-v{version}",
        version=version,
        asset_name=f"vibesensor-{version}.whl",
        asset_url=f"https://example.com/{version}.whl",
    )


class TestBug07SplitHostPort:
    def test_non_integer_port_raises_descriptive_error(self) -> None:
        with pytest.raises(ValueError, match="not an integer"):
            _split_host_port("host:abc")

    def test_valid_host_port(self) -> None:
        host, port = _split_host_port("127.0.0.1:8080")
        assert host == "127.0.0.1"
        assert port == 8080
