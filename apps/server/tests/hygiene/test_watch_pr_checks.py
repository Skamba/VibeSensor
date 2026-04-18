"""Guard the compact PR check watcher."""

from __future__ import annotations

import importlib.util
import sys

from tests._paths import REPO_ROOT

_WATCH_PR_CHECKS = REPO_ROOT / "tools" / "watch_pr_checks.py"


def _load_watch_pr_checks_module():
    spec = importlib.util.spec_from_file_location(
        "watch_pr_checks_local_for_tests",
        _WATCH_PR_CHECKS,
    )
    assert spec is not None and spec.loader is not None, f"Unable to load {_WATCH_PR_CHECKS}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_snapshot_check_treats_skipped_and_commit_status_success_as_ok() -> None:
    module = _load_watch_pr_checks_module()

    skipped = module._snapshot_check(
        {
            "name": "Backend lint",
            "workflowName": "CI",
            "status": "COMPLETED",
            "conclusion": "SKIPPED",
            "detailsUrl": "https://example.invalid/skipped",
        }
    )
    commit_status = module._snapshot_check(
        {
            "context": "external-ci/build",
            "state": "SUCCESS",
            "targetUrl": "https://example.invalid/status",
        }
    )

    assert skipped.bucket == "ok"
    assert skipped.conclusion == "SKIPPED"
    assert commit_status.bucket == "ok"
    assert commit_status.details_url == "https://example.invalid/status"


def test_actionable_merge_issue_only_flags_real_merge_conflicts() -> None:
    module = _load_watch_pr_checks_module()

    assert module._actionable_merge_issue("BLOCKED", "UNKNOWN") is None
    assert module._actionable_merge_issue("UNKNOWN", "UNKNOWN") is None
    assert module._actionable_merge_issue("DIRTY", "UNKNOWN") == "merge_state=DIRTY"
    assert module._actionable_merge_issue("CLEAN", "CONFLICTING") == "mergeable=CONFLICTING"


def test_main_emits_compact_state_changes_without_repeating_unchanged_pending_polls(
    monkeypatch,
    capsys,
) -> None:
    module = _load_watch_pr_checks_module()
    pending_checks = [
        {
            "name": "Repo hygiene",
            "workflowName": "CI",
            "status": "IN_PROGRESS",
            "detailsUrl": "https://example.invalid/repo-hygiene",
        },
        {
            "name": "UI smoke tests",
            "workflowName": "CI",
            "status": "QUEUED",
            "detailsUrl": "https://example.invalid/ui-smoke",
        },
    ]
    green_checks = [
        {
            "name": "Repo hygiene",
            "workflowName": "CI",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
            "detailsUrl": "https://example.invalid/repo-hygiene",
        },
        {
            "name": "UI smoke tests",
            "workflowName": "CI",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
            "detailsUrl": "https://example.invalid/ui-smoke",
        },
    ]
    responses = iter(
        [
            (pending_checks, "BLOCKED", "UNKNOWN"),
            (pending_checks, "BLOCKED", "UNKNOWN"),
            (green_checks, "BLOCKED", "UNKNOWN"),
        ]
    )
    monotonic_times = iter([0.0, 10.0, 20.0])

    monkeypatch.setattr(module, "_fetch_pr_status", lambda pr, repo: next(responses))
    monkeypatch.setattr(module, "_now_monotonic", lambda: next(monotonic_times))
    monkeypatch.setattr(module, "_now_utc", lambda: "12:00:00")
    monkeypatch.setattr(module, "_sleep", lambda seconds: None)

    rc = module.main(["--pr", "123", "--interval", "1", "--heartbeat", "300"])
    output_lines = capsys.readouterr().out.splitlines()

    assert rc == 0
    assert output_lines == [
        "[12:00:00] PR 123 pending ok=0 running=1 queued=1 total=2",
        "START CI/Repo hygiene",
        "QUEUE CI/UI smoke tests",
        "[12:00:00] PR 123 green ok=2 total=2",
        "DONE CI/Repo hygiene (success)",
        "DONE CI/UI smoke tests (success)",
        "RESULT=ALL_GREEN",
    ]


def test_main_reports_real_failures_with_details_url(monkeypatch, capsys) -> None:
    module = _load_watch_pr_checks_module()

    monkeypatch.setattr(
        module,
        "_fetch_pr_status",
        lambda pr, repo: (
            [
                {
                    "name": "Backend lint",
                    "workflowName": "CI",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                    "detailsUrl": "https://example.invalid/backend-lint",
                }
            ],
            "BLOCKED",
            "UNKNOWN",
        ),
    )
    monkeypatch.setattr(module, "_now_monotonic", lambda: 0.0)
    monkeypatch.setattr(module, "_now_utc", lambda: "12:34:56")

    rc = module.main(["--pr", "321", "--heartbeat", "0"])
    output_lines = capsys.readouterr().out.splitlines()

    assert rc == 2
    assert output_lines == [
        "[12:34:56] PR 321 failing ok=0 running=0 queued=0 failed=1 total=1",
        "FAIL CI/Backend lint (failure) https://example.invalid/backend-lint",
        "RESULT=NON_GREEN",
    ]
