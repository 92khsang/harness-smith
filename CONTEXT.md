# harness-smith

harness-smith authors and governs the repository-owned harness while auditing externally supplied harness surfaces. It ships as a Claude Code plugin, and this repository is itself one of its consumers.

## Language

### Harness

**Agent Harness**:
The set of artifacts and configuration intentionally installed or declared to govern an agent's persistent runtime behaviour. Documents an agent merely happens to read, source code, and ad-hoc investigation material are not part of it.
_Avoid_: harness (unqualified), agent config, prompt setup

**Effective Harness**:
The Agent Harness actually active in a given session — repository artifacts, user-global settings, installed plugins, and runtime configuration combined.
_Avoid_: full harness, runtime harness, active configuration

**Harness Toolchain**:
This project: the tooling that authors, validates, composes, and cleans up harness artifacts.
_Avoid_: the plugin, the framework, harness manager

**Methodology Plugin**:
An externally supplied plugin that provides a development methodology — planning, TDD, debugging, review, shipping. It occupies part of the Effective Harness and is never owned or modified by the Harness Toolchain.
_Avoid_: primary harness, development harness, workflow plugin

**Design Reference**:
A temporary input consulted only while making a design decision. Never canonical, never part of any harness, never referenced by a shipped artifact. Deleting every Design Reference must leave the product fully working.
_Avoid_: scratch docs, notes, temp files

### Artifacts and surfaces

**Artifact**:
A single discovered and classifiable unit of one declared Artifact Type. Whether harness-smith governs it is a separate question, answered by Governed Artifact and Observed Artifact.
_Avoid_: file, resource, asset

**Rule**:
An Artifact stating a constraint an agent must follow. It is the normative authority for that constraint whether or not anything checks it mechanically.
_Avoid_: guideline, convention, policy

**Enforcement**:
An Artifact that mechanically decides whether the current state satisfies a Rule. It is the deterministic verdict authority and never redefines the Rule it checks.
_Avoid_: check, gate, validation (too broad)

**Surface**:
A boundary that groups artifacts by where they live: repository, plugin, user-global, external, or managed-policy. A Surface is an identity and a reach, not a set of permissions, so two Surfaces whose Capability Policy rows agree are still two Surfaces.
_Avoid_: container, area, layer

**Artifact Container**:
A file holding zero or more Artifacts addressed by pointer rather than by path, such as a settings file holding hook declarations.
_Avoid_: surface (reserved for scope boundaries), config file

**Locator**:
Where an Artifact is found right now: a path, or a path and a pointer into an Artifact Container. A Locator is a position, not an identity, and may change without the Artifact changing.
_Avoid_: id, identity, address

**Declaration Digest**:
The lowercase SHA-256 of the RFC 8785 canonical bytes of one declaration held in an Artifact Container, taken over that declaration alone. It recognises a lock-tracked Hook that moved within its container, is a different measurement from a digest of the containing file, and is never serialised into a Discovery Report.
_Avoid_: fingerprint, hook hash, file digest

**Runtime Adapter**:
The mapping from one agent runtime's own layout and loading rules to this project's artifact model. v1 has exactly one, for Claude Code.
_Avoid_: backend, driver, provider

### Discovery

**Discovery Report**:
What one scan produces: an Artifact Inventory, a Container Inventory, and Runtime Component Observations. Runtime surfaces with no declared type appear as observations, never as Artifacts.
_Avoid_: scan result, audit

**Artifact Inventory**:
The part of a Discovery Report holding only Artifacts of declared types.
_Avoid_: file list, catalogue

### Classification

**Scope**:
Which Surface an Artifact belongs to.

**Representation**:
How an Artifact is written down, where the runtime accepts a type in more than one form. A command-form skill is a Skill in its legacy-command representation, not a type of its own.
_Avoid_: format, kind, variant

**Provenance**:
Where an Artifact's content came from and how it got here — authored, generated, imported, or adopted. Provenance is history and never implies who may write it now.
_Avoid_: origin, source (ambiguous with a relation's source)

**Management Authority**:
Who may write an Artifact now. Resolving to unknown refuses mutation rather than presuming permission.
_Avoid_: ownership, provenance

**Capability Policy**:
What the Runtime Adapter permits for a Surface, per capability: inventory, structural check, lifecycle advice, mutation. A permissive mutation value is a precondition, not permission.
_Avoid_: support level, access level

**Activation**:
A report-only projection of whether a declared Artifact is active in the Effective Harness. Active means positive evidence of activation, inactive means a confirmed blocker, unknown means the runtime or policy evidence needed to decide is unavailable. Never stored.
_Avoid_: effectiveness, enabled, status

### Relations

**Relation**:
A declared link from one Artifact to something it depends on or is depended on by, carrying the evidence that justifies it.
_Avoid_: reference, link, dependency

**Consumer**:
Something outside this repository that reads an Artifact as part of doing work. A Consumer relation records the reading party, its version, and the evidence.
_Avoid_: reader, client, user

**Writer**:
Something outside this repository that writes or regenerates an Artifact. Being a Consumer is no evidence of being a Writer; the two are recorded separately.
_Avoid_: owner, generator

### Governance sets

Each set is a derived query. Depending on the set, the query reads the Discovery Report, Capability Policy, Management Authority, Relations, harness relevance, and Activation. No set is a label stored on an Artifact.

**Inventoried Artifact**:
An Artifact the scan discovers at all.

**Governed Artifact**:
An Inventoried Artifact whose structural policy harness-smith applies authoritatively.
_Avoid_: managed artifact (that is narrower)

**Managed Artifact**:
A Governed Artifact harness-smith may mutate through an explicit operation.

**Advisory Artifact**:
A Governed Artifact harness-smith may only propose changes to, never write.

**Unclassified Artifact**:
A Governed Artifact whose Management Authority could not be resolved, so mutation is refused until someone classifies it.

**Observed Artifact**:
An Inventoried Artifact outside harness-smith's structural authority — reported, never checked as pass or fail, never mutated.

**Governed Harness**:
The Governed Artifacts that are harness-relevant: the runtime loads them, or a valid Consumer relation says an agent-facing consumer reads them. A document merely linked from the entry point is not one.
