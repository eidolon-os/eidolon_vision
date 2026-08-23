"""The decoupling criteria, as tests.

Without these, the layering degrades quietly over a few months and nobody
notices until a capability turns out to be unremovable. Modelled on
``eidolon_kernel/tests/architecture/test_boundaries.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "eidolon_vision"

# Inward-only dependency rule. `app` is the composition layer and may see all.
LAYER_IMPORTS = {
    "runtime": {"runtime"},
    "adapters": {"runtime", "adapters"},
    "capabilities": {"runtime", "capabilities"},
    "app": {"runtime", "adapters", "capabilities", "app"},
}


def _imports(path: Path) -> tuple[str, ...]:
    found: list[str] = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.module is None:
                continue
            found.append(node.module or "")
    return tuple(found)


def _own_layers(module: str) -> set[str]:
    """Which of our layers an absolute import refers to."""
    return {
        layer
        for layer in LAYER_IMPORTS
        if module == layer
        or module.startswith((f"eidolon_vision.{layer}.", f"{layer}."))
    }


def test_layers_exist_and_import_only_inward() -> None:
    violations = []
    for layer, allowed in LAYER_IMPORTS.items():
        assert (PACKAGE / layer).is_dir(), f"missing layer: {layer}"
        for path in (PACKAGE / layer).rglob("*.py"):
            for module in _imports(path):
                for target in _own_layers(module):
                    if target not in allowed:
                        violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, "inward-only rule violated:\n" + "\n".join(violations)


def test_relative_imports_do_not_escape_layer() -> None:
    """A `from ...capabilities.x import y` inside runtime/ would dodge the check above."""
    violations = []
    for layer, allowed in LAYER_IMPORTS.items():
        for path in (PACKAGE / layer).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level and node.module:
                    head = node.module.split(".")[0]
                    if head in LAYER_IMPORTS and head not in allowed:
                        violations.append(f"{path.relative_to(ROOT)} -> {node.module}")
    assert not violations, "relative import escaped its layer:\n" + "\n".join(violations)


def test_runtime_never_names_a_capability() -> None:
    """The harsh one. It is what catches `detectors["fatigue_sample"]`.

    Capability names are discovered from the capabilities/ tree rather than
    hard-coded, so adding a capability cannot silently escape this check.
    """
    names = sorted(
        p.name
        for p in (PACKAGE / "capabilities").iterdir()
        if p.is_dir() and not p.name.startswith("_")
    )
    assert names, "no capabilities found — the check would be vacuous"

    violations = []
    for path in (PACKAGE / "runtime").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for name in names:
            if name in text:
                violations.append(f"{path.relative_to(ROOT)} mentions {name!r}")
    assert not violations, "runtime knows a capability by name:\n" + "\n".join(violations)


def test_capability_names_do_not_collide_with_role_names() -> None:
    """Roles and capabilities are different namespaces and must stay distinguishable.

    A capability called the same thing as a role makes the check above
    unusable — the role name legitimately appears all over runtime/ — and makes
    `needs_roles=("x",)` ambiguous to a reader. Cheaper to forbid the collision.
    """
    from eidolon_vision.runtime.types import PERCEPTOR_ROLES

    names = {
        p.name
        for p in (PACKAGE / "capabilities").iterdir()
        if p.is_dir() and not p.name.startswith("_")
    }
    collisions = names & set(PERCEPTOR_ROLES)
    assert not collisions, f"capability name collides with a role: {sorted(collisions)}"


def test_every_capability_declares_a_spec() -> None:
    from eidolon_vision.runtime.spec import CapabilitySpec

    for pkg in (PACKAGE / "capabilities").iterdir():
        if not pkg.is_dir() or pkg.name.startswith("_"):
            continue
        module = __import__(f"eidolon_vision.capabilities.{pkg.name}", fromlist=["SPEC"])
        spec = getattr(module, "SPEC", None)
        assert isinstance(spec, CapabilitySpec), f"{pkg.name} exports no CapabilitySpec"
        assert spec.name == pkg.name, f"{pkg.name}: spec name {spec.name!r} != directory"
