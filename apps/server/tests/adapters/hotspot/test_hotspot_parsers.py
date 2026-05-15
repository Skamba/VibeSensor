"""Tests for hotspot parser helpers and HealStateStore behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from vibesensor.adapters.hotspot.parsers import (
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
    @pytest.mark.parametrize(
        ("stdout", "expected"),
        [
            pytest.param(
                "Wired connection 1\nHotspot\n",
                ["Wired connection 1", "Hotspot"],
                id="preserves_order",
            ),
            pytest.param("", [], id="empty"),
            pytest.param("  \n  \n", [], id="blank_lines"),
            pytest.param("foo\n\n\n", ["foo"], id="ignores_blank_lines"),
        ],
    )
    def test_parses_non_empty_lines_in_order(self, stdout: str, expected: list[str]) -> None:
        assert parse_active_connection_names(stdout) == expected


# ---------------------------------------------------------------------------
# parse_active_conn_device
# ---------------------------------------------------------------------------


class TestParseActiveConnDevice:
    @pytest.mark.parametrize(
        ("con_name", "stdout", "expected"),
        [
            pytest.param(
                "Hotspot",
                "Hotspot:wlan0\nWired connection 1:eth0\n",
                (True, "wlan0"),
                id="found",
            ),
            pytest.param("Missing", "Hotspot:wlan0\n", (False, None), id="not_found"),
            pytest.param("Hotspot", "Hotspot:\n", (True, None), id="no_device"),
            pytest.param("Hotspot", "badinput\n", (False, None), id="malformed_line"),
        ],
    )
    def test_finds_active_connection_device(
        self,
        con_name: str,
        stdout: str,
        expected: tuple[bool, str | None],
    ) -> None:
        assert parse_active_conn_device(con_name, stdout) == expected


# ---------------------------------------------------------------------------
# parse_ip
# ---------------------------------------------------------------------------


class TestParseIp:
    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            pytest.param(
                "    inet 192.168.4.1/24 brd 192.168.4.255 scope global wlan0\n",
                "192.168.4.1/24",
                id="first_inet_cidr",
            ),
            pytest.param("    link/ether aa:bb:cc:dd:ee:ff\n", None, id="no_inet"),
            pytest.param("", None, id="empty"),
            pytest.param(
                "    inet\n    inet 10.0.0.5/24 brd 10.0.0.255 scope global wlan0\n",
                "10.0.0.5/24",
                id="skips_malformed_inet",
            ),
        ],
    )
    def test_extracts_first_valid_inet_cidr(self, output: str, expected: str | None) -> None:
        assert parse_ip(output) == expected


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
        self,
        expected_cidr: str,
        actual_cidr: str | None,
        is_match: bool,
    ) -> None:
        assert expected_ip_match(expected_cidr, actual_cidr) is is_match


# ---------------------------------------------------------------------------
# parse_iw_info
# ---------------------------------------------------------------------------


class TestParseIwInfo:
    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            pytest.param(
                "Interface wlan0\n\ttype AP\n\tchannel 6 (2437 MHz)\n",
                (True, "6"),
                id="ap_mode",
            ),
            pytest.param(
                "Interface wlan0\n\ttype managed\n\tchannel 11\n",
                (False, "11"),
                id="station_mode",
            ),
            pytest.param("Interface wlan0\n\ttype AP\n", (True, None), id="no_channel"),
        ],
    )
    def test_parses_mode_and_channel(
        self,
        output: str,
        expected: tuple[bool, str | None],
    ) -> None:
        assert parse_iw_info(output) == expected


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
            pytest.param(
                "dhcp: no address range available for subnet\n",
                "dhcp_no_range",
                id="dhcp_no_range",
            ),
            pytest.param(
                "failed to start dnsmasq process\n",
                "dhcp_dnsmasq_start_failed",
                id="dnsmasq_start_failed",
            ),
            pytest.param(
                "address already in use on port 53\n",
                "port53_conflict",
                id="port53_conflict",
            ),
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
    @pytest.mark.parametrize(
        ("initial_state", "steps"),
        [
            pytest.param(None, [("restart", 60, False, True)], id="allow_first_call"),
            pytest.param(
                None,
                [
                    ("restart", 9999, False, True),
                    ("restart", 9999, False, False),
                ],
                id="cooldown_blocks_second_call",
            ),
            pytest.param(
                None,
                [
                    ("restart", 9999, False, True),
                    ("reload", 9999, False, True),
                ],
                id="different_keys_independent",
            ),
            pytest.param("NOT JSON", [("restart", 60, False, True)], id="corrupt_recovered"),
            pytest.param(
                None,
                [
                    ("restart", 9999, False, True),
                    ("restart", 9999, True, False),
                ],
                id="state_persists_across_instances",
            ),
            pytest.param(
                '{"restart": 9999999999, "reload": "bad", "reassociate": [1]}\n',
                [
                    ("restart", 9999, False, False),
                    ("reload", 60, False, True),
                    ("reassociate", 60, False, True),
                ],
                id="partial_state_keeps_numeric_entries",
            ),
        ],
    )
    def test_allow_applies_cooldown_state_rules(
        self,
        tmp_path: Path,
        initial_state: str | None,
        steps: list[tuple[str, int, bool, bool]],
    ) -> None:
        state_path = tmp_path / "state.json"
        if initial_state is not None:
            state_path.write_text(initial_state, encoding="utf-8")
        store = HealStateStore(state_path)

        for key, min_interval_s, recreate_store, expected in steps:
            if recreate_store:
                store = HealStateStore(state_path)
            assert store.allow(key, min_interval_s=min_interval_s) is expected
