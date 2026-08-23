"""``CapabilitySpec`` — the declaration that makes a capability governable.

A capability is not a pipeline; it is a *named combination*: who initiates it,
where semantics are computed, what comes out, who authorizes it. Declaring those
fields is what earns a capability its lease, its gate and its audit trail —
"declare and it is governed", per the EID-Capability model.

The runtime knows this shape. It never knows any capability's name.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from .ports import Aggregator
from .types import PERCEPTOR_ROLES, PerceptorRole

Initiative = Literal["owner-pull", "system-push"]
Output = Literal["answer", "fact", "state"]
Authz = Literal["per-request", "standing-lease"]
ArbitrationClass = Literal["shared", "exclusive"]
SafetyClass = Literal["safe", "sensitive"]


class SpecError(ValueError):
    """Raised when a capability declaration is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    name: str

    # The triggers this capability serves. The runtime routes on these instead
    # of hard-coding names, which is the whole reason a capability can be
    # deleted without touching the framework.
    serves_triggers: tuple[str, ...]

    initiative: Initiative
    output: Output
    authz: Authz
    arbitration: tuple[ArbitrationClass, SafetyClass]

    # Roles, not implementations. Bootstrap decides who fills each one.
    needs_roles: tuple[PerceptorRole, ...] = ()

    # Optional ports. Unset means this capability does not use that layer.
    aggregator_factory: Callable[[], Aggregator] | None = None
    needs_interpreter: bool = False

    def __post_init__(self) -> None:
        if not self.serves_triggers:
            raise SpecError(f"{self.name}: must serve at least one trigger")

        unknown = set(self.needs_roles) - PERCEPTOR_ROLES
        if unknown:
            raise SpecError(f"{self.name}: unknown perceptor roles {sorted(unknown)}")

        # These two consistency rules are what stop a capability from quietly
        # becoming a different kind of thing than it declared.
        if self.output == "answer":
            if not self.needs_interpreter:
                raise SpecError(f"{self.name}: answer output requires an interpreter")
            if self.aggregator_factory is not None:
                raise SpecError(f"{self.name}: an answer must not be aggregated into a fact")
        if self.output in ("fact", "state"):
            if self.aggregator_factory is None:
                raise SpecError(f"{self.name}: {self.output} output requires an aggregator")
            if not self.needs_roles:
                raise SpecError(f"{self.name}: {self.output} output requires at least one role")

        # Owner-initiated work is authorized per request; standing work needs a
        # revocable lease. Getting this backwards is how a camera becomes creepy.
        if self.initiative == "owner-pull" and self.authz != "per-request":
            raise SpecError(f"{self.name}: owner-pull must be authorized per request")
        if self.initiative == "system-push" and self.authz != "standing-lease":
            raise SpecError(f"{self.name}: system-push must hold a revocable lease")
