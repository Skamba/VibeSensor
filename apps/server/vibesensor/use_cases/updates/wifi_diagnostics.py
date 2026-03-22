from __future__ import annotations

import logging
from pathlib import Path

from vibesensor.use_cases.updates.models import UpdateIssue
from vibesensor.use_cases.updates.runner import sanitize_log_line

_FAILURE_MARKERS = ("failed", "error", "timeout")
_WIFI_DIAG_DIR = "/var/log/wifi"
_MAX_HOTSPOT_LOG_ISSUES = 5
_WIFI_LOGGER = logging.getLogger(__name__)


def parse_wifi_diagnostics(log_dir: str = _WIFI_DIAG_DIR) -> list[UpdateIssue]:
    """Parse wifi diagnostic files into structured issues."""
    issues: list[UpdateIssue] = []
    log_path = Path(log_dir)
    if not log_path.is_dir():
        return issues

    summary = log_path / "summary.txt"
    if summary.is_file():
        try:
            text = summary.read_text(encoding="utf-8", errors="replace")
            for line in text.splitlines():
                line = line.strip()
                lower_line = line.lower()
                if not lower_line.startswith("status="):
                    continue
                status_value = lower_line.split("=", 1)[1].strip()
                if any(marker in status_value for marker in _FAILURE_MARKERS):
                    issues.append(
                        UpdateIssue(
                            phase="diagnostics",
                            message="Hotspot summary reports failure",
                            detail=sanitize_log_line(line),
                        ),
                    )
        except OSError:
            _WIFI_LOGGER.debug(
                "Unable to read wifi summary diagnostics from %s",
                summary,
                exc_info=True,
            )

    hotspot_log = log_path / "hotspot.log"
    if hotspot_log.is_file():
        try:
            text = hotspot_log.read_text(encoding="utf-8", errors="replace")
            hotspot_issues: list[UpdateIssue] = []
            for line in text.splitlines()[-100:]:
                lower = line.lower()
                if any(marker in lower for marker in _FAILURE_MARKERS):
                    hotspot_issues.append(
                        UpdateIssue(
                            phase="diagnostics",
                            message="Hotspot log issue",
                            detail=sanitize_log_line(line),
                        ),
                    )
                    if len(hotspot_issues) >= _MAX_HOTSPOT_LOG_ISSUES:
                        break
            issues.extend(hotspot_issues)
        except OSError:
            _WIFI_LOGGER.debug(
                "Unable to read hotspot diagnostics from %s",
                hotspot_log,
                exc_info=True,
            )

    return issues
