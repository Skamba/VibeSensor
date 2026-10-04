"""The printable hotspot card (tools/hardware/make_qr_card.py, docs/user_journeys.md §3.1).

The QR symbols are read back with the small decoder below (versions 1-6, byte
mode), so a payload or layout regression fails here rather than at a phone.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from reportlab.graphics.shapes import Group, String

from tests._paths import REPO_ROOT
from vibesensor.app.config_defaults import DEFAULT_CONFIG
from vibesensor.hotspot.constants import HOTSPOT_IP

_SCRIPT = REPO_ROOT / "tools" / "hardware" / "make_qr_card.py"
_EXAMPLE = REPO_ROOT / "hardware" / "qr_card_example"

# Data codewords per block at error correction M (ISO/IEC 18004 table 9).
_M_BLOCKS = {1: [16], 2: [28], 3: [44], 4: [32] * 2, 5: [43] * 2, 6: [27] * 4}
_MASKS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r * c) % 3 + (r + c) % 2) % 2 == 0,
)


@pytest.fixture(scope="module")
def card() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_qr_card_for_tests", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _decode(matrix: list[list[bool]]) -> tuple[str, str]:
    """Return (error correction level, text) of a version 1-6 byte-mode symbol."""
    size = len(matrix)
    version = (size - 17) // 4
    finder = [[max(abs(r - 3), abs(c - 3)) != 2 for c in range(7)] for r in range(7)]
    for r0, c0 in ((0, 0), (0, size - 7), (size - 7, 0)):
        assert [row[c0 : c0 + 7] for row in matrix[r0 : r0 + 7]] == finder

    reserved = [[False] * size for _ in range(size)]

    def reserve(r0: int, c0: int, height: int, width: int) -> None:
        for r in range(r0, r0 + height):
            for c in range(c0, c0 + width):
                reserved[r][c] = True

    reserve(0, 0, 9, 9)  # finder, separator and format info
    reserve(0, size - 8, 9, 8)
    reserve(size - 8, 0, 8, 9)
    reserve(6, 0, 1, size)  # timing patterns
    reserve(0, 6, size, 1)
    if version >= 2:
        reserve(size - 9, size - 9, 5, 5)  # the single alignment pattern of v2-6

    rows = [*range(6), 7, 8, *range(size - 7, size)]
    raw = sum(matrix[r][8] << i for i, r in enumerate(rows)) ^ 0x5412
    level = {0b00: "M", 0b01: "L", 0b10: "H", 0b11: "Q"}[raw >> 13]
    mask = _MASKS[(raw >> 10) & 0b111]

    bits: list[int] = []
    col, upward = size - 1, True
    while col > 0:
        if col == 6:
            col -= 1
        for r in range(size - 1, -1, -1) if upward else range(size):
            for c in (col, col - 1):
                if not reserved[r][c]:
                    bits.append(int(matrix[r][c] ^ mask(r, c)))
        upward, col = not upward, col - 2
    codewords = [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits) - 7, 8)]

    blocks = _M_BLOCKS[version]
    data_stream = [0] * sum(blocks)
    starts = [sum(blocks[:b]) for b in range(len(blocks))]
    for i, word in enumerate(codewords[: sum(blocks)]):  # equal blocks: round-robin
        data_stream[starts[i % len(blocks)] + i // len(blocks)] = word
    stream = "".join(f"{word:08b}" for word in data_stream)
    assert stream[:4] == "0100", "byte mode"
    count = int(stream[4:12], 2)
    text = bytes(int(stream[12 + 8 * i : 20 + 8 * i], 2) for i in range(count))
    return level, text.decode()


def _strings(group: Group) -> list[String]:
    found: list[String] = []
    for item in group.contents:
        if isinstance(item, String):
            found.append(item)
        elif isinstance(item, Group):
            found.extend(_strings(item))
    return found


def test_the_card_defaults_are_the_stock_hotspot(card: ModuleType) -> None:
    assert card.DEFAULT_SSID == DEFAULT_CONFIG["ap"]["ssid"]
    assert card.DEFAULT_PSK == DEFAULT_CONFIG["ap"]["psk"] == ""
    assert card.DEFAULT_URL == f"http://{HOTSPOT_IP.split('/')[0]}"


def test_wifi_payload_follows_the_wifi_qr_format(card: ModuleType) -> None:
    assert card.wifi_payload("VibeSensor", "") == "WIFI:T:nopass;S:VibeSensor;;"
    assert card.wifi_payload("My;Car", 'pa:ss,wo"rd\\') == (
        'WIFI:T:WPA;S:My\\;Car;P:pa\\:ss\\,wo\\"rd\\\\;;'
    )
    hex_psk = "0123456789abcdef" * 4  # a raw 256-bit PSK
    assert card.wifi_payload("Car", hex_psk) == f"WIFI:T:WPA;S:Car;P:{hex_psk};;"
    bad = (("", ""), ("x" * 33, ""), ("Car", "short"), ("Car", "x" * 64), ("Car", "é" * 8))
    for ssid, psk in bad:
        with pytest.raises(ValueError):
            card.wifi_payload(ssid, psk)


@pytest.mark.parametrize(
    "payload",
    [
        "WIFI:T:nopass;S:VibeSensor;;",
        "http://10.4.0.1",
        "WIFI:T:WPA;S:Werkplaats 3;P:" + "k" * 63 + ";;",  # version 6, four blocks
    ],
)
def test_qr_symbols_decode_to_their_payload(card: ModuleType, payload: str) -> None:
    assert _decode(card.qr_matrix(payload)) == ("M", payload)


def test_the_card_keeps_quiet_zones_clear_and_states_the_network(card: ModuleType) -> None:
    drawing = card.card_drawing("Werkplaats 3", "geheim-wachtwoord", "http://10.4.0.1")
    symbols = [item for item in drawing.contents if isinstance(item, Group)]
    texts = _strings(drawing)

    assert [text.text for text in texts] == [
        "1. Join the Wi-Fi",
        "Network: Werkplaats 3",
        "Password: geheim-wachtwoord",
        "2. Open VibeSensor",
        "http://10.4.0.1",
        "If the phone says no internet, stay connected.",
    ]
    assert len(symbols) == 2
    payloads = (card.wifi_payload("Werkplaats 3", "geheim-wachtwoord"), "http://10.4.0.1")
    for symbol, payload in zip(symbols, payloads, strict=True):
        x0, y0, x1, y1 = symbol.getBounds()
        quiet = card.QUIET_ZONE_MODULES * (x1 - x0) / len(card.qr_matrix(payload))
        box = (x0 - quiet, y0 - quiet, x1 + quiet, y1 + quiet)
        assert box[0] >= 0 and box[1] >= 0
        assert box[2] <= card.CARD_WIDTH and box[3] <= card.CARD_HEIGHT
        for text in texts:
            tx0, ty0, tx1, ty1 = text.getBounds()
            overlaps = tx0 < box[2] and tx1 > box[0] and ty0 < box[3] and ty1 > box[1]
            assert not overlaps, text.text


def test_the_committed_example_is_the_generator_output(card: ModuleType, tmp_path: Path) -> None:
    """hardware/qr_card_example.* is the stock open network: no credentials, reproducible."""
    svg, pdf = card.write_card(
        tmp_path / "card", ssid=card.DEFAULT_SSID, psk=card.DEFAULT_PSK, url=card.DEFAULT_URL
    )

    assert svg.read_bytes() == _EXAMPLE.with_suffix(".svg").read_bytes()
    assert pdf.read_bytes() == _EXAMPLE.with_suffix(".pdf").read_bytes()
    example_svg = _EXAMPLE.with_suffix(".svg").read_text(encoding="utf-8")
    assert 'width="85.6mm" height="54mm"' in example_svg
    for line in ("Network: VibeSensor", "Password: none (open network)", "http://10.4.0.1"):
        assert f">{line}</text>" in example_svg


def test_the_cli_writes_both_files_and_rejects_a_bad_psk(card: ModuleType, tmp_path: Path) -> None:
    assert card.main(["--out", str(tmp_path / "c"), "--ssid", "Car", "--psk", "12345678"]) == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["c.pdf", "c.svg"]
    with pytest.raises(SystemExit):
        card.main(["--out", str(tmp_path / "d"), "--psk", "short"])
