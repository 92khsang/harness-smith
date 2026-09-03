"""The Claude Code runtime adapter: the locations this runtime defines and loads from.

Everything Claude-Code-specific lives here, split by the Surface each scan walks. A repository
is scanned at the locations the runtime reads a project's own harness from; a plugin is scanned
at the locations its manifest and the runtime's defaults put its components in. Locations the
Harness Standard prescribes, and artifacts found because something points at them, are the
other two discovery layers and belong to neither.
"""

from __future__ import annotations

from harness_smith.adapters.claude_code.repository import discover

__all__ = ["discover"]
