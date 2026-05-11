"""Failure artifact writers for fuzz tooling."""

from __future__ import annotations

import json
import os
import traceback
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path


def write_processing_failure_artifact(
    *,
    target: str,
    case: Mapping[str, object] | None,
    output: Mapping[str, object] | None,
    exc: BaseException,
    artifact_dir: Path,
) -> Path | None:
    if case is None:
        return None
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = (
        artifact_dir / f"{target}-fuzz-failure-{timestamp}-{os.getpid()}.json"
    )
    payload: dict[str, object] = {
        "target": target,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": traceback.format_exc(),
        "case": case,
        "output": output,
    }
    artifact_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return artifact_path


def write_analysis_failure_artifact(
    *,
    case: Mapping[str, object] | None,
    summary: Mapping[str, object] | None,
    exc: BaseException,
    artifact_dir: Path,
) -> Path | None:
    if case is None:
        return None
    artifact_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = "unknown-run"
    metadata = case.get("metadata")
    if isinstance(metadata, Mapping):
        raw_run_id = metadata.get("run_id")
        if isinstance(raw_run_id, str) and raw_run_id.strip():
            run_id = raw_run_id.strip()
    artifact_path = artifact_dir / (
        f"analysis-fuzz-failure-{timestamp}-{os.getpid()}-{run_id}.json"
    )
    payload: dict[str, object] = {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": traceback.format_exc(),
        "case": case,
        "summary": summary,
    }
    artifact_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    return artifact_path
