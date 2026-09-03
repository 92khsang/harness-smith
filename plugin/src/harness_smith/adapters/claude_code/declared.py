"""Hooks a Skill or a Subagent declares in its own frontmatter.

A Markdown file is a Skill or a Subagent because of where it sits, which is known before its
frontmatter is opened. Whether it is also a hook container is not: only a readable frontmatter
carrying a ``hooks`` field says so. A file that cannot be read, or whose frontmatter is not a
mapping, therefore stays an Artifact and produces no container, because claiming one would be
asserting a declaration nobody has seen.

The frontmatter is parsed once per file and shared. Artifact discovery owns the file and
frontmatter findings; a failure it already reported is not reported again here, and the hook
findings are raised only for a ``hooks`` value inside a frontmatter that did parse.

What is written down is preserved. The runtime converts a subagent's ``Stop`` into
``SubagentStop`` when it runs one, and registers a skill's hooks for the rest of the session
once the skill is invoked; none of that changes the declaration, and turning it into what the
runtime would do is the effective projection's work, not this inventory's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from harness_smith.adapters.claude_code import hooks as hook_container
from harness_smith.artifacts import (
    ArtifactContainer,
    ArtifactType,
    ContainerFormat,
    ContainerKind,
    HookDeclaration,
    InventoriedArtifact,
    Representation,
    Scope,
)
from harness_smith.diagnostics import Diagnostic
from harness_smith.frontmatter import Frontmatter, FrontmatterState
from harness_smith.vocabulary import Subject, SubjectKind

__all__ = ["Declared", "from_frontmatter"]

HOOKS_FIELD = "hooks"

# What a file's own failure is called, per Artifact Type, so that a remediation names the thing
# the reader has to open.
FINDINGS: Mapping[ArtifactType, Mapping[FrontmatterState, str]] = {
    ArtifactType.SKILL: {
        FrontmatterState.FILE_UNREADABLE: "HS-SKILL-FILE-UNREADABLE",
        FrontmatterState.INVALID: "HS-SKILL-FRONTMATTER-INVALID",
    },
    ArtifactType.AGENT: {
        FrontmatterState.FILE_UNREADABLE: "HS-AGENT-FILE-UNREADABLE",
        FrontmatterState.INVALID: "HS-AGENT-FRONTMATTER-INVALID",
    },
}

KINDS: Mapping[ArtifactType, ContainerKind] = {
    ArtifactType.SKILL: ContainerKind.SKILL_FRONTMATTER,
    ArtifactType.AGENT: ContainerKind.SUBAGENT_FRONTMATTER,
}


@dataclass(frozen=True)
class Declared:
    """What one file declares beyond being itself."""

    containers: tuple[ArtifactContainer, ...] = ()
    artifacts: tuple[InventoriedArtifact, ...] = ()
    declarations: tuple[HookDeclaration, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    def joined(self, other: Declared) -> Declared:
        return Declared(
            self.containers + other.containers,
            self.artifacts + other.artifacts,
            self.declarations + other.declarations,
            self.diagnostics + other.diagnostics,
        )


def finding(
    locator: str, artifact_type: ArtifactType, frontmatter: Frontmatter
) -> Diagnostic | None:
    """The file's own failure, owned by whoever inventories the Artifact so that one unreadable
    file is reported once. A file with no frontmatter is prose, not a broken file."""
    code = FINDINGS[artifact_type].get(frontmatter.state)
    if code is None:
        return None
    return Diagnostic.of(code, Subject(SubjectKind.ARTIFACT, locator), message=frontmatter.reason)


def from_frontmatter(
    locator: str, artifact_type: ArtifactType, scope: Scope, frontmatter: Frontmatter
) -> Declared:
    """The hooks ``locator`` declares, and the container holding them.

    Nothing is produced unless the frontmatter parsed and carries a ``hooks`` field: until then
    there is no evidence this file is a hook container at all.
    """
    if frontmatter.state is not FrontmatterState.PARSED:
        return Declared()
    events = frontmatter.fields.get(HOOKS_FIELD)
    if events is None:
        return Declared()
    kind = KINDS[artifact_type]
    if not isinstance(events, Mapping):
        return _refused(
            locator, kind, scope, f"the `{HOOKS_FIELD}` field is not a mapping of hook events"
        )
    read = hook_container.read_events(events, locator, f"/{HOOKS_FIELD}", scope)
    if read.code:
        return _refused(locator, kind, scope, read.reason, read.code)
    holds = tuple(declaration.locator for declaration in read.declarations)
    return Declared(
        containers=(
            ArtifactContainer(locator, ContainerFormat.YAML_FRONTMATTER, kind, scope, None, holds),
        ),
        artifacts=tuple(
            InventoriedArtifact.runtime_native(
                declaration.locator, ArtifactType.HOOK, scope, Representation.CONTAINER_ENTRY
            )
            for declaration in read.declarations
        ),
        declarations=read.declarations,
    )


def _refused(
    locator: str,
    kind: ContainerKind,
    scope: Scope,
    reason: str,
    code: str = "HS-HOOK-CONTAINER-INVALID",
) -> Declared:
    """The file declares hooks and they could not be read, so the container stays holding
    nothing. That is a different report from a file nobody knows declares hooks at all."""
    return Declared(
        containers=(ArtifactContainer(locator, ContainerFormat.YAML_FRONTMATTER, kind, scope),),
        diagnostics=(Diagnostic.of(code, Subject(SubjectKind.CONTAINER, locator), message=reason),),
    )
