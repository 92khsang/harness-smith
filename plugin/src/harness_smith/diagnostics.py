"""The diagnostic vocabulary.

Every finding carries a registered ``HS-*`` code. The registry is the single place that
decides a code's severity, its effect on the exit code, and its remediation, so a call site
chooses a code and never re-decides what that code means.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from harness_smith.vocabulary import ExitCode, Severity, Subject

__all__ = ["DIAGNOSTIC_REGISTRY", "Diagnostic", "DiagnosticSpec"]


@dataclass(frozen=True)
class DiagnosticSpec:
    severity: Severity
    exit_effect: ExitCode
    remediation: str


def _registry() -> dict[str, DiagnosticSpec]:
    error_1 = (Severity.ERROR, ExitCode.VIOLATIONS)
    error_2 = (Severity.ERROR, ExitCode.USAGE_ERROR)
    error_3 = (Severity.ERROR, ExitCode.ENVIRONMENT_ERROR)
    warning = (Severity.WARNING, ExitCode.SUCCESS)
    info = (Severity.INFO, ExitCode.SUCCESS)

    entries: dict[str, tuple[tuple[Severity, ExitCode], str]] = {
        # Authority
        "HS-AUTHORITY-CLASSIFICATION-REQUIRED": (
            error_1,
            "Declare `authority` or `managed-by` for the path in the manifest",
        ),
        "HS-AUTHORITY-REVIEW-REQUIRED": (
            warning,
            "Confirm whether an external tool also writes the file, then declare",
        ),
        "HS-AUTHORITY-UNDECLARED-EXTERNAL-WRITER": (
            error_1,
            "Add `managed-by` naming that plugin, or `authority: local` to accept the contest",
        ),
        "HS-AUTHORITY-CONFLICT": (error_1, "Reconcile the manifest with the recorded relation"),
        "HS-AUTHORITY-CONTESTED-WRITE": (
            warning,
            "Accept the hazard, or return the file to the plugin's ownership",
        ),
        "HS-AUTHORITY-LOCK-MANIFEST-MISMATCH": (
            error_1,
            "Re-run the adoption transition through `artifact-manage`",
        ),
        "HS-AUTHORITY-DECLARED-PLUGIN-MISSING": (
            warning,
            "Install the plugin, or remove the declaration",
        ),
        "HS-AUTHORITY-ORPHAN-DECLARATION": (warning, "Remove the declaration"),
        # Consumer relations
        "HS-CONSUMER-PLUGIN-MISSING": (error_1, "Install it, or remove the relation"),
        "HS-CONSUMER-SKILL-MISSING": (
            error_1,
            "Update the relation to the current component name",
        ),
        "HS-CONSUMED-ARTIFACT-MISSING": (error_1, "Restore the file, or remove the relation"),
        "HS-CONSUMER-EVIDENCE-MISSING": (
            error_1,
            "Re-derive the evidence against the installed revision",
        ),
        "HS-CONSUMER-REVISION-MISMATCH": (
            warning,
            "Re-verify the relation and update `source-revision`",
        ),
        "HS-CONSUMER-VERSION-MISMATCH": (warning, "Record `source-revision`, or update `version`"),
        "HS-CONSUMER-BINDING-CHANGED": (warning, "Update `binding` and re-confirm `resolution`"),
        # Rules
        "HS-RULE-FILE-UNREADABLE": (
            error_1,
            "Make the rule readable UTF-8 text, then rerun",
        ),
        "HS-RULE-FRONTMATTER-INVALID": (error_1, "Fix the YAML"),
        "HS-RULE-METADATA-UNREADABLE": (error_1, "Correct the namespaced mapping"),
        "HS-RULE-ENFORCEMENT-UNVERIFIED": (
            error_1,
            "Add a test for the enforcer, or drop the enforcement claim",
        ),
        "HS-RULE-ID-DUPLICATE": (error_1, "Rename one"),
        # Hooks
        "HS-HOOK-CONTAINER-FILE-UNREADABLE": (
            error_1,
            "Make the container readable UTF-8 text, then rerun",
        ),
        "HS-HOOK-CONTAINER-UNPARSEABLE": (error_1, "Fix the JSON syntax"),
        "HS-HOOK-CONTAINER-INVALID": (
            error_1,
            "Correct the hook container's structure, or the declaration value it holds",
        ),
        "HS-HOOK-LOCATOR-UNRESOLVED": (
            error_1,
            "Restore the declaration, or remove the lock entry through `artifact-manage`",
        ),
        "HS-HOOK-LOCATOR-AMBIGUOUS": (
            error_1,
            "Make the declarations distinguishable, or remove the duplicate",
        ),
        "HS-HOOK-RELOCATED": (info, "Apply the lock update proposal"),
        # Structure and placement
        "HS-PLACEMENT-INVALID": (error_1, "Move it, or reclassify it"),
        "HS-ARTIFACT-TYPE-UNKNOWN": (error_1, "Register it, or remove it from the harness"),
        "HS-REFERENCE-DANGLING": (error_1, "Fix or remove the reference"),
        "HS-PROVENANCE-MISSING": (error_1, "Record provenance through `artifact-manage`"),
        "HS-SCOPE-LEAKAGE": (error_1, "Move it to the correct scope"),
        "HS-DEPENDENCY-ON-TRANSIENT-SOURCE": (
            error_1,
            "Rewrite the dependency into a tracked canonical location",
        ),
        "HS-ENFORCEMENT-ORPHAN": (warning, "Point a rule at it, or retire it"),
        "HS-ENFORCEMENT-TARGET-MISSING": (error_1, "Restore the target, or update the relation"),
        "HS-ENFORCEMENT-PLACEMENT-UNKNOWN": (
            warning,
            "Move the enforcer, or record why it lives elsewhere",
        ),
        # Entry point and standard version
        "HS-ENTRYPOINT-DUPLICATE": (error_1, "Keep one"),
        "HS-ENTRYPOINT-CONTRACT-VIOLATION": (error_1, "Apply the proposed relocation"),
        "HS-ENTRYPOINT-BUDGET-EXCEEDED": (
            warning,
            "Route content out, or raise the recorded budget deliberately",
        ),
        "HS-STANDARD-VERSION-INCOMPATIBLE": (
            error_1,
            "Upgrade the repository, or pin an older tool",
        ),
        "HS-STANDARD-UPGRADE-AVAILABLE": (warning, "Run the upgrade path and review the diff"),
        "HS-VALIDATOR-TOO-OLD": (error_1, "Upgrade the plugin"),
        # Plugins, skills, documentation
        "HS-PLUGIN-SHADOWED-DEFAULT-DIR": (
            warning,
            "List the default directory explicitly, or delete it",
        ),
        "HS-PLUGIN-COMPONENT-PATH-ESCAPES-ROOT": (
            warning,
            "Move the component inside the plugin root",
        ),
        "HS-SKILL-NAME-SHADOWED": (warning, "Rename one, or delete the command file"),
        "HS-DOC-UNREGISTERED-IN-RESERVED-PATH": (
            warning,
            "Register it, or move it out of the reserved path",
        ),
        "HS-OVERLAP-IDENTIFIER-COLLISION": (error_1, "Rename one"),
        # Shared and compatibility
        "HS-ARTIFACT-UNACKNOWLEDGED-DRIFT": (
            error_1,
            "Review the diff and adopt it, or restore the pinned content",
        ),
        "HS-EFFECTIVE-HARNESS-UNCERTAIN": (
            warning,
            "Supply the missing evidence, or accept the uncertainty",
        ),
        "HS-HARNESS-RELEVANCE-DOWNGRADED": (
            warning,
            "Re-verify the relation against the installed plugin",
        ),
        "HS-PACKAGE-INVALID": (
            error_1,
            "Fix the reported manifest, hook, or frontmatter problem",
        ),
        "HS-PACKAGE-VALIDATOR-UNAVAILABLE": (error_3, "Install the runtime that provides it"),
        "HS-PACKAGE-VALIDATOR-FAILED": (error_3, "Re-run; if it persists, report it upstream"),
        "HS-CLI-USAGE": (error_2, "Correct the invocation"),
        "HS-REPOSITORY-ROOT-NOT-FOUND": (
            error_2,
            "Run inside a repository, or pass the root explicitly",
        ),
        "HS-MANIFEST-INVALID": (error_2, "Fix the manifest"),
        "HS-LOCK-INVALID": (error_2, "Fix the lock, or regenerate it"),
        "HS-GC-CANDIDATE-UNRECOVERABLE": (
            error_2,
            "Commit or discard the change, or drop the candidate from the selection",
        ),
        "HS-PLAN-DOCUMENT-INVALID": (
            error_2,
            "Re-run the plan phase; do not hand-edit a plan document",
        ),
        "HS-PLAN-STALE": (error_2, "Re-run the plan phase and review the new proposal"),
        "HS-PLAN-RESUMED": (info, "None; the remaining changes were written"),
        "HS-PLAN-ALREADY-APPLIED": (info, "None; nothing needed writing"),
        "HS-RUNTIME-BELOW-MINIMUM": (error_3, "Upgrade the runtime"),
        "HS-COMPAT-UNVERIFIED": (
            warning,
            "Probe this version and update the registry, or accept the risk",
        ),
        "HS-COMPAT-REGRESSION": (error_3, "Treat as a release blocker; the platform changed"),
        "HS-COMPAT-PROBE-UNAVAILABLE": (
            error_3,
            "Install or authenticate the runtime, then re-run",
        ),
        # Environment failures the tool itself can hit before or during dispatch.
        "HS-BOOTSTRAP-FAILED": (
            error_3,
            "Resolve the environment problem reported on stderr, then re-run",
        ),
        "HS-INTERNAL-ERROR": (
            error_3,
            "Re-run with the stderr traceback attached to a bug report",
        ),
    }
    return {
        code: DiagnosticSpec(severity=severity, exit_effect=exit_effect, remediation=remediation)
        for code, ((severity, exit_effect), remediation) in entries.items()
    }


DIAGNOSTIC_REGISTRY: Mapping[str, DiagnosticSpec] = _registry()


@dataclass(frozen=True)
class Diagnostic:
    code: str
    subject: Subject
    message: str
    cause: str | None = None
    affected: tuple[str, ...] = ()

    @classmethod
    def of(
        cls,
        code: str,
        subject: Subject,
        *,
        message: str,
        cause: str | None = None,
        affected: Iterable[str] = (),
    ) -> Diagnostic:
        if code not in DIAGNOSTIC_REGISTRY:
            raise KeyError(f"unregistered diagnostic code: {code}")
        return cls(code, subject, message, cause, tuple(sorted(affected)))

    @property
    def spec(self) -> DiagnosticSpec:
        return DIAGNOSTIC_REGISTRY[self.code]

    @property
    def severity(self) -> Severity:
        return self.spec.severity

    @property
    def exit_effect(self) -> ExitCode:
        return self.spec.exit_effect

    def as_document(self) -> dict[str, object]:
        document: dict[str, object] = {
            "code": self.code,
            "severity": self.severity.value,
            "subject": self.subject.as_document(),
            "message": self.message,
        }
        if self.cause is not None:
            document["cause"] = self.cause
        if self.affected:
            document["affected"] = list(self.affected)
        document["remediation"] = self.spec.remediation
        return document
