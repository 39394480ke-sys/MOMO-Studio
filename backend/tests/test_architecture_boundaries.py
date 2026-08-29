"""Executable dependency rules for the unified MOMO Studio product architecture."""

from __future__ import annotations

import ast
from pathlib import Path

from momo.settings import repository_root

SOURCE_ROOT = repository_root() / "backend" / "src" / "momo"


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    observed: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            observed.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            observed.append(node.module)
    return tuple(observed)


def _layer_violations(
    relative_root: str,
    forbidden_prefixes: tuple[str, ...],
) -> list[str]:
    layer_root = SOURCE_ROOT / relative_root
    violations: list[str] = []
    for path in sorted(layer_root.rglob("*.py")):
        for imported in _imports(path):
            if imported.startswith(forbidden_prefixes):
                relative = path.relative_to(SOURCE_ROOT)
                violations.append(f"{relative}: {imported}")
    return violations


def test_domain_and_ports_do_not_depend_on_outer_layers() -> None:
    assert (
        _layer_violations(
            "domain",
            (
                "momo.adapters",
                "momo.api",
                "momo.application",
                "momo.ports",
                "momo.settings",
            ),
        )
        == []
    )
    assert (
        _layer_violations(
            "ports",
            (
                "momo.adapters",
                "momo.api",
                "momo.application",
                "momo.settings",
            ),
        )
        == []
    )


def test_application_and_api_routes_cannot_import_concrete_adapters() -> None:
    assert (
        _layer_violations(
            "application",
            ("momo.adapters", "momo.api"),
        )
        == []
    )
    assert (
        _layer_violations(
            "api/routes",
            (
                "momo.adapters",
                "momo.bootstrap",
                "momo.release_bootstrap",
            ),
        )
        == []
    )


def test_adapter_construction_stays_in_explicit_outer_compositions_or_tools() -> None:
    allowed_roots = {
        Path("adapters"),
        Path("bootstrap.py"),
        Path("real_bootstrap.py"),
        Path("release_bootstrap.py"),
        Path("tools"),
    }
    violations: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        relative = path.relative_to(SOURCE_ROOT)
        if any(relative == root or root in relative.parents for root in allowed_roots):
            continue
        for imported in _imports(path):
            if imported.startswith("momo.adapters"):
                violations.append(f"{relative}: {imported}")
    assert violations == []


def test_simulation_composition_cannot_hide_a_real_hardware_backend() -> None:
    imports = _imports(SOURCE_ROOT / "bootstrap.py")
    forbidden = (
        "momo.adapters.motion.real_motion_executor",
        "momo.adapters.hardware.feetech_servo_bus",
        "momo.adapters.hardware.ftservo_commissioning_motion_bus",
        "momo.adapters.hardware.ftservo_raw_direction_bus",
    )
    assert not any(imported.startswith(forbidden) for imported in imports)


def test_product_runtime_has_no_legacy_controller_dependency() -> None:
    runtime_roots = (
        SOURCE_ROOT / "api",
        SOURCE_ROOT / "application",
        SOURCE_ROOT / "domain",
        SOURCE_ROOT / "ports",
    )
    forbidden_markers = ("MOMO_RobotARM", "MOMOarm", "arm_a")
    violations: list[str] = []
    for root in runtime_roots:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if any(marker in text for marker in forbidden_markers):
                violations.append(str(path.relative_to(SOURCE_ROOT)))
    assert violations == []
