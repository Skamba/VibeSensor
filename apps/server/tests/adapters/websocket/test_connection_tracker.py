"""Tests for the ConnectionTracker — generation-based connection state."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from vibesensor.adapters.websocket.connection_tracker import (
    ConnectionTracker,
)


def _make_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_text = AsyncMock()
    return ws


@pytest.mark.asyncio
async def test_add_and_snapshot() -> None:
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, "client_a")
    snaps = await tracker.snapshot()
    assert len(snaps) == 1
    assert snaps[0].websocket is ws
    assert snaps[0].selected_client_id == "client_a"


@pytest.mark.asyncio
async def test_remove_excludes_from_snapshot() -> None:
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, None)
    await tracker.remove(ws)
    assert await tracker.snapshot() == []


@pytest.mark.asyncio
async def test_connection_count() -> None:
    tracker = ConnectionTracker()
    assert tracker.connection_count() == 0
    ws = _make_ws()
    await tracker.add(ws, None)
    assert tracker.connection_count() == 1
    await tracker.remove(ws)
    assert tracker.connection_count() == 0


@pytest.mark.asyncio
async def test_update_selected_client() -> None:
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, "old")
    await tracker.update_selected_client(ws, "new")
    snaps = await tracker.snapshot()
    assert snaps[0].selected_client_id == "new"


@pytest.mark.asyncio
async def test_is_snapshot_current_after_remove() -> None:
    """Snapshot becomes stale after the connection is removed."""
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, None)
    snap = (await tracker.snapshot())[0]
    assert await tracker.is_snapshot_current(snap) is True
    await tracker.remove(ws)
    assert await tracker.is_snapshot_current(snap) is False


@pytest.mark.asyncio
async def test_mark_snapshot_closing() -> None:
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, None)
    snap = (await tracker.snapshot())[0]
    assert await tracker.mark_snapshot_closing(snap) is True
    # After marking closing, snapshot() excludes it
    assert await tracker.snapshot() == []


@pytest.mark.asyncio
async def test_mark_closing_stale_snapshot_returns_false() -> None:
    """Marking a stale snapshot closing returns False."""
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, None)
    snap = (await tracker.snapshot())[0]
    await tracker.remove(ws)
    assert await tracker.mark_snapshot_closing(snap) is False


@pytest.mark.asyncio
async def test_remove_snapshot_only_removes_same_generation() -> None:
    """remove_snapshot() ignores a snapshot whose generation doesn't match."""
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, None)
    old_snap = (await tracker.snapshot())[0]
    # Remove and re-add ⇒ new generation
    await tracker.remove(ws)
    await tracker.add(ws, "new")
    # Old generation removal should be a no-op
    await tracker.remove_snapshot(old_snap)
    assert tracker.connection_count() == 1


@pytest.mark.asyncio
async def test_current_selected_client_id_returns_live_value() -> None:
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, "initial")
    snap = (await tracker.snapshot())[0]
    await tracker.update_selected_client(ws, "updated")
    is_current, cid = await tracker.current_selected_client_id(snap)
    assert is_current is True
    assert cid == "updated"


@pytest.mark.asyncio
async def test_current_selected_client_id_stale_returns_false() -> None:
    tracker = ConnectionTracker()
    ws = _make_ws()
    await tracker.add(ws, "initial")
    snap = (await tracker.snapshot())[0]
    await tracker.remove(ws)
    is_current, cid = await tracker.current_selected_client_id(snap)
    assert is_current is False
    assert cid is None
