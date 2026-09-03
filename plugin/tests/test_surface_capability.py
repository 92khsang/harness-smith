"""The Capability Policy table: one row per Surface, and nothing else deciding it.

Capability Policy is a function of Scope alone. A caller that composed its own values would be
answering a different question — whether an operation applies to a thing, or who owns it — in
this one's name.
"""

from __future__ import annotations

import pytest

from harness_smith.adapters.claude_code.capability import SURFACE_CAPABILITY, capability
from harness_smith.artifacts import CapabilityPolicy, CapabilityValue, Scope

MANAGED = CapabilityValue.MANAGED
OBSERVED_ONLY = CapabilityValue.OBSERVED_ONLY
UNSUPPORTED = CapabilityValue.UNSUPPORTED

# The Surface Runtime Capability table of the specification, restated rather than imported, so
# that changing the implementation's table without changing the specification fails here.
SPECIFIED = {
    Scope.REPOSITORY: CapabilityPolicy(MANAGED, MANAGED, MANAGED, MANAGED),
    Scope.PLUGIN: CapabilityPolicy(MANAGED, MANAGED, MANAGED, MANAGED),
    Scope.USER_GLOBAL: CapabilityPolicy(MANAGED, OBSERVED_ONLY, OBSERVED_ONLY, UNSUPPORTED),
    Scope.EXTERNAL: CapabilityPolicy(MANAGED, OBSERVED_ONLY, OBSERVED_ONLY, UNSUPPORTED),
    Scope.MANAGED_POLICY: CapabilityPolicy(MANAGED, OBSERVED_ONLY, OBSERVED_ONLY, UNSUPPORTED),
}


def test_every_surface_has_exactly_one_row() -> None:
    assert set(SURFACE_CAPABILITY) == set(Scope)


@pytest.mark.parametrize("scope", list(Scope))
def test_each_row_is_the_one_the_specification_states(scope: Scope) -> None:
    assert capability(scope) == SPECIFIED[scope]


def test_a_surface_that_permits_the_same_things_is_still_its_own_surface() -> None:
    """Managed policy, user-global and external agree on every capability. That is a fact about
    what may be done, not a reason to give them one Scope."""
    agreeing = {Scope.MANAGED_POLICY, Scope.USER_GLOBAL, Scope.EXTERNAL}

    assert len({capability(scope) for scope in agreeing}) == 1
    assert len(agreeing) == 3
