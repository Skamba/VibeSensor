from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED_ROOT = ROOT / "apps" / "server" / "vibesensor" / "shared"
LOCATIONS_PATH = SHARED_ROOT / "locations.py"
STRENGTH_FIELDS_PATH = SHARED_ROOT / "strength_fields.py"


def _load_dict_constant(module_path: Path, constant_name: str) -> dict[str, str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    for node in tree.body:
        value_node: ast.expr | None = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
            if (
                isinstance(target, ast.Name)
                and target.id == constant_name
                and node.value is not None
            ):
                value_node = node.value
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == constant_name:
                    value_node = node.value
                    break
        if value_node is None:
            continue
        value = ast.literal_eval(value_node)
        if not isinstance(value, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in value.items()
        ):
            msg = f"{module_path}::{constant_name} must be a dict[str, str] literal"
            raise ValueError(msg)
        return dict(value)
    msg = f"Could not find {constant_name} in {module_path}"
    raise ValueError(msg)


def render_ui_shared_constants_module() -> str:
    location_codes = _load_dict_constant(LOCATIONS_PATH, "LOCATION_CODES")
    metric_fields = _load_dict_constant(STRENGTH_FIELDS_PATH, "METRIC_FIELDS")
    return (
        "// Generated from apps/server/vibesensor/shared/locations.py and "
        "apps/server/vibesensor/shared/strength_fields.py\n"
        "// Do not edit manually; run tools/config/sync_shared_contracts_to_ui.mjs\n\n"
        f"export const METRIC_FIELDS = {json.dumps(metric_fields, indent=2)} as const;\n\n"
        f"export const LOCATION_CODES = {json.dumps(list(location_codes.keys()), indent=2)} as const;\n\n"
        "export const defaultLocationCodes = LOCATION_CODES;\n"
    )


def main() -> None:
    sys.stdout.write(render_ui_shared_constants_module())


if __name__ == "__main__":
    main()
