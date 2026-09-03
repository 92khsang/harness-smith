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
    EvidenceSource,
    EvidenceStatus,
    RuntimeEvidenceSnapshot,
    SettingsLayer,
)

USER_SETTINGS = "~/.claude/settings.json"
DROPIN_DIRECTORY = "/etc/claude-code/managed-settings.d"


def document(**changes: object) -> EvidenceDocument:
    fields: dict[str, object] = {
        "source": EvidenceSource.USER_SETTINGS,
        "scope": Scope.USER_GLOBAL,
        "layer": SettingsLayer.USER,
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
        layer=SettingsLayer.POLICY,
        locator=DROPIN_DIRECTORY,
        status=EvidenceStatus.PRESENT,
    )

    assert directory.entries == ()
    assert directory.status is EvidenceStatus.PRESENT


def test_a_drop_in_directory_keeps_the_entries_that_were_observed() -> None:
    directory = EvidenceDirectory(
        source=EvidenceSource.MANAGED_POLICY_DROPIN_DIRECTORY,
        scope=Scope.MANAGED_POLICY,
        layer=SettingsLayer.POLICY,
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
            layer=SettingsLayer.POLICY,
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
        layer=SettingsLayer.PROJECT_LOCAL,
        locator=".claude/settings.local.json",
    )

    assert local.scope is Scope.REPOSITORY
    assert local.layer is SettingsLayer.PROJECT_LOCAL
