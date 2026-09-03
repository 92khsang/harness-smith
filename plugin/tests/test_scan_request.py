"""The input contract of one scan: what it is pointed at, and what was observed for it.

Asking for runtime evidence and observing it are different events. These fix the shape that
keeps them apart, and the invariants that stop an unreadable source from reading as a missing
one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_smith.artifacts import Scope
from harness_smith.scan import (
    DiscoveryRequest,
    EvidenceCause,
    EvidenceDirectory,
    EvidenceDocument,
    EvidenceKind,
    EvidenceSource,
    EvidenceStatus,
    EvidenceTarget,
    RuntimeEvidenceSnapshot,
    SettingsLayer,
)

USER_SETTINGS = "~/.claude/settings.json"
DROPIN_DIRECTORY = "/etc/claude-code/managed-settings.d"


def document(**changes: object) -> EvidenceDocument:
    fields: dict[str, object] = {
        "source": EvidenceSource.USER_SETTINGS,
        "scope": Scope.USER_GLOBAL,
        "settings_layer": SettingsLayer.USER,
        "locator": USER_SETTINGS,
        "status": EvidenceStatus.PRESENT,
        "content": b"{}",
    }
    fields.update(changes)
    return EvidenceDocument(**fields)  # type: ignore[arg-type]


def test_a_request_without_runtime_evidence_says_nobody_asked() -> None:
    """`None` is not an empty snapshot. One says the question was never put, the other says it
    was put and answered with nothing."""
    request = DiscoveryRequest(repository_root=Path("/repository"))

    assert request.runtime_evidence is None
    assert request.plugin_roots == ()


def test_a_collected_snapshot_that_found_nothing_is_not_the_same_as_no_snapshot() -> None:
    request = DiscoveryRequest(
        repository_root=Path("/repository"), runtime_evidence=RuntimeEvidenceSnapshot()
    )

    assert request.runtime_evidence == RuntimeEvidenceSnapshot()
    assert request.runtime_evidence is not None


def test_plugin_roots_are_a_product_input_rather_than_runtime_evidence() -> None:
    """Which plugins to scan is something the caller names, not something a machine reveals."""
    request = DiscoveryRequest(
        repository_root=Path("/repository"), plugin_roots=(Path("/repository/plugin"),)
    )

    assert request.plugin_roots == (Path("/repository/plugin"),)
    assert request.runtime_evidence is None


def test_a_present_source_carries_the_bytes_that_were_observed() -> None:
    observed = document(content=b'{"hooks": {}}')

    assert observed.status is EvidenceStatus.PRESENT
    assert observed.content == b'{"hooks": {}}'


@pytest.mark.parametrize(
    ("status", "cause"),
    [
        (EvidenceStatus.ABSENT, None),
        (EvidenceStatus.UNREADABLE, EvidenceCause.READ_FAILED),
        (EvidenceStatus.UNSUPPORTED, EvidenceCause.DELIVERY_NOT_FILE_BASED),
    ],
)
def test_only_a_present_source_carries_content(
    status: EvidenceStatus, cause: EvidenceCause | None
) -> None:
    with pytest.raises(ValueError, match="only a present source"):
        document(status=status, cause=cause, content=b"{}")


def test_an_absent_source_keeps_the_locator_it_was_expected_at() -> None:
    """ "We looked and found nothing" is a different report from "we never looked", and it needs
    to say where it looked."""
    missing = document(status=EvidenceStatus.ABSENT, content=None)

    assert missing.locator == USER_SETTINGS
    assert missing.content is None
    assert missing.cause is None


def test_a_source_with_no_locator_is_refused() -> None:
    with pytest.raises(ValueError, match="Locator it was expected at"):
        document(locator="")


@pytest.mark.parametrize("status", [EvidenceStatus.UNREADABLE, EvidenceStatus.UNSUPPORTED])
def test_an_unresolved_source_says_why(status: EvidenceStatus) -> None:
    with pytest.raises(ValueError, match="a cause says why"):
        document(status=status, content=None)


@pytest.mark.parametrize("status", [EvidenceStatus.PRESENT, EvidenceStatus.ABSENT])
def test_a_resolved_source_carries_no_cause(status: EvidenceStatus) -> None:
    content = b"{}" if status is EvidenceStatus.PRESENT else None
    with pytest.raises(ValueError, match="a cause says why"):
        document(status=status, content=content, cause=EvidenceCause.READ_FAILED)


def test_unreadable_and_absent_are_distinguishable_at_the_same_locator() -> None:
    """The two answers a raw OS failure would otherwise blur together."""
    missing = document(status=EvidenceStatus.ABSENT, content=None)
    unreadable = document(
        status=EvidenceStatus.UNREADABLE, content=None, cause=EvidenceCause.PERMISSION_DENIED
    )

    assert missing != unreadable
    assert missing.locator == unreadable.locator
    assert unreadable.cause is EvidenceCause.PERMISSION_DENIED


def test_a_cause_is_a_stable_value_rather_than_an_operating_system_message() -> None:
    causes = {member.value for member in EvidenceCause}

    assert "permission-denied" in causes
    assert all(cause.islower() and " " not in cause for cause in causes)


def test_a_drop_in_directory_that_is_present_and_empty_says_so() -> None:
    """Missing, unreadable, and present-but-empty are three answers, not one."""
    directory = EvidenceDirectory(
        source=EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
        scope=Scope.MANAGED_POLICY,
        settings_layer=SettingsLayer.MANAGED_POLICY,
        locator=DROPIN_DIRECTORY,
        status=EvidenceStatus.PRESENT,
    )

    assert directory.entries == ()
    assert directory.status is EvidenceStatus.PRESENT


def test_a_drop_in_directory_keeps_the_entries_that_were_observed() -> None:
    directory = EvidenceDirectory(
        source=EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
        scope=Scope.MANAGED_POLICY,
        settings_layer=SettingsLayer.MANAGED_POLICY,
        locator=DROPIN_DIRECTORY,
        status=EvidenceStatus.PRESENT,
        entries=(f"{DROPIN_DIRECTORY}/10-telemetry.json", f"{DROPIN_DIRECTORY}/20-security.json"),
    )

    assert len(directory.entries) == 2


def test_a_directory_that_was_not_observed_holds_no_entries() -> None:
    with pytest.raises(ValueError, match="holds no entries"):
        EvidenceDirectory(
            source=EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
            scope=Scope.MANAGED_POLICY,
            settings_layer=SettingsLayer.MANAGED_POLICY,
            locator=DROPIN_DIRECTORY,
            status=EvidenceStatus.ABSENT,
            entries=(f"{DROPIN_DIRECTORY}/10-telemetry.json",),
        )


def test_a_settings_layer_is_not_a_scope() -> None:
    """A project-local overlay affects one project, like the settings it overlays, and being an
    overlay is what the layer records. Neither is derivable from the other."""
    local = document(
        source=EvidenceSource.PROJECT_LOCAL_SETTINGS,
        scope=Scope.REPOSITORY,
        settings_layer=SettingsLayer.PROJECT_LOCAL,
        locator=".claude/settings.local.json",
    )

    assert local.scope is Scope.REPOSITORY
    assert local.settings_layer is SettingsLayer.PROJECT_LOCAL


def directory(**changes: object) -> EvidenceDirectory:
    fields: dict[str, object] = {
        "source": EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
        "scope": Scope.MANAGED_POLICY,
        "settings_layer": SettingsLayer.MANAGED_POLICY,
        "locator": DROPIN_DIRECTORY,
        "status": EvidenceStatus.PRESENT,
    }
    fields.update(changes)
    return EvidenceDirectory(**fields)  # type: ignore[arg-type]


DROPIN_TARGET = EvidenceTarget(
    source=EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
    kind=EvidenceKind.DIRECTORY,
    scope=Scope.MANAGED_POLICY,
    settings_layer=SettingsLayer.MANAGED_POLICY,
    locator=DROPIN_DIRECTORY,
)


def dropin(name: str) -> EvidenceDocument:
    return document(
        source=EvidenceSource.MANAGED_POLICY_DROPIN,
        scope=Scope.MANAGED_POLICY,
        settings_layer=SettingsLayer.MANAGED_POLICY,
        locator=f"{DROPIN_DIRECTORY}/{name}",
    )


USER_TARGET = EvidenceTarget(
    source=EvidenceSource.USER_SETTINGS,
    kind=EvidenceKind.DOCUMENT,
    scope=Scope.USER_GLOBAL,
    settings_layer=SettingsLayer.USER,
    locator=USER_SETTINGS,
)


def local_target(locator: str) -> EvidenceTarget:
    return EvidenceTarget(
        source=EvidenceSource.PROJECT_LOCAL_SETTINGS,
        kind=EvidenceKind.DOCUMENT,
        scope=Scope.REPOSITORY,
        settings_layer=SettingsLayer.PROJECT_LOCAL,
        locator=locator,
    )


def local_document(locator: str) -> EvidenceDocument:
    return document(
        source=EvidenceSource.PROJECT_LOCAL_SETTINGS,
        scope=Scope.REPOSITORY,
        settings_layer=SettingsLayer.PROJECT_LOCAL,
        locator=locator,
    )


def test_a_requested_place_answers_for_itself_even_when_it_is_not_there() -> None:
    """An empty snapshot is a collection that did not run, not a machine with nothing on it."""
    with pytest.raises(ValueError, match="requested and never answered for"):
        RuntimeEvidenceSnapshot(requested=(USER_TARGET,))


def test_a_requested_place_is_answered_by_an_absence() -> None:
    snapshot = RuntimeEvidenceSnapshot(
        requested=(USER_TARGET,),
        documents=(document(status=EvidenceStatus.ABSENT, content=None),),
    )

    assert snapshot.documents[0].status is EvidenceStatus.ABSENT


def test_one_kind_of_source_may_be_asked_about_in_more_than_one_place() -> None:
    """Claude Code reads a project-local file at the repository root and, where an older
    version left one, at the starting directory as well. Coverage counts places."""
    root = "/repository/.claude/settings.local.json"
    started = "/repository/service/.claude/settings.local.json"

    snapshot = RuntimeEvidenceSnapshot(
        requested=(local_target(root), local_target(started)),
        documents=(local_document(root), local_document(started)),
    )

    assert len(snapshot.documents) == 2


def test_one_of_several_places_left_unanswered_is_still_refused() -> None:
    root = "/repository/.claude/settings.local.json"
    started = "/repository/service/.claude/settings.local.json"

    with pytest.raises(ValueError, match="requested and never answered for"):
        RuntimeEvidenceSnapshot(
            requested=(local_target(root), local_target(started)),
            documents=(local_document(root),),
        )


def test_a_place_answered_twice_is_refused() -> None:
    """Two answers to one question, and nothing says which the run saw."""
    with pytest.raises(ValueError, match="answered for once"):
        RuntimeEvidenceSnapshot(
            requested=(USER_TARGET,),
            documents=(document(), document(content=b'{"hooks": {}}')),
        )


def test_a_place_answered_for_and_never_requested_is_refused() -> None:
    with pytest.raises(ValueError, match="never requested"):
        RuntimeEvidenceSnapshot(documents=(document(),))


def test_an_answer_describing_a_different_kind_of_place_is_refused() -> None:
    with pytest.raises(ValueError, match="different kind of place"):
        RuntimeEvidenceSnapshot(
            requested=(local_target(USER_SETTINGS),),
            documents=(document(source=EvidenceSource.PROJECT_LOCAL_SETTINGS),),
        )


def test_a_drop_in_needs_the_directory_that_lists_it() -> None:
    with pytest.raises(ValueError, match="without the directory that lists it"):
        RuntimeEvidenceSnapshot(documents=(dropin("10-a.json"),))


def test_every_entry_the_runtime_would_read_has_been_read() -> None:
    with pytest.raises(ValueError, match="disagree about"):
        RuntimeEvidenceSnapshot(
            requested=(DROPIN_TARGET,),
            documents=(dropin("10-a.json"),),
            directories=(
                directory(
                    entries=(f"{DROPIN_DIRECTORY}/10-a.json", f"{DROPIN_DIRECTORY}/20-b.json")
                ),
            ),
        )


def test_nothing_is_read_that_the_listing_never_showed() -> None:
    with pytest.raises(ValueError, match="disagree about"):
        RuntimeEvidenceSnapshot(
            requested=(DROPIN_TARGET,),
            documents=(dropin("10-a.json"),),
            directories=(directory(entries=(f"{DROPIN_DIRECTORY}/20-b.json",)),),
        )


def test_the_listing_keeps_what_the_runtime_would_skip_without_reading_it() -> None:
    """ "Claude Code ignores hidden files and files that don't end in `.json`". What was seen and
    what was adopted stay separate answers, so the listing keeps both."""
    snapshot = RuntimeEvidenceSnapshot(
        requested=(DROPIN_TARGET,),
        documents=(dropin("10-a.json"),),
        directories=(
            directory(
                entries=(
                    f"{DROPIN_DIRECTORY}/.hidden.json",
                    f"{DROPIN_DIRECTORY}/10-a.json",
                    f"{DROPIN_DIRECTORY}/notes.txt",
                )
            ),
        ),
    )

    assert len(snapshot.directories[0].entries) == 3
    assert len(snapshot.documents) == 1


def test_a_listing_is_ordered_and_holds_each_entry_once() -> None:
    with pytest.raises(ValueError, match="ordered and holds each entry once"):
        RuntimeEvidenceSnapshot(
            requested=(DROPIN_TARGET,),
            directories=(
                directory(
                    entries=(f"{DROPIN_DIRECTORY}/20-b.json", f"{DROPIN_DIRECTORY}/10-a.json")
                ),
            ),
            documents=(dropin("10-a.json"), dropin("20-b.json")),
        )


def test_a_layer_and_a_scope_that_disagree_are_refused() -> None:
    """Each layer sits in exactly one Scope, so the pair is checked rather than trusted."""
    with pytest.raises(ValueError, match="layer is in"):
        document(settings_layer=SettingsLayer.MANAGED_POLICY, scope=Scope.USER_GLOBAL)


def test_plugin_roots_are_canonical_however_a_caller_spelled_them(tmp_path: Path) -> None:
    root = tmp_path / "product"
    root.mkdir()

    request = DiscoveryRequest(
        repository_root=tmp_path,
        plugin_roots=(root, tmp_path / "product" / ".." / "product", root),
    )

    assert request.plugin_roots == (root.resolve(),)


def test_the_order_roots_arrive_in_does_not_survive_into_the_request(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    for root in (first, second):
        root.mkdir()

    assert (
        DiscoveryRequest(repository_root=tmp_path, plugin_roots=(second, first)).plugin_roots
        == DiscoveryRequest(repository_root=tmp_path, plugin_roots=(first, second)).plugin_roots
    )
