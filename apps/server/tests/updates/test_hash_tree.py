"""The installed-tree hash survives files disappearing while it is computed."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from vibesensor.updates.status.runtime_details import hash_tree


class TestHashTreeFileDeletedMidScan:
    """hash_tree must not crash if a file is deleted between rglob and open."""

    def test_deleted_file_skipped_gracefully(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")

        h1 = hash_tree(tmp_path, ignore_names=set())
        assert len(h1) == 64  # SHA256 hex digest

        original_path_open = Path.open

        def failing_path_open(self, *args, **kwargs):
            if "b.txt" in str(self):
                raise FileNotFoundError(f"simulated deletion: {self}")
            return original_path_open(self, *args, **kwargs)

        with patch.object(Path, "open", side_effect=failing_path_open, autospec=True):
            h2 = hash_tree(tmp_path, ignore_names=set())
            assert len(h2) == 64
            assert h2 != h1
