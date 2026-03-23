# Design Review Notes

## Purpose

This document summarizes how the system architecture was reviewed and refined.

Its purpose is to show that the final architecture reflects iterative review, targeted challenge, and deliberate acceptance of specific changes rather than a one-pass draft.

The canonical architecture remains in `system-architecture.md`.

## Review approach

The architecture was reviewed as a production-oriented backend and platform design, with emphasis on:

- architecture correctness
- workflow and orchestration realism
- multi-tenant isolation and safety
- storage and data model realism
- idempotency, replay, and auditability
- LLM integration boundaries and governance
- observability, recoverability, and operational control

**Review was intentionally critical.**
**Weak or underspecified areas were challenged, and the final architecture document was updated only where the change improved realism or clarity without over-specifying implementation details.**

## Main review themes

### Workflow and orchestration

Review focused on workflow boundaries, payload discipline, retry scope, replay behavior, and human review reinsertion. The final architecture tightened the distinction between orchestration state and operational data, and clarified where new execution paths are expected.

### Multi-tenant safety

Review focused on tenant isolation across storage, data access, queue-backed execution, connector credentials, and runtime behavior. The final architecture now states tenant-fair operational expectations more explicitly and strengthens the treatment of tenant-governed runtime configuration.

### Storage and operational data

Review focused on whether the storage model was realistic for a production system, including relational versus object storage boundaries, read load expectations, artifact retention, and blob deduplication behavior. The final architecture remained conservative and operationally grounded.

### LLM governance and execution boundaries

Review focused on whether model-assisted stages were bounded correctly, whether provider access was controlled properly, and whether malformed outputs, fallback, and policy routing were handled credibly. The final architecture tightened the LLM Gateway boundary and made model-stage guardrails more explicit.

### Auditability, observability, and recoverability

Review focused on whether the platform could be operated, debugged, and defended in production. The final architecture now more clearly covers distributed tracing, audit-history hardening, and a baseline backup and disaster-recovery posture.

## Material changes accepted into the architecture

The following changes were accepted and integrated into the architecture document during review:

- clarified that Step Functions payloads should carry identifiers and orchestration context, not large mutable processing state
- added workflow-type awareness so workflow boundaries stay aligned with execution limits, duration, and cost shape
- added connection-management expectations for shared PostgreSQL access from bursty EKS worker fleets
- clarified that future operational read scaling may be introduced without changing the v1 baseline
- added explicit tenant-fairness expectations for queue-backed execution
- tightened the LLM Gateway so provider access is controlled through one mandatory boundary
- added bounded input-shaping expectations for model-assisted stages
- added explicit handling for schema-invalid or structurally malformed model outputs
- clarified Case idempotency for the same active unresolved exception condition
- removed duplicated idempotency wording from the event-backbone section
- added artifact admission safety controls before deeper processing
- added connector credential lifecycle handling for refresh, revocation, and delayed execution
- added an ingress or edge baseline for externally exposed APIs
- added a governed tenant runtime-configuration expectation
- added technical hardening expectations for append-oriented audit history
- added distributed tracing as a complement to entity-centered traceability
- added backup, restore, and disaster-recovery expectations beyond simple high availability

## Areas left intentionally open

Some areas were intentionally left at principle level rather than locked into one exact implementation. This was deliberate.

The architecture does not fully specify:

- the exact Step Functions execution-mode pattern for every workflow shape
- the exact queue topology or fairness mechanism
- the exact read-scaling topology for PostgreSQL
- the exact immutability mechanism for audit-history hardening
- the exact configuration implementation for tenant runtime controls
- the exact operator tooling surface for replay, cancel, force review, reopen case, and republish delivery

These areas remain open because the architecture is meant to define a credible platform direction and key constraints without pretending to resolve every lower-level implementation choice up front.

## Final note

The final architecture should be read as a reviewed and curated system design. It was iterated through critical feedback, but only selected changes were accepted. The resulting document reflects deliberate scope control: it is more specific where production realism required it, and still intentionally open where further product or implementation decisions are better made later.
