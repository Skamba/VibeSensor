#!/usr/bin/env python3
"""Make the printable hotspot card: a Wi-Fi QR code, a URL QR code and the same text.

The card is credit-card sized (85.6 x 54 mm). The left QR code joins the Pi's
hotspot (the ``WIFI:`` payload phone cameras understand), the right one opens
the web UI, and both are repeated as readable text for phones that cannot scan.

Run it with the repo venv (``reportlab`` is a server dependency)::

    .venv/bin/python tools/hardware/make_qr_card.py --out vibesensor_card
    .venv/bin/python tools/hardware/make_qr_card.py --ssid MyCar --psk 'secret pass' --out card

It writes ``<out>.svg`` and ``<out>.pdf``. The defaults are the stock hotspot
(the open ``VibeSensor`` network, ``ap.ssid`` / ``ap.psk`` in
``apps/server/vibesensor/app/config_defaults.py``) and ``http://10.4.0.1``.
A card made with a real PSK prints that PSK: keep it out of the repository.
"""

from __future__ import annotations

import argparse
import re
import string
from collections.abc import Sequence
from pathlib import Path

from reportlab.graphics import renderPDF, renderSVG
from reportlab.graphics.barcode.qrencoder import QR8bitByte, QRCode, QRErrorCorrectLevel
from reportlab.graphics.shapes import Drawing, Group, Rect, String
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth

DEFAULT_SSID = "VibeSensor"
DEFAULT_PSK = ""
DEFAULT_URL = "http://10.4.0.1"

CARD_WIDTH = 85.6 * mm
CARD_HEIGHT = 54.0 * mm
QUIET_ZONE_MODULES = 4  # ISO/IEC 18004 minimum light margin around the symbol
_QR_BOX = 30.0 * mm  # each symbol including its quiet zone
_MARGIN = 4.0 * mm
_FONT = "Helvetica"
_BOLD = "Helvetica-Bold"

# Characters the de-facto WIFI: format (ZXing) requires to be backslash-escaped.
_WIFI_SPECIAL = '\\;,":'


def _escape(value: str) -> str:
    return "".join(f"\\{char}" if char in _WIFI_SPECIAL else char for char in value)


def wifi_payload(ssid: str, psk: str) -> str:
    """The QR text that joins ``ssid``; an empty ``psk`` is an open network."""
    if not ssid or len(ssid.encode()) > 32:
        raise ValueError("the SSID must be 1-32 bytes")
    if not psk:
        return f"WIFI:T:nopass;S:{_escape(ssid)};;"
    is_hex_key = len(psk) == 64 and all(char in string.hexdigits for char in psk)
    printable = all(32 <= ord(char) <= 126 for char in psk)
    if not is_hex_key and not (8 <= len(psk) <= 63 and printable):
        raise ValueError(
            "a WPA PSK is 8-63 printable ASCII characters or 64 hex digits"
        )
    return f"WIFI:T:WPA;S:{_escape(ssid)};P:{_escape(psk)};;"


def qr_matrix(text: str) -> list[list[bool]]:
    """The QR symbol for ``text`` (byte mode, error correction M), dark modules True."""
    code = QRCode(None, QRErrorCorrectLevel.M)
    code.addData(QR8bitByte(text))
    code.make()
    size = code.getModuleCount()
    return [[bool(code.isDark(row, col)) for col in range(size)] for row in range(size)]


def _qr_group(text: str, x: float, y: float) -> Group:
    """The symbol fitted into the square box at (x, y), quiet zone included."""
    matrix = qr_matrix(text)
    size = len(matrix)
    module = _QR_BOX / (size + 2 * QUIET_ZONE_MODULES)
    left = x + QUIET_ZONE_MODULES * module
    top = y + _QR_BOX - QUIET_ZONE_MODULES * module
    group = Group()
    for row, cells in enumerate(matrix):
        col = 0
        while col < size:
            if not cells[col]:
                col += 1
                continue
            run = col
            while run < size and cells[run]:
                run += 1
            # Each rect overlaps the row below by 5% so viewers draw no seam.
            group.add(
                Rect(
                    left + col * module,
                    top - (row + 1.05) * module,
                    (run - col) * module,
                    1.05 * module,
                    fillColor=colors.black,
                    strokeColor=None,
                    strokeWidth=0,
                )
            )
            col = run
    return group


def _text(value: str, x: float, y: float, *, size: float, bold: bool = False) -> String:
    """Left-aligned text shrunk to fit one card column."""
    font = _BOLD if bold else _FONT
    width = CARD_WIDTH / 2 - _MARGIN - 1 * mm
    while size > 4 and stringWidth(value, font, size) > width:
        size -= 0.25
    return String(x, y, value, fontName=font, fontSize=size, fillColor=colors.black)


