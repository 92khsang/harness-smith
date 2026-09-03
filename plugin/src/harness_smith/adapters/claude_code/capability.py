"""The Capability Policy for each Surface.

Capability Policy is keyed by Surface alone. It says what this adapter is willing to do with a
Surface at all, and says nothing about which operations apply to a particular thing found
there, nor about who owns it. Those are separate determinations: operation applicability is a
question about the thing, and Management Authority is a question about ownership, which the
Mutation Decision consults after this policy has already permitted mutation for the Surface.

Reading the policy through one table is what keeps that separation mechanical. A caller that
composed its own values would be answering one of the other two questions in this one's name.
"""

from __future__ import annotations

from collections.abc import Mapping

from harness_smith.artifacts import CapabilityPolicy, CapabilityValue, Scope

__all__ = ["SURFACE_CAPABILITY", "capability"]

_MANAGED = CapabilityValue.MANAGED
_OBSERVED_ONLY = CapabilityValue.OBSERVED_ONLY
_UNSUPPORTED = CapabilityValue.UNSUPPORTED

# `plugin` is this repository's own plugin product source; `external` is an installed
# third-party plugin. `observed-only` on structural check means findings are reported and never
# contribute to a pass-or-fail verdict.
SURFACE_CAPABILITY: Mapping[Scope, CapabilityPolicy] = {
    Scope.REPOSITORY: CapabilityPolicy(_MANAGED, _MANAGED, _MANAGED, _MANAGED),
    Scope.PLUGIN: CapabilityPolicy(_MANAGED, _MANAGED, _MANAGED, _MANAGED),
    Scope.EXTERNAL: CapabilityPolicy(_MANAGED, _OBSERVED_ONLY, _OBSERVED_ONLY, _UNSUPPORTED),
    Scope.USER_GLOBAL: CapabilityPolicy(_MANAGED, _OBSERVED_ONLY, _OBSERVED_ONLY, _UNSUPPORTED),
}


def capability(scope: Scope) -> CapabilityPolicy:
    return SURFACE_CAPABILITY[scope]
