"""Guard docs lint command-reference checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from tests._paths import REPO_ROOT

_DOCS_LINT = REPO_ROOT / "tools" / "dev" / "docs_lint.py"


def _load_docs_lint_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("docs_lint_local_for_tests", _DOCS_LINT)
    assert spec is not None and spec.loader is not None, f"Unable to load {_DOCS_LINT}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_make_command_target_lint_rejects_stale_documented_targets(
    tmp_path: Path,
) -> None:
    module = _load_docs_lint_module()
    (tmp_path / "Makefile").write_text(
        ".PHONY: coverage lint\ncoverage:\n\tpytest\nlint:\n\truff check .\n",
        encoding="utf-8",
    )
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    docs_path = docs_dir / "testing.md"
    docs_path.write_text(
        "```bash\nmake coverage\nmake coverage-html\n```\nInline command: `make lint`.\n",
        encoding="utf-8",
    )

    assert module._check_make_command_targets(["docs/testing.md"], tmp_path) == [
        "docs/testing.md: documented make target does not exist: coverage-html"
    ]


def test_docs_lint_rejects_removed_processing_path_references(tmp_path: Path) -> None:
    module = _load_docs_lint_module()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    docs_path = docs_dir / "intake_buffering.md"
    docs_path.write_text(
        "Old path: `infra/processing/fft.py`.\n",
        encoding="utf-8",
    )

    assert module._check_stale_repo_path_references(
        ["docs/intake_buffering.md"],
        tmp_path,
    ) == [
        "docs/intake_buffering.md: stale repo path reference: "
        "infra/processing/fft.py "
        "(use apps/server/vibesensor/shared/fft_analysis.py)"
    ]


def test_npm_run_script_lint_rejects_missing_ui_scripts(tmp_path: Path) -> None:
    module = _load_docs_lint_module()
    ui_dir = tmp_path / "apps" / "ui"
    ui_dir.mkdir(parents=True)
    (ui_dir / "package.json").write_text(
        '{"scripts": {"build": "vite build", "test:unit": "vitest run"}}',
        encoding="utf-8",
    )
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "testing.md").write_text(
        "Good: `npm run build`.\nBad: `npm run test:visual`.\n",
        encoding="utf-8",
    )

    assert module._check_npm_run_scripts(["docs/testing.md"], tmp_path) == [
        "docs/testing.md: documented npm script does not exist in apps/ui/package.json: test:visual"
    ]


def test_ci_job_example_lint_separates_act_and_local_job_ids(tmp_path: Path) -> None:
    module = _load_docs_lint_module()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "testing.md").write_text(
        "\n".join(
            [
                "`act -j backend-tests -W .github/workflows/ci.yml`",
                "`act -j backend-tests-1 -W .github/workflows/ci.yml`",
                "`./.venv/bin/python tools/tests/run_ci_parallel.py --job backend-tests-1`",
                "`./.venv/bin/python tools/tests/run_ci_parallel.py --job backend-tests`",
            ]
        ),
        encoding="utf-8",
    )

    assert module._check_ci_job_examples(
        ["docs/testing.md"],
        tmp_path,
        raw_workflow_job_ids={"backend-tests"},
        local_logical_job_ids={"backend-tests-1"},
    ) == [
        "docs/testing.md: ACT job example must use raw workflow job id: backend-tests-1",
        "docs/testing.md: local CI job example must use logical job id: backend-tests",
    ]


def test_local_logical_ci_job_id_loader_expands_matrix_names(tmp_path: Path) -> None:
    module = _load_docs_lint_module()
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "jobs:",
                "  ci-scope:",
                "    steps: []",
                "  backend-tests:",
                "    strategy:",
                "      matrix:",
                "        include:",
                '          - logical_job_name: "backend-tests-1"',
                '          - logical_job_name: "backend-tests-2"',
                "    steps: []",
                "  docs-lint:",
                "    steps: []",
            ]
        ),
        encoding="utf-8",
    )

    assert module._local_logical_ci_job_ids(tmp_path) == {
        "backend-tests-1",
        "backend-tests-2",
        "docs-lint",
    }


def test_direct_shell_script_command_lint_requires_executable_script(
    tmp_path: Path,
) -> None:
    module = _load_docs_lint_module()
    script_dir = tmp_path / "tools" / "tests"
    script_dir.mkdir(parents=True)
    script_path = script_dir / "run_ci_with_act.sh"
    script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    script_path.chmod(0o644)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "testing.md").write_text(
        "`./tools/tests/run_ci_with_act.sh -j backend-lint`\n",
        encoding="utf-8",
    )

    assert module._check_direct_shell_script_commands(["docs/testing.md"], tmp_path) == [
        "docs/testing.md: documented script command is not executable: "
        "tools/tests/run_ci_with_act.sh"
    ]


def test_design_doc_status_lint_requires_explicit_status(tmp_path: Path) -> None:
    module = _load_docs_lint_module()
    design_dir = tmp_path / "docs" / "designs"
    design_dir.mkdir(parents=True)
    (design_dir / "active.md").write_text(
        "# Active design\n\n> **Status:** Active\n",
        encoding="utf-8",
    )
    (design_dir / "missing.md").write_text(
        "# Missing status\n",
        encoding="utf-8",
    )

    assert module._check_design_doc_status(
        [
            "docs/designs/active.md",
            "docs/designs/missing.md",
        ],
        tmp_path,
    ) == [
        "docs/designs/missing.md: design doc must declare Status: Active, Historical, or Superseded"
    ]


def test_docs_index_lint_requires_every_docs_markdown_file(
    tmp_path: Path,
) -> None:
    module = _load_docs_lint_module()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "README.md").write_text(
        "| File | Description |\n|---|---|\n| `docs/README.md` | Index. |\n",
        encoding="utf-8",
    )
    (docs_dir / "listed.md").write_text("# Listed\n", encoding="utf-8")
    (docs_dir / "missing.md").write_text("# Missing\n", encoding="utf-8")

    assert module._check_docs_index_complete(
        [
            "docs/README.md",
            "docs/listed.md",
            "docs/missing.md",
        ],
        tmp_path,
    ) == [
        "docs/README.md must list docs/listed.md",
        "docs/README.md must list docs/missing.md",
    ]


def test_frontend_guidance_lint_rejects_raw_typecheck_primary_gate(
    tmp_path: Path,
) -> None:
    module = _load_docs_lint_module()
    instructions_dir = tmp_path / ".github" / "instructions"
    instructions_dir.mkdir(parents=True)
    frontend_guidance = instructions_dir / "frontend.instructions.md"
    frontend_guidance.write_text(
        "- Validation: run `cd apps/ui && npm run typecheck && npm run build`.\n",
        encoding="utf-8",
    )

    assert module._check_frontend_guidance_validation(tmp_path) == [
        ".github/instructions/frontend.instructions.md must use make ui-typecheck "
        "as the primary frontend validation gate"
    ]

    frontend_guidance.write_text(
        "- Validation: run `make ui-typecheck`; add `cd apps/ui && npm run build` for bundles.\n",
        encoding="utf-8",
    )

    assert module._check_frontend_guidance_validation(tmp_path) == []


def test_firmware_guidance_lint_requires_ci_native_validation_commands(
    tmp_path: Path,
) -> None:
    module = _load_docs_lint_module()
    instructions_dir = tmp_path / ".github" / "instructions"
    workflow_dir = tmp_path / ".github" / "workflows"
    instructions_dir.mkdir(parents=True)
    workflow_dir.mkdir(parents=True)
    firmware_guidance = instructions_dir / "firmware.instructions.md"
    firmware_guidance.write_text(
        "- Validation: run `cd firmware/esp && pio run`.\n",
        encoding="utf-8",
    )
    (workflow_dir / "ci.yml").write_text(
        "\n".join(
            [
                "run: python tools/firmware/generate_protocol_contract_fixtures.py --check",
                "working-directory: firmware/esp",
                "run: pio test -e native",
            ]
        ),
        encoding="utf-8",
    )

    assert module._check_firmware_guidance_validation(tmp_path) == [
        ".github/instructions/firmware.instructions.md must mention "
        "CI firmware validation command: "
        "python tools/firmware/generate_protocol_contract_fixtures.py --check",
        ".github/instructions/firmware.instructions.md must mention "
        "CI firmware validation command: cd firmware/esp && pio test -e native",
    ]

    firmware_guidance.write_text(
        "- Validation: run `cd firmware/esp && pio run`, "
        "`python tools/firmware/generate_protocol_contract_fixtures.py --check`, "
        "and `cd firmware/esp && pio test -e native`.\n",
        encoding="utf-8",
    )

    assert module._check_firmware_guidance_validation(tmp_path) == []
