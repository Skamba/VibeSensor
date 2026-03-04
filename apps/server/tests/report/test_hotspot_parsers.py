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
    def test_parses_non_empty_lines_in_order(self) -> None:
        assert parse_active_connection_names("Wired connection 1\nHotspot\n") == [
            "Wired connection 1",
            "Hotspot",
        ]

    @pytest.mark.parametrize(
        ("stdout", "expected"),
        [
            ("", []),
            ("  \n  \n", []),
            ("foo\n\n\n", ["foo"]),
        ],
    )
    def test_ignores_blank_lines(self, stdout: str, expected: list[str]) -> None:
        assert parse_active_connection_names(stdout) == expected


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
    def test_extracts_first_inet_cidr(self) -> None:
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
    @pytest.mark.parametrize(
        ("expected_cidr", "actual_cidr", "is_match"),
        [
            ("192.168.4.1/24", "192.168.4.1/24", True),
            ("192.168.4.1/24", "192.168.4.1/16", True),
            ("192.168.4.1/24", "10.0.0.1/24", False),
            ("192.168.4.1/24", None, False),
        ],
    )
    def test_compares_ip_part_only(
        self, expected_cidr: str, actual_cidr: str | None, is_match: bool
    ) -> None:
        assert expected_ip_match(expected_cidr, actual_cidr) is is_match


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
    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            ("Soft blocked: yes\nHard blocked: no\n", True),
            ("Soft blocked: no\nHard blocked: yes\n", True),
            ("Soft blocked: no\nHard blocked: no\n", False),
            ("", False),
        ],
    )
    def test_reports_blocked_state(self, output: str, expected: bool) -> None:
        assert parse_rfkill_blocked(output) is expected


# ---------------------------------------------------------------------------
# nm_log_signals
# ---------------------------------------------------------------------------


class TestNmLogSignals:
    @pytest.mark.parametrize(
        ("log_text", "expected_sig"),
        [
            pytest.param("dhcp: no address range available for subnet\n", "dhcp_no_range", id="dhcp_no_range"),
            pytest.param("failed to start dnsmasq process\n", "dhcp_dnsmasq_start_failed", id="dnsmasq_start_failed"),
            pytest.param("address already in use on port 53\n", "port53_conflict", id="port53_conflict"),
            pytest.param("everything is fine\n", None, id="no_signal"),
        ],
    )
    def test_detects_signal(self, log_text: str, expected_sig: str | None) -> None:
        sig, detail = nm_log_signals(log_text)
        assert sig == expected_sig
        assert detail is None


# ---------------------------------------------------------------------------
# parse_port53_conflict
# ---------------------------------------------------------------------------


class TestParsePort53Conflict:
    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            pytest.param(
                # Real ss output uses double-paren format: users:(("name",pid=…,fd=…))
                "LISTEN  0  128  127.0.0.53%lo:53  0.0.0.0:*"
                '  users:(("systemd-resolved",pid=571,fd=13))\n',
                "systemd-resolved",
                id="double_paren",
            ),
            pytest.param(
                # Some ss versions may use single-paren format
                'LISTEN  0  0  *:53  *:*  users:("systemd-resolved",pid=123,fd=4)\n',
                "systemd-resolved",
                id="single_paren",
            ),
            pytest.param(
                'LISTEN 0 0 *:53 *:* users:(("dnsmasq",pid=1,fd=2)) networkmanager dnsmasq\n',
                None,
                id="dnsmasq_nm_ignored",
            ),
            pytest.param("", None, id="empty"),
            pytest.param(
                "LISTEN  0  128  127.0.0.53%lo:53  0.0.0.0:*\n",
                None,
                id="no_users_field",
            ),
            pytest.param(
                'LISTEN 0 0 *:53 *:* users:(("zproc",pid=1,fd=2))\n'
                'LISTEN 0 0 *:53 *:* users:(("aproc",pid=3,fd=4))\n'
                'LISTEN 0 0 *:53 *:* users:(("zproc",pid=5,fd=6))\n',
                "aproc,zproc",
                id="sorted_deduped",
            ),
        ],
    )
    def test_parses(self, output: str, expected: str | None) -> None:
        assert parse_port53_conflict(output) == expected


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
