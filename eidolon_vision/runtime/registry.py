"""Capability registry: routing by declaration, never by hard-coded name.

This module is the reason ``rm -rf capabilities/<name>/`` is a local operation.
The runtime asks the registry which capability serves a trigger; if nobody
registered one, the answer is ``None`` and the caller degrades. No import of any
capability package appears anywhere in ``runtime/``.
"""

from __future__ import annotations

from .spec import CapabilitySpec


class RegistryError(ValueError):
    """Raised on a duplicate name or a trigger claimed by two capabilities."""


class CapabilityRegistry:
    def __init__(self) -> None:
        self._by_name: dict[str, CapabilitySpec] = {}
        self._by_trigger: dict[str, CapabilitySpec] = {}

    def register(self, spec: CapabilitySpec) -> None:
        if spec.name in self._by_name:
            raise RegistryError(f"capability {spec.name!r} already registered")
        for trigger in spec.serves_triggers:
            existing = self._by_trigger.get(trigger)
            if existing is not None:
                raise RegistryError(
                    f"trigger {trigger!r} already served by {existing.name!r}"
                )
        self._by_name[spec.name] = spec
        for trigger in spec.serves_triggers:
            self._by_trigger[trigger] = spec

    def route(self, trigger: str) -> CapabilitySpec | None:
        """Which capability serves this trigger, if any is enabled."""
        return self._by_trigger.get(trigger)

    def get(self, name: str) -> CapabilitySpec | None:
        return self._by_name.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_name))

    def triggers(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_trigger))

    def required_roles(self) -> frozenset[str]:
        """Every role the enabled set needs — bootstrap checks it can fill these."""
        roles: set[str] = set()
        for spec in self._by_name.values():
            roles.update(spec.needs_roles)
        return frozenset(roles)
