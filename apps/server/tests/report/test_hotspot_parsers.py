"""Tests for hotspot_parsers text-parsing helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.hotspot_parsers import (
    HealStateStore,
    expected_ip_match,
    nm_log_signals,
    parse_active_conn_device,
    parse_active_connection_names,
    parse_ip,
    parse_iw_info,
    parse_port53_conflict,
    parse_rfkill_blocked,
)

# ---------------------------------------------------------------------------
# parse_active_connection_names
# ---------------------------------------------------------------------------


class TestParseActiveConnectionNames:
    def test_basic(self) -> None:
        assert parse_active_connection_names("Wired connection 1\nHotspot\n") == [
            "Wired connection 1",
            "Hotspot",
        ]

    def test_empty(self) -> None:
        assert parse_active_connection_names("") == []

    def test_whitespace_lines(self) -> None:
        assert parse_active_connection_names("  \n  \n") == []

    def test_trailing_newlines(self) -> None:
        assert parse_active_connection_names("foo\n\n\n") == ["foo"]


# ---------------------------------------------------------------------------
# parse_active_conn_device
# ---------------------------------------------------------------------------


class TestParseActiveConnDevice:
    def test_found(self) -> None:
        stdout = "Hotspot:wlan0\nWired connection 1:eth0\n"
        active, device = parse_active_conn_device("Hotspot", stdout)
        assert active is True
        assert device == "wlan0"

    def test_not_found(self) -> None:
        active, device = parse_active_conn_device("Missing", "Hotspot:wlan0\n")
        assert active is False
        assert device is None

    def test_no_device(self) -> None:
        active, device = parse_active_conn_device("Hotspot", "Hotspot:\n")
        assert active is True
        assert device is None

    def test_malformed_lines(self) -> None:
        active, device = parse_active_conn_device("Hotspot", "badinput\n")
        assert active is False
        assert device is None


# ---------------------------------------------------------------------------
# parse_ip
# ---------------------------------------------------------------------------


class TestParseIp:
    @pytest.mark.smoke
    def test_basic(self) -> None:
        output = "    inet 192.168.4.1/24 brd 192.168.4.255 scope global wlan0\n"
        assert parse_ip(output) == "192.168.4.1/24"

    def test_no_inet(self) -> None:
        assert parse_ip("    link/ether aa:bb:cc:dd:ee:ff\n") is None

    def test_empty(self) -> None:
        assert parse_ip("") is None


# ---------------------------------------------------------------------------
# expected_ip_match
# ---------------------------------------------------------------------------


class TestExpectedIpMatch:
    def test_match(self) -> None:
        assert expected_ip_match("192.168.4.1/24", "192.168.4.1/24") is True

    def test_ip_only_match(self) -> None:
        assert expected_ip_match("192.168.4.1/24", "192.168.4.1/16") is True

    def test_mismatch(self) -> None:
        assert expected_ip_match("192.168.4.1/24", "10.0.0.1/24") is False

    def test_none(self) -> None:
        assert expected_ip_match("192.168.4.1/24", None) is False


# ---------------------------------------------------------------------------
# parse_iw_info
# ---------------------------------------------------------------------------


class TestParseIwInfo:
    def test_ap_mode(self) -> None:
        output = "Interface wlan0\n\ttype AP\n\tchannel 6 (2437 MHz)\n"
        ap, channel = parse_iw_info(output)
        assert ap is True
        assert channel == "6"

    def test_station_mode(self) -> None:
        output = "Interface wlan0\n\ttype managed\n\tchannel 11\n"
        ap, channel = parse_iw_info(output)
        assert ap is False
        assert channel == "11"

    def test_no_channel(self) -> None:
        ap, channel = parse_iw_info("Interface wlan0\n\ttype AP\n")
        assert ap is True
        assert channel is None


# ---------------------------------------------------------------------------
# parse_rfkill_blocked
# ---------------------------------------------------------------------------


class TestParseRfkillBlocked:
    def test_soft_blocked(self) -> None:
        assert parse_rfkill_blocked("Soft blocked: yes\nHard blocked: no\n") is True

    def test_hard_blocked(self) -> None:
        assert parse_rfkill_blocked("Soft blocked: no\nHard blocked: yes\n") is True

    def test_not_blocked(self) -> None:
        assert parse_rfkill_blocked("Soft blocked: no\nHard blocked: no\n") is False

    def test_empty(self) -> None:
        assert parse_rfkill_blocked("") is False


# ---------------------------------------------------------------------------
# nm_log_signals
# ---------------------------------------------------------------------------


class TestNmLogSignals:
    def test_dhcp_no_range(self) -> None:
        sig, detail = nm_log_signals("dhcp: no address range available for subnet\n")
        assert sig == "dhcp_no_range"

    def test_dnsmasq_start_failed(self) -> None:
        sig, _ = nm_log_signals("failed to start dnsmasq process\n")
        assert sig == "dhcp_dnsmasq_start_failed"

    def test_port53_conflict(self) -> None:
        sig, _ = nm_log_signals("address already in use on port 53\n")
        assert sig == "port53_conflict"

    def test_no_signal(self) -> None:
        sig, detail = nm_log_signals("everything is fine\n")
        assert sig is None and detail is None


# ---------------------------------------------------------------------------
# parse_port53_conflict
# ---------------------------------------------------------------------------


class TestParsePort53Conflict:
    def test_conflict_found_double_paren(self) -> None:
        # Real ss output uses double-paren format: users:(("name",pid=…,fd=…))
        output = (
            "LISTEN  0  128  127.0.0.53%lo:53  0.0.0.0:*"
            '  users:(("systemd-resolved",pid=571,fd=13))\n'
        )
        result = parse_port53_conflict(output)
        assert result == "systemd-resolved"

    def test_conflict_found_single_paren(self) -> None:
        # Some ss versions may use single-paren format
        output = 'LISTEN  0  0  *:53  *:*  users:("systemd-resolved",pid=123,fd=4)\n'
        result = parse_port53_conflict(output)
        assert result == "systemd-resolved"

    def test_dnsmasq_nm_ignored(self) -> None:
        output = 'LISTEN 0 0 *:53 *:* users:(("dnsmasq",pid=1,fd=2)) networkmanager dnsmasq\n'
        assert parse_port53_conflict(output) is None

    def test_empty(self) -> None:
        assert parse_port53_conflict("") is None

    def test_no_users_field(self) -> None:
        output = "LISTEN  0  128  127.0.0.53%lo:53  0.0.0.0:*\n"
        assert parse_port53_conflict(output) is None


# ---------------------------------------------------------------------------
# HealStateStore
# ---------------------------------------------------------------------------


class TestHealStateStore:
    def test_allow_first_call(self, tmp_path: Path) -> None:
        store = HealStateStore(tmp_path / "state.json")
        assert store.allow("restart", min_interval_s=60) is True

    def test_cooldown_blocks_second_call(self, tmp_path: Path) -> None:
        store = HealStateStore(tmp_path / "state.json")
        assert store.allow("restart", min_interval_s=9999) is True
        assert store.allow("restart", min_interval_s=9999) is False

    def test_different_keys_independent(self, tmp_path: Path) -> None:
        store = HealStateStore(tmp_path / "state.json")
        assert store.allow("restart", min_interval_s=9999) is True
        assert store.allow("reload", min_interval_s=9999) is True

    def test_corrupt_state_file_recovered(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        state_path.write_text("NOT JSON", encoding="utf-8")
        store = HealStateStore(state_path)
        assert store.allow("restart", min_interval_s=60) is True

    def test_state_persists_across_instances(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.json"
        store1 = HealStateStore(state_path)
        assert store1.allow("restart", min_interval_s=9999) is True
        store2 = HealStateStore(state_path)
        assert store2.allow("restart", min_interval_s=9999) is False
