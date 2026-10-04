"""Minimal ESP-IDF NVS page reader so tests can check what a sensor would load."""

from __future__ import annotations

_PAGE_SIZE = 4096
_ENTRIES_OFFSET = 64
_ENTRY_SIZE = 32
_TYPE_U8 = 0x01
_TYPE_STRING = 0x21


def read_nvs_strings(image: bytes) -> dict[str, dict[str, str]]:
    """Return ``{namespace: {key: string}}`` for every string entry in *image*."""
    namespaces: dict[int, str] = {}
    strings: dict[int, dict[str, str]] = {}
    for page_start in range(0, len(image), _PAGE_SIZE):
        page = image[page_start : page_start + _PAGE_SIZE]
        index = 0
        while index < (_PAGE_SIZE - _ENTRIES_OFFSET) // _ENTRY_SIZE:
            start = _ENTRIES_OFFSET + index * _ENTRY_SIZE
            entry = page[start : start + _ENTRY_SIZE]
            ns_index, kind, span = entry[0], entry[1], max(entry[2], 1)
            if ns_index == 0xFF:
                break
            key = entry[8:24].split(b"\0", 1)[0].decode()
            if ns_index == 0 and kind == _TYPE_U8:
                namespaces[entry[24]] = key
            elif kind == _TYPE_STRING:
                size = int.from_bytes(entry[24:26], "little")
                data = page[start + _ENTRY_SIZE : start + _ENTRY_SIZE + size]
                strings.setdefault(ns_index, {})[key] = data.rstrip(b"\0").decode()
            index += span
    return {namespaces[ns]: values for ns, values in strings.items()}
