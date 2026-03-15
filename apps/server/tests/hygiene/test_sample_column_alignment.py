"""Hygiene test: sample column definitions must stay aligned across 4 sources.

The same sample field set is defined independently in:
- Schema DDL (``_schema.py`` ``samples_v2`` table)
- Insertion columns (``_samples.py`` ``_V2_TYPED_COLS + _V2_PEAK_COLS``)
- Domain model (``domain_models.py`` ``SensorFrame``)
- CSV export (``exports.py`` ``EXPORT_CSV_COLUMNS``)

A typo or omission in any of these produces silent NULL insertion or missing
export columns.  This test enforces that the core column set (excluding
source-specific extras) stays consistent.
"""

from __future__ import annotations

import dataclasses

from vibesensor.adapters.persistence.history_db._samples import _V2_PEAK_COLS, _V2_TYPED_COLS
from vibesensor.adapters.persistence.history_db._schema import SCHEMA_SQL
from vibesensor.use_cases.history.exports import EXPORT_CSV_COLUMNS
from vibesensor.adapters.udp.protocol import SensorFrame

# Known source-specific columns that are intentionally absent from other sources.
_DDL_ONLY = {"id"}  # autoincrement PK
_DOMAIN_ONLY = {"record_type", "schema_version"}  # runtime metadata
_EXPORT_ONLY = {"extras"}  # synthetic overflow column


def _ddl_columns() -> list[str]:
    """Extract column names from the samples_v2 CREATE TABLE statement."""
    # Find the CREATE TABLE block — handle nested parens in REFERENCES clauses.
    start = SCHEMA_SQL.lower().index("create table")
    start = SCHEMA_SQL.lower().index("samples_v2", start)
    paren_start = SCHEMA_SQL.index("(", start)
    depth, pos = 1, paren_start + 1
    while depth > 0 and pos < len(SCHEMA_SQL):
        if SCHEMA_SQL[pos] == "(":
            depth += 1
        elif SCHEMA_SQL[pos] == ")":
            depth -= 1
        pos += 1
    body = SCHEMA_SQL[paren_start + 1 : pos - 1]
    cols: list[str] = []
    for line in body.split(","):
        line = line.strip()
        if not line or line.upper().startswith(("PRIMARY", "FOREIGN", "UNIQUE", "CHECK")):
            continue
        col_name = line.split()[0].strip('"')
        cols.append(col_name)
    return cols


def _insert_columns() -> list[str]:
    """Column names used for insertion (typed + peak cols)."""
    return list(_V2_TYPED_COLS) + list(_V2_PEAK_COLS)


def _domain_fields() -> list[str]:
    return [f.name for f in dataclasses.fields(SensorFrame)]


def _export_columns() -> list[str]:
    return list(EXPORT_CSV_COLUMNS)


class TestSampleColumnAlignment:
    def test_insert_columns_match_ddl(self) -> None:
        ddl = set(_ddl_columns()) - _DDL_ONLY
        insert = set(_insert_columns())
        assert ddl == insert, f"DDL↔insert mismatch: {ddl.symmetric_difference(insert)}"

    def test_domain_fields_cover_ddl(self) -> None:
        ddl = set(_ddl_columns()) - _DDL_ONLY
        domain = set(_domain_fields()) - _DOMAIN_ONLY
        missing_from_domain = ddl - domain
        assert not missing_from_domain, (
            f"DDL columns missing from SensorFrame: {missing_from_domain}"
        )

    def test_export_columns_cover_ddl(self) -> None:
        ddl = set(_ddl_columns()) - _DDL_ONLY
        export = set(_export_columns()) - _EXPORT_ONLY
        missing_from_export = ddl - export
        assert not missing_from_export, (
            f"DDL columns missing from EXPORT_CSV_COLUMNS: {missing_from_export}"
        )

    def test_no_unexpected_extras_in_domain(self) -> None:
        ddl = set(_ddl_columns()) - _DDL_ONLY
        domain = set(_domain_fields()) - _DOMAIN_ONLY
        unexpected = domain - ddl
        assert not unexpected, (
            f"SensorFrame has fields not in DDL (add to _DOMAIN_ONLY if intentional): {unexpected}"
        )

    def test_no_unexpected_extras_in_export(self) -> None:
        ddl = set(_ddl_columns()) - _DDL_ONLY
        export = set(_export_columns()) - _EXPORT_ONLY
        unexpected = export - ddl
        assert not unexpected, (
            "EXPORT_CSV_COLUMNS has entries not in DDL"
            f" (add to _EXPORT_ONLY if intentional): {unexpected}"
        )
