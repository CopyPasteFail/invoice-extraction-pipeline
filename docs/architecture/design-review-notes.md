# Design Review Notes

## Purpose

This document summarizes how the system architecture was reviewed and refined.

Its purpose is to show that the architecture document reflects iterative review, targeted challenge, and deliberate acceptance of specific changes rather than a one-pass draft.

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
**Weak or underspecified areas were challenged, and the architecture document was updated only where the change improved realism or clarity without over-specifying implementation details.**

## Main review themes

### Workflow and orchestration

Review focused on workflow boundaries, payload discipline, retry scope, replay behavior, and human review reinsertion. The reviewed architecture now makes a clearer distinction between orchestration state and operational data, and clarifies where new execution paths are expected.

### Multi-tenant safety

Review focused on tenant isolation across storage, data access, queue-backed execution, connector credentials, and runtime behavior. The reviewed architecture now states tenant-fair operational expectations more explicitly and strengthens the treatment of tenant-governed runtime configuration.

### Storage and operational data

Review focused on whether the storage model was realistic for a production system, including relational versus object storage boundaries, read load expectations, artifact retention, and blob deduplication behavior. The reviewed architecture remains conservative and operationally grounded.

### LLM governance and execution boundaries

Review focused on whether model-assisted stages were bounded correctly, whether provider access was controlled properly, and whether malformed outputs, fallback, and policy routing were handled credibly. The reviewed architecture tightens the LLM Gateway boundary and makes model-stage guardrails more explicit.

### Auditability, observability, and recoverability

Review focused on whether the platform could be operated, debugged, and defended in production. The reviewed architecture now more clearly covers distributed tracing, audit-history hardening, and a baseline backup and disaster-recovery posture.

## Material changes accepted into the architecture

The following changes were accepted and integrated into the architecture document during review:

- clarified that Step Functions payloads should carry identifiers and orchestration context rather than large mutable processing state, so workflows stay lighter and easier to reason about
- added workflow-type awareness so workflow boundaries can match the execution limits, expected duration, and cost profile of each workload shape
- added connection-management expectations for shared PostgreSQL access from bursty EKS worker fleets, so database usage remains realistic under parallel worker spikes
- v1 baseline stays simple and does not add operational read-scaling mechanisms up front, while still keeping the architecture flexible enough to support higher operational read demand later without a major redesign
- added explicit tenant-fairness expectations for queue-backed execution, meaning the shared queueing and worker model should prevent one tenant’s workload from dominating system capacity and slowing down processing for other tenants
- tightened the LLM Gateway so provider access is controlled through one mandatory boundary, which makes policy enforcement and credential isolation more consistent
- clarified that AI-powered stages should receive carefully controlled inputs, rather than overly large, loosely defined, or open-ended data
- added explicit handling for schema-invalid or structurally malformed model outputs, so the architecture accounts for failure paths instead of assuming clean responses
- clarified Case idempotency for the same active unresolved exception condition, so the platform does not keep creating duplicate Cases for the same unresolved problem
- added artifact admission safety controls before deeper processing, so unsafe or malformed files can be rejected or quarantined early
- clarified that connector credentials need to be managed over time, including cases where access must be refreshed, revoked, or used after a delay, so integrations remain reliable and controllable
- clarified that public APIs should sit behind a dedicated entry layer, so incoming traffic is routed and protected before it reaches backend services
- clarified that tenant-specific runtime behavior can be configured, but only within platform-controlled rules and limits
- clarified that audit history should be better protected from accidental changes or improper modification
- clarified that operators should be able to trace requests and workflow activity across multiple services, not just follow individual business entities
- clarified that recovery planning should cover backup, restore, and disaster recovery, not just keeping services available during normal failures

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

The architecture document should be read as a reviewed and curated system design. It was iterated through critical feedback, but only selected changes were accepted. The resulting document reflects deliberate scope control: it is more specific where production realism required it, and still intentionally open where further product or implementation decisions are better made later.
