"""Registry and spec validation — the rules that keep declarations honest."""

from __future__ import annotations

import pytest

from eidolon_vision.runtime.registry import CapabilityRegistry, RegistryError
from eidolon_vision.runtime.spec import CapabilitySpec, SpecError


def _fact_spec(name: str, triggers: tuple[str, ...]) -> CapabilitySpec:
    return CapabilitySpec(
        name=name,
        serves_triggers=triggers,
        initiative="system-push",
        output="fact",
        authz="standing-lease",
        arbitration=("shared", "safe"),
        needs_roles=("presence",),
        aggregator_factory=lambda: object(),
    )


def test_routes_by_declaration() -> None:
    registry = CapabilityRegistry()
    registry.register(_fact_spec("alpha", ("a_sample",)))
    assert registry.route("a_sample").name == "alpha"
    assert registry.route("unclaimed") is None


def test_duplicate_name_is_rejected() -> None:
    registry = CapabilityRegistry()
    registry.register(_fact_spec("alpha", ("a_sample",)))
    with pytest.raises(RegistryError, match="already registered"):
        registry.register(_fact_spec("alpha", ("other",)))


def test_two_capabilities_cannot_claim_one_trigger() -> None:
    registry = CapabilityRegistry()
    registry.register(_fact_spec("alpha", ("shared_trigger",)))
    with pytest.raises(RegistryError, match="already served"):
        registry.register(_fact_spec("beta", ("shared_trigger",)))


def test_required_roles_is_the_union_of_enabled_capabilities() -> None:
    registry = CapabilityRegistry()
    registry.register(_fact_spec("alpha", ("a",)))
    assert registry.required_roles() == frozenset({"presence"})


def test_unknown_role_is_rejected_at_declaration_time() -> None:
    with pytest.raises(SpecError, match="unknown perceptor roles"):
        CapabilitySpec(
            name="bad",
            serves_triggers=("t",),
            initiative="system-push",
            output="fact",
            authz="standing-lease",
            arbitration=("shared", "safe"),
            needs_roles=("telepathy",),
            aggregator_factory=lambda: object(),
        )


def test_an_answer_must_not_be_aggregated_into_a_fact() -> None:
    with pytest.raises(SpecError, match="must not be aggregated"):
        CapabilitySpec(
            name="bad",
            serves_triggers=("t",),
            initiative="owner-pull",
            output="answer",
            authz="per-request",
            arbitration=("shared", "safe"),
            needs_interpreter=True,
            aggregator_factory=lambda: object(),
        )


def test_standing_work_cannot_be_declared_per_request() -> None:
    with pytest.raises(SpecError, match="revocable lease"):
        CapabilitySpec(
            name="bad",
            serves_triggers=("t",),
            initiative="system-push",
            output="fact",
            authz="per-request",
            arbitration=("shared", "safe"),
            needs_roles=("presence",),
            aggregator_factory=lambda: object(),
        )


def test_shipped_capabilities_declare_valid_specs() -> None:
    """Whatever capabilities exist must all register cleanly together.

    Discovered from the tree rather than listed here — a framework-level test
    that names a capability is the same coupling it is meant to forbid, and it
    would go red the moment one is deleted.
    """
    from pathlib import Path

    from eidolon_vision.app.bootstrap import build_registry

    root = Path(__file__).resolve().parents[1] / "eidolon_vision" / "capabilities"
    found = tuple(
        sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("_"))
    )
    registry = build_registry(found)
    assert registry.names() == found
    # Every declared trigger routes back to exactly the capability that claimed it.
    for name in found:
        spec = registry.get(name)
        for trigger in spec.serves_triggers:
            assert registry.route(trigger) is spec


def test_missing_capability_is_skipped_not_fatal() -> None:
    """Deleting a capability package must degrade, never crash."""
    from eidolon_vision.app.bootstrap import build_registry

    registry = build_registry(("look_on_demand", "deleted_yesterday"))
    assert registry.names() == ("look_on_demand",)
