from __future__ import annotations

from ...runtime.spec import CapabilitySpec

# Uses three of the seven layers — source, interpreter, sink — and declares
# nothing else. Relevance is guaranteed because the owner asked, so there is no
# gate, no tracker and no aggregator to reason about, and the answer never
# becomes a fact.
SPEC = CapabilitySpec(
    name="look_on_demand",
    serves_triggers=("user_look",),
    initiative="owner-pull",
    output="answer",
    authz="per-request",
    arbitration=("shared", "safe"),
    needs_roles=(),
    needs_interpreter=True,
)
