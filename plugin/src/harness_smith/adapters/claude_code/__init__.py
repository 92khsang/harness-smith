"""The Claude Code runtime adapter: the locations this runtime defines and loads from.

Everything Claude-Code-specific lives here, split by the Surface each scan walks. A repository
is scanned at the locations the runtime reads a project's own harness from; a plugin is scanned
at the locations its manifest and the runtime's defaults put its components in. Locations the
Harness Standard prescribes, and artifacts found because something points at them, are the
other two discovery layers and belong to neither.

One scan reads exactly what its request names. The ambient environment is not a source here:
the roots come from the caller and the runtime sources come from a snapshot someone else
collected, so a run cannot depend on the machine it happened to run on.
"""

from __future__ import annotations

from harness_smith.adapters.claude_code.evidence import discover_evidence
from harness_smith.adapters.claude_code.plugin import discover_plugin
from harness_smith.adapters.claude_code.repository import discover as discover_repository
from harness_smith.artifacts import Discovery, DiscoveryReport
from harness_smith.scan import DiscoveryRequest

__all__ = ["discover", "discover_evidence", "discover_plugin", "discover_repository"]


def discover(request: DiscoveryRequest) -> Discovery:
    """Scan everything ``request`` names, as one Discovery.

    Which plugin roots to scan is the caller's to decide, not this scan's: a root arrives named
    or it is not scanned. Runtime evidence is read from the snapshot the request carries and
    from nowhere else, so a request without one produces the same report on every machine.
    """
    scans = [discover_repository(request.repository_root)]
    scans.extend(discover_plugin(root) for root in request.plugin_roots)
    if request.runtime_evidence is not None:
        scans.append(discover_evidence(request.runtime_evidence))
    return Discovery(
        report=DiscoveryReport(
            artifacts=tuple(entry for scan in scans for entry in scan.report.artifacts),
            containers=tuple(entry for scan in scans for entry in scan.report.containers),
            observations=tuple(entry for scan in scans for entry in scan.report.observations),
        ),
        diagnostics=tuple(entry for scan in scans for entry in scan.diagnostics),
        hooks=tuple(entry for scan in scans for entry in scan.hooks),
    )