def card_drawing(ssid: str, psk: str, url: str) -> Drawing:
    """The card: Wi-Fi QR and network text on the left, URL QR and address on the right."""
    if not url.startswith(("http://", "https://")):
        raise ValueError("the URL must start with http:// or https://")
    drawing = Drawing(CARD_WIDTH, CARD_HEIGHT)
    drawing.add(
        Rect(
            0.5,
            0.5,
            CARD_WIDTH - 1,
            CARD_HEIGHT - 1,
            rx=3 * mm,
            ry=3 * mm,
            fillColor=colors.white,
            strokeColor=colors.lightgrey,
            strokeWidth=0.5,
        )
    )
    columns = (_MARGIN, CARD_WIDTH / 2 + 1 * mm)
    qr_bottom = CARD_HEIGHT - _MARGIN - 6 * mm - _QR_BOX
    password = f"Password: {psk}" if psk else "Password: none (open network)"
    panels = (
        ("1. Join the Wi-Fi", wifi_payload(ssid, psk), (f"Network: {ssid}", password)),
        (
            "2. Open VibeSensor",
            url,
            (url, "If the phone says no internet, stay connected."),
        ),
    )
    for x, (heading, payload, lines) in zip(columns, panels, strict=True):
        drawing.add(
            _text(heading, x, CARD_HEIGHT - _MARGIN - 3.5 * mm, size=9, bold=True)
        )
        drawing.add(_qr_group(payload, x, qr_bottom))
        drawing.add(_text(lines[0], x, qr_bottom - 4 * mm, size=8, bold=True))
        drawing.add(_text(lines[1], x, qr_bottom - 8 * mm, size=6))
    return drawing


def _sub_once(pattern: str, replacement: str, text: str) -> str:
    result, count = re.subn(pattern, replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"unexpected reportlab SVG output: {pattern!r} not found")
    return result


def _printable_svg(svg: str) -> str:
    """Make reportlab's SVG print at card size with fonts every viewer has.

    reportlab sizes the SVG in unitless points, rounds the viewBox to whole
    points and names PDF fonts ("Helvetica-Bold") browsers do not know.
    """
    width, height = f"{CARD_WIDTH:.4f}", f"{CARD_HEIGHT:.4f}"
    svg = _sub_once(
        r'<svg width="[^"]*" height="[^"]*"', '<svg width="85.6mm" height="54mm"', svg
    )
    svg = _sub_once(r'viewBox="[^"]*"', f'viewBox="0 0 {width} {height}"', svg)
    svg = _sub_once(r"translate\(0,-\d+\)", f"translate(0,-{height})", svg)
    svg = _sub_once(
        r"<title>[^<]*</title>", "<title>VibeSensor hotspot card</title>", svg
    )
    svg = _sub_once(
        r"<desc>[^<]*</desc>", "<desc>Wi-Fi and web UI QR codes</desc>", svg
    )
    sans = "font-family: Helvetica, Arial, sans-serif;"
    svg = svg.replace("font-family: Helvetica-Bold;", f"{sans} font-weight: bold;")
    return svg.replace("font-family: Helvetica;", sans)


def write_card(out: Path, *, ssid: str, psk: str, url: str) -> tuple[Path, Path]:
    """Write ``<out>.svg`` and ``<out>.pdf``; the PDF is byte-reproducible."""
    drawing = card_drawing(ssid, psk, url)
    svg_path, pdf_path = Path(f"{out}.svg"), Path(f"{out}.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    svg_path.write_text(
        _printable_svg(renderSVG.drawToString(drawing)), encoding="utf-8"
    )
    # invariant: no timestamp or random document ID, so a rerun gives the same bytes.
    renderPDF.drawToFile(drawing, str(pdf_path), invariant=1)
    return svg_path, pdf_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ssid", default=DEFAULT_SSID, help="hotspot SSID (ap.ssid)")
    parser.add_argument(
        "--psk", default=DEFAULT_PSK, help="hotspot PSK (ap.psk); empty = open"
    )
    parser.add_argument("--url", default=DEFAULT_URL, help="address of the web UI")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="output path without suffix (.svg/.pdf added)",
    )
    args = parser.parse_args(argv)
    try:
        paths = write_card(args.out, ssid=args.ssid, psk=args.psk, url=args.url)
    except ValueError as exc:
        parser.error(str(exc))
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
