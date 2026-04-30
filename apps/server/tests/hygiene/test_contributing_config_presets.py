"""Guard contributor config preset docs against shipped backend preset drift."""

from __future__ import annotations

import re

from tests._paths import REPO_ROOT


def test_contributing_lists_all_backend_config_presets() -> None:
    contributing_text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    preset_table = contributing_text.split("Preset files ship with the repo", maxsplit=1)[1].split(
        "**Quick start for local dev:**", maxsplit=1
    )[0]
    documented_presets = set(re.findall(r"`(config\.[a-z0-9_-]+\.yaml)`", preset_table))
    shipped_presets = {
        preset_path.name for preset_path in (REPO_ROOT / "apps" / "server").glob("config.*.yaml")
    }

    assert shipped_presets <= documented_presets
