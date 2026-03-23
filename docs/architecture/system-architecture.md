# System Architecture for an AI-Native Operations Platform

## Table of contents
- [1. Scope and architectural principles](#1-scope-and-architectural-principles)
- [2. Architectural baseline](#2-architectural-baseline)
- [3. Top-level platform services](#3-top-level-platform-services)
- [4. Platform entity model](#4-platform-entity-model)
- [5. Processing lifecycle](#5-processing-lifecycle)
- [6. Platform terminology](#6-platform-terminology)
- [7. Design assumptions](#7-design-assumptions)
- [8. Product shape and operating model](#8-product-shape-and-operating-model)
- [9. Detailed system design](#9-detailed-system-design)
- [9.1 Data and storage](#91-data-and-storage)
- [9.2 Workflow and orchestration](#92-workflow-and-orchestration)
- [9.2.1 Exact Step Functions boundaries](#921-exact-step-functions-boundaries)
- [9.2.2 Queueing model](#922-queueing-model)
- [9.2.3 Retry model](#923-retry-model)
- [9.2.4 Reprocessing model](#924-reprocessing-model)
- [9.2.5 Batch model](#925-batch-model)
- [9.2.6 Human review reinsertion](#926-human-review-reinsertion)
- [9.2.7 Event backbone beyond Step Functions and SQS](#927-event-backbone-beyond-step-functions-and-sqs)
- [9.2.8 Canonical schema and versioning strategy](#928-canonical-schema-and-versioning-strategy)
- [9.2.9 Downstream action execution and write-back scope](#929-downstream-action-execution-and-write-back-scope)
- [9.2.10 Idempotency model](#9210-idempotency-model)
- [9.3 Service boundaries on EKS](#93-service-boundaries-on-eks)
- [9.4 Integration and delivery patterns](#94-integration-and-delivery-patterns)
- [9.5 Product and domain modeling](#95-product-and-domain-modeling)
- [9.6 Security, tenancy, and governance](#96-security-tenancy-and-governance)
- [9.7 LLM and model strategy](#97-llm-and-model-strategy)
- [9.7.1 Which stages are allowed to use LLMs versus deterministic logic only](#971-which-stages-are-allowed-to-use-llms-versus-deterministic-logic-only)
- [9.7.2 How the LLM Gateway chooses a provider by cost, latency, data sensitivity, capability, or tenant policy](#972-how-the-llm-gateway-chooses-a-provider-by-cost-latency-data-sensitivity-capability-or-tenant-policy)
- [9.7.3 Fallback policy between model providers](#973-fallback-policy-between-model-providers)
- [9.7.4 Prompt and schema versioning model](#974-prompt-and-schema-versioning-model)
- [9.7.5 Logging and redaction boundaries for model inputs and outputs](#975-logging-and-redaction-boundaries-for-model-inputs-and-outputs)
- [9.7.6 Evaluation and quality measurement for model-assisted stages](#976-evaluation-and-quality-measurement-for-model-assisted-stages)
- [9.7.7 Support for on-prem inference endpoints and provider-specific constraints](#977-support-for-on-prem-inference-endpoints-and-provider-specific-constraints)
- [9.8 Operations, observability, and cost](#98-operations-observability-and-cost)
- [9.8.1 Success metrics](#981-success-metrics)
- [9.8.2 Required traces and audit views across Source Artifact, Document, Case, Canonical Result, and Delivery Payload](#982-required-traces-and-audit-views-across-source-artifact-document-case-canonical-result-and-delivery-payload)
- [9.8.3 Alerting thresholds](#983-alerting-thresholds)
- [9.8.4 Backup, restore, and disaster recovery](#984-backup-restore-and-disaster-recovery)
- [9.8.5 Cost controls](#985-cost-controls)
- [9.8.6 Operational tooling for replay, cancel, force review, reopen case, and republish delivery](#986-operational-tooling-for-replay-cancel-force-review-reopen-case-and-republish-delivery)

## 1. Scope and architectural principles
-  The architecture is platform-oriented, not repo-oriented.
-  The system supports multiple pipeline types, not only invoice extraction.
-  The target workload shape includes heterogeneous inputs, multiple document families and formats, deterministic and non-deterministic stages, validation, fallback and recovery, review, artifacts, and extensibility.
-  The architecture supports ingestion of varied document sources, pluggable processing pipelines, orchestration, classification and routing, extraction and enrichment, validation and quality gates, review workflow, storage of source documents, outputs and runtime artifacts, observability, traceability, and future model-backed or rules-backed stages.
-  The architecture is not tied to a specific Python repository implementation.
-  The platform is a multi-tenant document operations platform that accepts different document-driven workflows, routes them through the right processing pipelines, stores artifacts and decisions, supports human-in-the-loop review, and provides operational controls, observability, and extensibility for new pipeline types.
-  The invoice pipeline is one example of a supported workload, not the definition of the whole system.
-  The architecture stays practical and skeptical rather than generic or hyped.

## 2. Architectural baseline
-  Cloud: AWS
-  Runtime platform: EKS for application services
-  Orchestration: AWS Step Functions
-  Data and storage architecture is defined further in later sections such as service boundaries, product modeling, tenancy, governance, and delivery patterns
-  Architectural split: EKS runs long-lived services and workers, Step Functions owns workflow state, fan-out, retries, branching, review escalation, and batch control
-  Kafka: not the primary orchestration backbone; at most optional later as an event backbone
-  LLM access: provider-agnostic through a unified internal API, supporting cloud-hosted and on-prem models as long as access is exposed through an API

## 3. Top-level platform services
-  Web Application
-  Submission API
-  Intake Service
-  Workflow Orchestrator
-  Processing Services
-  LLM Gateway
-  Review and Case Management
-  Integration and Delivery Services
-  Artifact Store
-  Metadata Store
-  Observability and Audit

## 4. Platform entity model
-  Source Artifact: raw immutable customer-submitted file. Examples: PDF, XLSX, email attachment, ZIP, EDI file.
-  Document: in-flight processing entity. Internal representation while the item moves through the system. May include partial extraction, OCR text, routing hints, confidence, temporary fields, enrichment state, intermediate validation results, and runtime metadata.
-  Case: business or operational entity created when an exception, mismatch, review, approval, or action-tracking workflow is needed.
-  Canonical Result: stable finalized normalized internal output with a governed shape.
-  Delivery Payload: the external response, export, webhook payload, or downstream integration payload derived from the Canonical Result.

## 5. Processing lifecycle
-  Customer submits a Source Artifact.
-  The system creates and processes a Document.
-  If needed, the system creates a Case.
-  When processing completes, the system produces a Canonical Result.
-  When something is sent out externally, it becomes a Delivery Payload.

## 6. Platform terminology
-  Use Intake or Submission for the customer-facing entry point.
-  Use Ingestion for the internal acceptance and registration of submitted content into the platform.
-  Use Normalization or Canonicalization for transforming processed content into an agreed internal schema.
-  Do not use ETL as the main term for this platform unless discussing a downstream warehouse or analytics loading flow.

## 7. Design assumptions
-  Which interaction modes become first-class product capabilities in v1 is GTM-dependent and not treated as a blocking architecture decision for this document.
-  ERP-specific integration examples such as SAP, Oracle, NetSuite, and Microsoft Dynamics are illustrative only at this stage. Exact mapping, priority, and connector depth are customer-dependent and should be validated against actual customer mix and rollout strategy.
-  Human review architecture is defined at the system-architecture level only. Deeper product-operating details such as staffing, queue operations, and detailed review procedures are intentionally out of scope for this document.

## 8. Product shape and operating model
-  The platform is closer to an operations automation and exception-management platform than a simple invoice parser.
-  Outputs include a web application or operations console, integrations and APIs, structured outputs and audit trail, and system actions inside customer tools.
-  The architecture therefore makes room not only for extraction, but also for case tracking, review, approvals, status visibility, and downstream actions.

## 9. Detailed system design

### 9.1 Data and storage
-  Amazon S3 is the system of record for raw Source Artifacts, Canonical Result snapshots, Delivery Payload snapshots, and Case attachments.

-  Amazon S3 uses a tenant-first, lifecycle-aligned prefix strategy rather than treating all stored objects as one undifferentiated bucket. The primary classification under each tenant is by blob class, including raw Source Artifacts, Canonical Result snapshots, Delivery Payload snapshots, and Case attachments. Working and audit-supporting prefixes may be used where needed as implementation guidance, but they are not locked as primary architectural storage classes.

-  Operational database is Amazon RDS for PostgreSQL with Multi-AZ deployment.
-  Services and workers running on EKS must not use unbounded direct database connection patterns against the shared operational database. The architecture should use a connection-management layer appropriate for bursty multi-worker workloads so that worker scaling, retry behavior, and tenant concurrency do not exhaust PostgreSQL connection limits or destabilize the operational store.

-  Cases live only in the operational RDS PostgreSQL database as first-class relational entities. They are not duplicated into S3, except that any file attachments associated with a Case may be stored in S3 with references kept in RDS.
-  The v1 baseline uses one operational PostgreSQL system of record, but the architecture should allow operational read scaling or read isolation to be introduced later if reviewer traffic, support queries, operational dashboards, or other read-heavy patterns begin to compete materially with workflow write load. This document does not lock a read-scaling topology in v1, but it does require the design to avoid assuming that one writer-only relational path will remain sufficient under all future workload shapes.
-  Search and operational filtering use RDS PostgreSQL in v1. If a dedicated search tier is needed later for full-text search, relevance ranking, fuzzy matching, advanced faceting, or larger-scale operator search, Amazon OpenSearch Service is the default candidate on AWS.

-  Analytics and reporting should not rely on heavy reads from the operational RDS PostgreSQL database. Structured reporting and event data should be exported to S3 and queried through Athena initially, with a dedicated warehouse considered later only if reporting scale and complexity justify it.
-  No dedicated cache layer is introduced in v1. RDS PostgreSQL, S3, SQS, and Step Functions cover the initial platform needs. Rate limiting, especially for externally exposed APIs, should be handled first at the API edge or ingress layer. A cache such as Redis should be added later only if a concrete need emerges for hot configuration reads, short-lived deduplication, rate-limiting state beyond edge controls, or other ephemeral high-frequency access patterns.
-  Retention follows a data lifecycle policy by artifact class. Operational metadata remains in RDS for as long as it must stay directly queryable for product and support workflows, while large artifacts and long-lived snapshots are retained in S3 according to their retention class. Exact retention periods are customer, business, and compliance-driven and are not specified in this document.
-  Canonical Results and Delivery Payloads are versioned explicitly. Each version must be traceable to the schema version and processing logic version that produced it, and model or prompt versions are tracked where model-assisted stages are used. Versioning is treated as an immutable history mechanism rather than in-place overwrite of prior outputs.

-  Raw blob deduplication is handled separately from request idempotency. The platform may create distinct Submission and Source Artifact records for separate intake events while still reusing the same underlying stored blob when the uploaded bytes are identical within the same tenant.
-  Raw blob deduplication uses exact-byte matching only. The platform computes a strong content hash over the raw bytes of an uploaded artifact and reuses an existing stored blob only when the bytes match exactly.
-  Blob deduplication scope is per tenant. Identical blobs may be reused within the same tenant, but identical bytes across different tenants are stored separately.
-  Physical blob deletion is reference-aware and retention-aware. A stored blob may be deleted only when no active references remain and the applicable retention policy permits deletion.
-  Operational records in RDS PostgreSQL use a relational core for primary entities, relationships, status, and queryable state, with JSONB used selectively for flexible substructures rather than as the primary modeling strategy.
-  A Document remains a persistent operational record in RDS PostgreSQL for metadata, state, lineage, and direct product queries, while large immutable artifacts and long-lived snapshots associated with that Document are retained in S3 according to their artifact class.
### 9.2 Workflow and orchestration
#### 9.2.1 Exact Step Functions boundaries
Step Functions uses a hybrid workflow boundary.
A parent workflow is created per submission, and optionally per explicit batch import job when the intake pattern is batch-oriented. The parent workflow owns intake registration, expansion of Source Artifacts into internal Documents, fan-out, aggregate progress tracking, and batch or submission completion.
A child workflow is created per Document. The Document workflow is the primary processing unit and owns stage sequencing, branching, retries, fallback paths, review escalation, case-triggering logic, canonicalization, and delivery preparation.
This means submission and batch are coordination scopes, while Document is the execution scope.
This boundary is preferred over a single workflow for the entire submission or batch because one Source Artifact may expand into multiple Documents, and those Documents may complete, fail, enter review, or be reprocessed independently.
A parent workflow should not hold detailed per-stage business state for every Document beyond what is needed for orchestration and aggregate status. Fine-grained processing state belongs to the per-Document workflow and the operational data model in RDS PostgreSQL.
Where reprocessing is needed, the system should be able to launch a new Document workflow for a specific Document without requiring full replay of the original submission or batch, unless the replay is explicitly requested at that higher scope.
The Step Functions workflow payload should carry identifiers, orchestration context, and other control-plane state needed for execution control, but it should not become the primary container for large mutable processing data. Large intermediate artifacts, detailed extraction state, OCR text, and other heavy runtime data should remain in the operational data model or object storage, with workflows referencing them through stable identifiers.
The workflow design must remain aware of the execution limits, payload boundaries, duration profile, and cost shape of the selected Step Functions execution mode. Workflow boundaries should therefore be chosen so that long-running, high-fan-out, or review-interrupted paths do not depend on oversized payload transfer or on execution behavior that is misaligned with the operational duration and observability needs of the platform.

#### 9.2.2 Queueing model
The queueing model uses a mixed pattern rather than direct invocation everywhere or SQS everywhere.
Step Functions invokes lightweight orchestration and control-plane actions directly. This includes intake validation, metadata registration, routing decisions, child workflow creation, aggregate status updates, case-triggering decisions, and other short-lived state transitions that do not require worker buffering.
SQS is used in front of asynchronous worker-style processing stages. This includes stages such as preprocessing, OCR, extraction, enrichment, model-assisted processing, rate-limited connector work, bulk delivery work, and other tasks that may be bursty, compute-heavy, slow, or operationally variable.
In this model, Step Functions remains the owner of workflow state and sequencing, SQS provides buffering and backpressure, and EKS worker services consume queued work and perform the actual processing.
SQS should not be introduced for every internal step by default. It is used where decoupling from worker capacity, smoothing intake bursts, isolating downstream slowness, or enabling independent worker scaling materially improves resilience and operability.
Direct Step Functions invocation is preferred for short control actions. SQS-backed execution is preferred for worker tasks whose runtime, throughput, or dependency behavior is variable enough that tight synchronous orchestration would be fragile or inefficient.
Because the platform is shared and multi-tenant, queue-backed execution must include protection against noisy-neighbor behavior. Admission, routing, worker concurrency, queue topology, priority handling, or other control mechanisms should be designed so that one tenant, one connector source, or one unusually large intake pattern cannot consume disproportionate queue capacity indefinitely at the expense of other tenants or normal platform work. This document does not lock one universal fairness mechanism, but it does require tenant-fair operational behavior.

#### 9.2.3 Retry model
The retry model is layered by execution type rather than using one uniform retry policy for all failures.
Step Functions handles retries for short-lived direct orchestration and control-plane actions. These retries should be bounded, use backoff, and be applied only to transient failures where repeating the control action is low-cost and operationally safe.
SQS-backed worker stages rely primarily on queue-based retry behavior and bounded worker re-execution rather than repeated orchestration-level retries. This applies to asynchronous processing stages such as preprocessing, OCR, extraction, enrichment, model-assisted stages, rate-limited connector work, and other variable-duration worker tasks.
Worker implementations may perform only limited local retries for brief transient dependency failures. Long or unbounded retry loops inside workers are not preferred, because they hide failure, consume capacity, and make execution behavior harder to reason about.
Permanent or policy-based failures should not be retried repeatedly. They should move to an explicit terminal or exception path such as failed, dead-lettered, in\_review, or case-created, depending on the stage and business impact.
Provider failover is treated separately from generic retry. Where an external model or service is interchangeable by policy, the platform may attempt bounded retry on the original provider and then switch to an approved alternate provider before escalating.
Replay and reprocessing are treated as explicit new-entry operations rather than ordinary retries. A retry is a bounded attempt to recover within the current execution. Reprocessing or replay starts a new execution path after correction, review, configuration change, or logic upgrade.
#### 9.2.4 Reprocessing model
Reprocessing is scope-aware and is not treated as the same mechanism as ordinary retry.
The default reprocessing scope is the Document. When a failure, correction, parser upgrade, model change, validation override, or delivery regeneration affects only one Document, the system starts a new Document workflow execution for that Document rather than replaying the full original submission.
Submission-level replay is allowed only when the issue is genuinely submission-scoped, such as incorrect intake metadata, incorrect Source Artifact expansion into Documents, or another submission-level routing or decomposition error.
Batch-level replay is supported as an explicit operational action for batch-oriented intake patterns, but it is not the default recovery path for ordinary document failures.
Reprocessing always creates a new execution path and must remain traceable to the original submission, Source Artifact, and Document. It should record the reason for reprocessing, the actor or system that triggered it, and the logic, schema, and model versions used for the new run where applicable.
Reprocessing does not overwrite immutable historical outputs. If reprocessing produces a new Canonical Result or Delivery Payload, that output is stored as a new explicit version, with lineage to the prior version preserved for audit and operational traceability.
#### 9.2.5 Batch model
Batch is an optional first-class operational grouping scope, not the default top-level entity for every intake.
Submission remains the normal intake scope for customer-facing uploads and API submissions. Batch is introduced only when work is intentionally grouped under a higher-level operational run, such as scheduled connector imports, bulk backfills, replay jobs, large synchronized pulls, or other explicitly batch-oriented intake patterns.
A Batch represents one operational job with its own identity, scope, status, progress tracking, and completion semantics. A Batch may contain one or more Submissions, one or more Documents, or another explicitly defined unit set, depending on the intake pattern, but the Document remains the primary processing unit.
Large customer submissions do not automatically require a separate Batch entity. For example, one uploaded ZIP that expands into many Documents may still be modeled as a single Submission with multiple Documents unless there is a real operational need for a higher-level batch grouping.
Batch progress and completion are tracked explicitly in RDS PostgreSQL. A Batch should record aggregate counts, terminal outcomes, timestamps, and orchestration references in the same way that Submission tracks its own aggregate lifecycle.
A Batch is considered complete only when all scoped work has reached terminal state. The preferred terminal states at batch scope are completed, completed\_with\_exceptions, failed, and cancelled.
Batch replay is supported as an explicit operational action, but it is not the default recovery path for ordinary Document-level failures.
Batch-versus-Submission classification is decided at intake admission time, before heavy processing begins. The decision is owned by the Intake Service and is based on explicit intake contract, tenant policy, and deterministic preflight thresholds such as file count, total size, archive characteristics, estimated expansion count, source channel, and operational guardrails.
The standard Submission path must have explicit size and scope limits. Requests above that scope may either be promoted to a batch-oriented intake path when policy allows or rejected and redirected to a dedicated bulk import mechanism. Batch classification should not emerge late during processing, because that would make lifecycle semantics, auditability, and operational control inconsistent.
#### 9.2.6 Human review reinsertion
Human review reinsertion uses controlled checkpoint-based continuation by default, with full Document reprocessing used only when the review outcome invalidates earlier processing stages.
When a Document requires human review, the platform creates or updates a Case in RDS PostgreSQL and records the reason for review, the triggering stage, the data presented for review, and the structured review outcome.
A review decision maps to a defined reinsertion action rather than an unstructured manual handoff. The preferred model is to continue from an approved post-review checkpoint such as post-review correction, post-correction validation, pre-canonicalization, or pre-delivery, depending on the type of review and the stage that raised the exception.
Full Document reprocessing is used only when the review decision changes upstream assumptions strongly enough that prior outputs can no longer be trusted, such as rerouting to a different pipeline, correcting a foundational parsing error, or invalidating earlier extraction results.
Human review does not imply replay of the full original submission by default. The normal unit of reinsertion remains the Document, and the review outcome must remain traceable to the Case record, the Document, and the execution path that resumes or reprocesses it.
#### 9.2.7 Event backbone beyond Step Functions and SQS
The platform may use a separate event backbone for decoupled non-orchestration events, but it is not the primary workflow-control mechanism. In v1, AWS EventBridge is the default candidate for this role on AWS.

Step Functions remains the owner of workflow state, sequencing, branching, retries, and execution control. SQS remains the buffering and backpressure mechanism for asynchronous worker stages. EventBridge, where used, is for publish-subscribe style distribution of domain and operational events that need to fan out to multiple consumers without becoming part of the core workflow-control path.

Examples may include downstream audit export triggers, analytics-oriented event export, loosely coupled operational notifications, integration-trigger fan-out, or future side consumers that react to platform events. EventBridge is not required for every internal state transition, and the architecture should prefer simpler direct orchestration or direct service interaction where fan-out and decoupling are not needed.

Kafka is not the default event backbone for v1. It may be considered later only if event volume, replay requirements, consumer topology, or streaming use cases exceed what the Step Functions, SQS, and EventBridge combination can reasonably support.

#### 9.2.8 Canonical schema and versioning strategy
Canonical schema uses a governed schema-family model rather than one universal flat schema for all platform workflows.

Each Canonical Result must conform to a shared platform envelope plus a schema-specific canonical payload. The shared envelope carries stable cross-platform fields such as identity, lineage, producing Document reference, execution lineage, schema family, schema version, processing-logic version, and other governed provenance metadata. The canonical payload then carries the normalized business structure appropriate to the relevant workflow, document family, or domain object.

This means the platform has one canonicalization approach and one governance model, but not one single payload schema forced across every workload. Different document families or workflow types may therefore produce different canonical payload schemas, as long as they remain explicitly versioned and governed under the platform’s canonical schema framework.

Schema evolution must be explicit and versioned. A Canonical Result version must remain traceable to the exact schema family and schema version that defined its structure at the time it was produced. Changes that materially alter canonical structure are treated as schema-version changes rather than silent in-place mutation.

This model keeps canonical outputs stable and governable without pretending that all platform workflows naturally fit one universal business object shape. Delivery Payloads remain derived external contracts and may evolve separately from the internal canonical schema family they are produced from.

#### 9.2.9 Downstream action execution and write-back scope
Downstream action execution and write-back are first-class supported platform capabilities in v1, using a configurable-autonomy model rather than a universal manual-only or auto-execute-default model.

The platform may execute approved downstream actions in connected systems where the workflow, connector capability, tenant policy, confidence policy, and product configuration explicitly allow it. Such actions may include structured write-back, status updates, exception-resolution actions, approval outcomes, reconciliation updates, record creation or update, and coordinated multi-system operational actions in external systems.

Downstream action execution is not assumed for every workflow, connector, or customer. Some flows may remain read-only, notification-only, retrieval-only, export-oriented, or human-confirmed, while others may permit controlled write-back or operational action execution. The exact action set remains product-, connector-, and customer-dependent.

Any downstream action that can materially affect an external system must remain policy-governed, explicitly attributable, and auditable. Where required by workflow or tenant policy, such actions must be gated by approval, override authority, confidence thresholds, or other explicit permission boundaries rather than treated as unconditional side effects of document processing.

This model aligns with the platform’s intended product shape: the platform can move from observation and analysis toward controlled operational automation, while preserving human oversight and configurable autonomy boundaries.

#### 9.2.10 Idempotency model
Idempotency is enforced as a layered model by scope rather than through one global deduplication key.

Submission intake must be idempotent within a defined request scope. The platform should use a tenant-scoped intake identity such as a client-supplied idempotency key, external event identifier, source message identifier, or another deterministic intake key so that retried submissions do not create duplicate Submission records.

Task and worker execution must be idempotent within the scope of a specific execution path. Repeated delivery of the same queued task, repeated orchestration of the same step, or worker restart during the same processing attempt must not create duplicate stage side effects. Idempotency at this layer should be keyed by Document, stage, and execution or attempt identity so that legitimate later reprocessing is not blocked.

Case creation must be idempotent for the same active unresolved exception condition. At minimum, that condition should be evaluated against the Document, the triggering stage or checkpoint, the exception or review type, and the still-open status of the prior Case. Repeated triggering of the same still-active issue should update, link, or reuse the existing active Case rather than create duplicate Cases for the same unresolved condition, while a later distinct exception path or a newly reopened issue may create a new Case where operationally justified.

Delivery and downstream write-back actions must be idempotent before any external side effect is committed. Delivery should use explicit payload or attempt identity, and downstream idempotency keys where supported, so that retries do not accidentally publish the same Delivery Payload multiple times.

Idempotency must prevent accidental duplication, but it must not block explicit replay, reprocessing, republish actions, or the creation of new immutable Canonical Result and Delivery Payload versions. Those actions are new intentional execution paths and must carry distinct execution lineage.

### 9.3 Service boundaries on EKS
The Web Application is hosted as a static frontend by default rather than being served from EKS. EKS remains the runtime for backend application services and APIs. The frontend communicates with backend services through the platform’s API layer. A dedicated backend-for-frontend or server-rendered web tier may be introduced later only if product requirements justify it.

The Submission API runs on EKS for control-plane responsibilities such as intake validation, tenant policy enforcement, metadata registration, submission admission, and workflow initiation. Large artifact transfer is not routed through EKS by default. Customer-uploaded blobs should be written directly to S3 through a direct-upload pattern such as presigned upload, with the Submission API responsible for registering and admitting the uploaded artifacts into the platform.
Externally exposed APIs should sit behind a managed ingress or edge layer responsible for request routing, TLS termination, and baseline request-protection controls. The exact edge product is not specified here, but the architecture assumes a distinct ingress boundary between public traffic and backend services rather than exposing internal application workloads directly.
Artifact admission must include basic file-safety and content-validation controls before deeper processing begins. This includes verification of allowed file types and container formats, rejection or quarantine of malformed or disallowed content, and security screening appropriate to customer-submitted files before those artifacts are expanded, parsed, or routed into downstream worker stages.

Review and Case Management is part of the main platform backend in v1 rather than a separately deployed service. The main backend owns Case lifecycle, reviewer actions, approvals, overrides, reinsertion triggers, related operational queries, and audit-linked review records.
Processing Services use a coarse-grained worker model on EKS rather than one monolithic worker service or a separate microservice for every logical stage. Worker boundaries are defined primarily by runtime profile, dependency profile, and operational isolation needs.
The LLM Gateway is the mandatory control point for provider access, credential isolation, routing, and policy enforcement. Platform services and workers request model-assisted execution through the gateway rather than calling providers directly. Shared internal libraries may still be used for request shaping, response normalization, and client-side integration convenience, but they must not bypass gateway-controlled provider access or duplicate policy-enforcement logic outside the gateway boundary.
This document does not specify which exact product features, stages, or workflows use model-assisted processing. Those remain product and policy decisions outside the scope of this architectural decision.

The default worker grouping is:
-  Preprocessing Workers for file type detection, archive unpacking, multi-document split, workbook or tab handling, format conversion, OCR preparation, and basic file integrity checks.
-  Core Document Processing Workers for family or class routing, vendor or layout detection, field extraction, table or line-item extraction, canonicalization, schema and business validation, and confidence or scoring logic.
-  Enrichment and Connector Workers for ERP and reference-data lookups, reconciliation against external records, vendor, PO, or shipment context fetches, rate-limited connector or API work, and downstream system enrichment.
-  Model-Assisted or Fallback Workers for LLM-assisted extraction or classification, alternate recovery paths, ambiguity resolution, provider-routed model calls, and bounded provider failover.

### 9.4 Integration and delivery patterns
The default customer delivery pattern is notify-by-webhook and retrieve-by-API. REST APIs are the primary interface for submission, status retrieval, result retrieval, and operational control. Webhooks are the default push mechanism for significant state changes, but they are notification-oriented by default and do not carry full result payloads unless a specific customer integration profile explicitly requires inline delivery.

Default webhook payloads are thin event notifications. They include event identity, affected resource identifiers, status, timestamps, and enough metadata for the customer to correlate and fetch the relevant Delivery Payload or related resource through the API. Full result delivery through webhook is not the default behavior.

The pull interaction model is API-based and primarily asynchronous. Customers and connected systems submit work, retrieve status, and fetch outputs through platform APIs rather than relying on long-lived synchronous processing responses. This document does not specify exact endpoint design, polling behavior, or resource navigation patterns.
The architecture supports outbound notifications and outbound system actions. Webhooks are the default generic push mechanism for lifecycle, exception, and delivery signaling. Direct connector-based write-back or action execution into external systems is also supported where the integration contract and product flow require it. This document does not specify the exact event catalog or exact external action set.
The architecture supports scheduled integration patterns such as periodic imports, exports, polling, reconciliation jobs, and other time-based operational runs. These are treated as explicit operational patterns rather than ad hoc exceptions. This document does not specify the exact scheduled job catalog, cadence, or customer-facing configuration model.
The architecture supports event-driven triggers from connected systems where integration contracts require them. External business or system events may initiate intake, enrichment, reprocessing, delivery, or other defined workflow entry points. This document does not specify the exact external event sources, schemas, or trigger catalog.
The external delivery contract is the Delivery Payload, not the Canonical Result. Canonical Result remains the governed internal normalized output used for platform processing, validation, lineage, and versioned internal state. Delivery Payload is the customer-facing response, export, webhook-referenced resource, or downstream integration payload derived from it.
This keeps the internal canonical model separate from customer-facing integration contracts and allows external delivery formats to evolve independently of the internal normalized representation.
Webhook events identify the primary domain object for the event type rather than forcing one universal resource model. Document lifecycle events reference the affected Document, Case lifecycle events reference the affected Case, Delivery events reference the relevant Delivery Payload, and Batch lifecycle events reference the Batch where batch-scoped signaling is needed. Webhook payloads may include related identifiers such as Batch, Submission, Document, Case, Canonical Result, or Delivery Payload IDs as needed for correlation, but the primary event object must match the actual business meaning of the event.

The v1 public integration style is REST APIs plus webhooks. REST APIs are the primary interface for submission, status retrieval, result retrieval, and operational control, while webhooks provide outbound event notification. Other interface styles may be added later if justified, but they are not part of the v1 architectural baseline.

Connectors are plugin-style integration modules selected according to product and GTM priorities rather than assuming universal connector coverage in v1. A connector may support inbound, outbound, or bidirectional interaction patterns depending on the target system and integration contract. Connector capabilities may include data retrieval, enrichment, write-back, and action execution, with the exact capability set governed by product requirements, tenant policy, approval rules, and auditability needs.

### 9.5 Product and domain modeling
Source Artifact and Document use a one-to-many primary lineage model. A Source Artifact may expand into zero, one, or many Documents depending on decomposition rules such as archive unpacking, attachment expansion, workbook or tab handling, or multi-document split. Each Document must retain a reference to exactly one primary originating Source Artifact for lineage, auditability, and reprocessing. The Source Artifact remains the immutable raw input, while each resulting Document becomes an independent operational processing unit with its own workflow state, status, outputs, and execution history.

This does not prevent future support for additional secondary artifact relationships where a Document may also reference supporting artifacts, but the primary v1 model is one Source Artifact to many Documents, with one primary origin per Document.
In v1, Case uses a strict one-Document-per-Case model. A Document may create zero, one, or many Cases over time, but each Case must reference exactly one Document and cannot span multiple Documents.

This keeps review, approval, exception handling, reinsertion, auditability, and operational reasoning aligned with the Document as the primary execution unit. Each Case represents an exception, review, approval, or action-tracking workflow for one Document only.

A future version of the platform may introduce grouped multi-Document Cases if shared-case handling becomes operationally valuable, but that is explicitly out of scope for the v1 domain model.
Canonical Result granularity is Document-scoped in v1. Each Document produces its own Canonical Result as the stable normalized internal output for that Document, and Canonical Result versioning, lineage, and reprocessing remain anchored to the Document as the primary execution unit.

A Canonical Result may contain one normalized business object or a structured collection of normalized business objects when that is the natural outcome of processing one Document. This does not change the ownership model: the Canonical Result still belongs to one Document, not directly to a delivery target, case resolution, or downstream integration endpoint.

Delivery Payloads are derived from the Canonical Result for external consumption, and Cases may influence whether a Canonical Result is approved, corrected, or regenerated, but they do not redefine the primary granularity of the Canonical Result itself.
Case lifecycle uses a moderate operational state model in v1 rather than a minimal or ticket-system-style workflow model. The preferred Case states are open, in\_review, awaiting\_approval, awaiting\_action, resolved, failed, and closed.

These states describe the operational handling lifecycle of the Case rather than the detailed technical processing state of the related Document. A Case begins in open, may move into active handling through in\_review, may pause in a waiting state such as awaiting\_approval or awaiting\_action, and eventually reaches a terminal outcome of resolved or failed. Closed is the final administrative state used when the Case no longer requires active operational visibility or further work.

Decision outcomes such as approved, rejected, overridden, or corrected should be recorded as structured Case data or review outcomes rather than modeled as primary lifecycle states. This keeps the Case state model stable while still allowing richer review and approval semantics.
In v1, the platform is primarily Document-centric in its domain model and primary API model, with Case-centric operational views used for exception handling where needed. Document is the primary unit of processing, status visibility, lineage, result inspection, and reprocessing, so it is also the primary first-class domain object of the platform model.

Case remains a first-class object for review, approval, exception handling, and action tracking, but it is not the default center of gravity of the platform model because not every Document creates a Case. Submission and Batch are coordination and grouping scopes, while workflow execution constructs remain operational implementation details rather than the main customer-facing resource model.

The exact UI and UX expression of this model, including navigation emphasis, landing views, operator queues, and workflow presentation, is product- and GTM-dependent and is not specified in this document. This document defines the platform’s primary object model, not the final product surface design.
The platform treats connected ERP, EDI, email, file systems, and other line-of-business systems as authoritative external operational systems, while the platform acts as the orchestration, automation, and exception-resolution layer across those systems, source artifacts, model-assisted processing, human review flows, and downstream actions. This aligns with the intended product positioning as a system that plugs into existing tools and deploys intelligent agents to reconcile, audit, and resolve exceptions in real time, rather than as a replacement system of record.

To support this role, the platform may ingest and persist a bounded operational read model of external business context when that materially improves processing reliability, latency, validation, review usability, auditability, or reprocessing stability. This may include external identifiers, reference mappings, and related business context that are repeatedly needed for normal operation. Additional context may still be fetched live from connected systems when needed.

The platform does not attempt to replace the ERP or other connected systems as the source of truth for their native business objects. Instead, it coordinates work across fragmented systems, document-derived outputs, model-assisted stages, reviewer actions, and external delivery or write-back actions, while keeping the authoritative business record in the underlying systems.

Pre-ingested external business context that is part of the platform’s bounded operational read model lives primarily in the operational RDS PostgreSQL database in v1 when it must be queryable for processing, validation, review, and case-handling workflows. Large raw responses, bulk extracts, or connector-side snapshots may still be stored in S3 where appropriate, but RDS remains the primary operational store for the structured external context that the platform actively reasons over.

External-context refresh uses a mixed synchronization model in v1 rather than one universal mechanism. The platform may use scheduled synchronization, event-driven updates, connector pull, or explicit on-demand fetch depending on the source system, integration contract, data volatility, operational importance, product offering, customer requirements, and cost tradeoff. Refresh depth and frequency are not only technical choices, but also product and commercial choices, since more frequent synchronization may increase connector cost, infrastructure load, and operational overhead. This document does not specify one universal sync pattern across all connectors, but it does require provenance, fetch timing, and source references to be recorded for materialized context that materially affects processing or operational decisions.

The platform distinguishes between hot operational context and extended reference context. Hot operational context is the subset of external data that is repeatedly needed for core processing, matching, validation, review, exception handling, or write-back preparation and is therefore a candidate for structured materialization in the platform’s bounded operational read model. Extended reference context is useful for drill-down, investigation, or less common workflows, but is not required for most normal execution paths and may be fetched live, cached selectively, or materialized later only where product workflows justify it.

Integration access patterns may be live-first or materialized-first depending on the source and workflow. Materialized-first is preferred where repeated access, low-latency decisions, reviewer usability, resilience to upstream slowness, or stable reprocessing make local context operationally valuable. Live-first is preferred where the data is highly volatile, rarely needed, expensive to mirror broadly, restricted by integration limits, or required mainly for occasional drill-down. The exact pattern remains product-, connector-, and customer-dependent and is not fully specified in this document.

### 9.6 Security, tenancy, and governance
The v1 platform uses a shared multi-tenant architecture with strong logical tenant isolation as the default baseline, rather than separate full runtime stacks per tenant. Shared platform services may serve multiple tenants, but tenant boundaries must be enforced explicitly across identity, authorization, workflow context, operational data, storage paths, connector credentials, and audit records.

In the operational data model, all tenant-owned records must remain tenant-scoped by design, with tenant context treated as a first-class access-control and query boundary rather than an optional filter. In object storage, tenant-first pathing remains mandatory. In integration handling, connector credentials, secrets, and external access tokens must be isolated per tenant or per tenant-approved integration scope.

The architecture must also support stronger segregation for selected tenants where required by customer contract, compliance posture, data sensitivity, or commercial tier. That stronger segregation may be applied selectively at the data, secret, storage, queue, or environment level without changing the core platform model. Full per-tenant isolated stacks are therefore supported as an exception path, not the default v1 operating model.
The v1 identity model distinguishes explicitly between customer user identities, internal platform user identities, and non-human service identities, rather than treating all actors through one flat access model. Customer users operate only within their tenant scope. Internal users are granted limited platform-support or operational access according to explicit role and support policy. Service identities are used for platform services, workers, workflows, and connector execution, and must be managed separately from human user identities.

Authorization in v1 uses a role-based model with explicit tenant scoping as the primary access boundary. Customer-facing roles may include operational roles such as tenant admin, operator, reviewer, or approver, but exact product role names are not locked here. Internal roles may include support or platform-operations access where justified, but such access must remain explicitly governed and auditable.

Approval authority is treated as a distinct permission boundary, not as an automatic property of ordinary user access. Actions such as approval, override, reinsertion, republish, or downstream write-back must require explicit role or permission grant according to tenant policy and workflow design. Sensitive operational actions performed by internal users or service identities must remain attributable through audit records.

In implementation terms, tenant authorization and workflow permissions are enforced primarily in the application and operational data model, while AWS IAM and Kubernetes service identities are used for workload-level least-privilege access to infrastructure, secrets, queues, storage, and external integrations.

The authorization model may evolve toward more attribute- and policy-driven controls for sensitive actions, high-segregation tenants, or regulated workflows, but v1 uses actor-class separation with tenant-scoped RBAC as the baseline.

This document does not specify the external identity provider choice, exact SSO model, or full permission matrix for v1. It does lock the actor separation model, tenant-scoped authorization baseline, least-privilege treatment of service identities, and explicit treatment of approval and override authority as governed permissions.
Tenant-specific behavior must be governed through explicit runtime configuration rather than scattered service-local assumptions or code-only branching. This includes tenant policy, workflow enablement, model-routing constraints, approval requirements, connector capability flags, delivery behavior, quota or guardrail settings, and other materially behavior-shaping controls. The exact configuration implementation is not specified here, but the architecture requires a governed configuration model with clear ownership, auditability, and runtime applicability.

Within shared EKS environments, Kubernetes NetworkPolicy is used as a defense-in-depth control to restrict east-west pod communication between workload classes, sensitive namespaces, and supporting platform components. NetworkPolicy is intended to reduce unnecessary service reachability, limit lateral movement, and improve workload segmentation inside the shared runtime environment.

NetworkPolicy is not treated as the primary tenant-isolation mechanism of the platform. Tenant isolation remains enforced primarily through identity, authorization, tenant-scoped operational data, tenant-scoped storage boundaries, secrets isolation, connector credential isolation, and audit controls.

In practice, NetworkPolicy should be used to constrain communication paths such as worker-to-worker traffic, connector access to internal services, access to review or administrative backends, and model-worker access to approved gateway or egress paths. Exact policy definitions are implementation-specific and are not fully specified in this document, but the architectural role of NetworkPolicy as an infra-level containment control is defined here.

AWS Secrets Manager is the primary secret-management system for the v1 platform. Long-lived and sensitive secrets such as connector credentials, OAuth client secrets, refresh tokens, webhook signing secrets, provider API keys, and database or service credentials must be stored and governed there rather than treated as ordinary application configuration.

Workloads running on EKS access secrets through least-privilege AWS identities, using workload-level IAM roles and service-account-based identity rather than broad shared credentials. Secret access must be scoped to the minimum set of secrets required by each service or worker role. Kubernetes Secrets are not the source of truth for customer-sensitive or long-lived platform credentials, though they may still be used selectively as runtime delivery mechanisms where implementation needs justify it.

Connector credentials and integration secrets must be isolated per tenant or per tenant-approved integration scope, not shared across tenants. The secret model must support credential rotation, revocation, provenance, and auditability. Where customer contract, sensitivity, or compliance requirements justify it, stronger segregation such as dedicated secret namespaces, dedicated keys, or more isolated tenant environments may be applied without changing the platform’s default shared multi-tenant baseline.

This document does not specify the exact secret naming convention, retrieval library, or rotation workflow implementation. It does lock AWS Secrets Manager as the canonical secret store, IAM-based workload access as the baseline access pattern, and tenant-scoped isolation of connector and customer-sensitive credentials.
Connector execution must account for credential lifecycle behavior during runtime, not only at rest. Where integrations use expiring access tokens or delegated credentials, the architecture must support refresh, reauthorization, revocation handling, and explicit failure paths when a connector can no longer act under the required tenant-approved scope. Long-running or delayed workflow steps must not assume that credentials captured earlier in the workflow remain valid at execution time.

The platform maintains a first-class structured audit trail for material human and system actions, rather than relying only on ordinary application logs. Audit history must be tied to the platform’s primary operational entities and workflows, including Submission, Batch where applicable, Source Artifact handling events, Document processing events, Case lifecycle events, Canonical Result version events, Delivery Payload publication events, and downstream write-back or action execution attempts.

Audit records must capture the acting principal or system identity, the action taken, the affected entity, the timestamp, and sufficient execution context to reconstruct what happened and why. Where relevant, this includes workflow or execution identifiers, prior and resulting state, triggering reason, policy path, review outcome, approval basis, connector target, and linked artifact or payload references. Internal user actions, customer user actions, and non-human service actions must all remain attributable.

Model-assisted stages are subject to audit as material system behavior. The platform must record enough metadata to explain which model-assisted path was used, which provider or model policy was selected, what versioned logic or prompt family applied, and how the resulting decision or output relates to the surrounding workflow. This document does not require universal storage of all raw prompts or full model inputs and outputs in every case, but it does require traceability of material model-driven decisions and outputs.

Audit history is append-oriented and must not be treated as an ordinary mutable business record. Operational state may change, but the history of material actions, decisions, approvals, overrides, deliveries, and execution attempts must remain preserved for support, investigation, customer accountability, and governance. Exact retention periods, storage tiering, and immutability hardening mechanisms are not fully specified in this document.
Because audit history is append-oriented and operationally sensitive, the implementation should apply technical hardening that reduces the risk of ordinary in-place mutation or silent deletion of historical records. This document does not lock one exact immutability mechanism, but it does require that audit preservation rely on more than application convention alone where material governance, support, or customer-accountability records are concerned.

Structured audit history remains directly queryable in dedicated audit tables in the operational RDS PostgreSQL database while it is operationally hot. Older audit history may be exported from RDS into a dedicated S3 audit-archive bucket rather than being mixed into general artifact storage.

The audit-archive bucket must be governed with explicit retention and lifecycle policies appropriate to audit data. Those policies must support long-term preservation, controlled deletion or expiration where permitted, lower-cost storage tiering for older records, and clear separation from ordinary application artifacts and snapshots.

This document does not specify exact retention durations, archive cadence, or exact S3 storage-class transitions for audit history. It does lock the principle that archived audit data is stored in a separately governed bucket with explicit lifecycle and retention controls, rather than being left in undifferentiated general-purpose storage.

Model-access routing is governed by customer policy, compliance requirements, contractual constraints, hosting restrictions, and workflow context rather than being based only on generic cost or latency optimization. The platform must support different execution routes for model-assisted stages, including cloud-allowed routing, routing limited to approved providers or model families, on-prem or customer-controlled inference only, and workflow paths where model use is disallowed entirely.

The set of supported model providers and model families is determined at the product-platform level, but the allowed subset for a given tenant or workflow is constrained by customer governance and platform policy. Those constraints may reflect customer AI policy, compliance requirements, residency or hosting restrictions, approved vendor lists, workflow-specific controls, or other contractual rules. Data sensitivity may be one input into that policy model, but it is not the only one.

The LLM Gateway is the enforcement point for this routing policy. Platform services and workers request model-assisted execution through the gateway, while the gateway applies the allowed provider set, execution location rules, and fallback boundaries for the relevant tenant and workflow context. Disallowed providers or hosting environments must not be used simply because they are cheaper, faster, or operationally convenient.

This document does not specify the exact customer policy taxonomy, exact provider allowlists, or exact configuration surface for policy administration. It does lock the principle that model routing is governed by explicit customer and platform policy, and that the architecture must support approved-provider-only, on-prem-only, and no-LLM paths where required.
The default environment model for v1 is one shared dev environment, one shared staging environment, and a shared multi-tenant prod environment. Shared multi-tenant production is the default and common operating model for customer tenants, with logical tenant isolation enforced through the platform’s identity, authorization, data, storage, secret, and audit controls.

Single-tenant or otherwise more isolated customer environments are supported as an option where justified by customer requirements such as governance, compliance, residency, hosting constraints, integration risk, or commercial tier, but they are not the default baseline of the platform.

This document does not specify the exact promotion process, the exact internal deployment topology inside each environment, or the exact approval criteria for when a customer receives a more isolated environment. It does lock that the platform is multi-tenant by default, with one shared dev, one shared staging, and shared multi-tenant prod as the normal model, while stronger tenant-specific deployment isolation remains an exception path.

### 9.7 LLM and model strategy
#### 9.7.1 Which stages are allowed to use LLMs versus deterministic logic only
LLM usage is bounded by stage type rather than treated as universally allowed across the platform.

Deterministic logic remains mandatory for orchestration, workflow state transitions, policy enforcement, admission control, authorization, approval and override checks, idempotency handling, and other control-plane decisions that must remain predictable, auditable, and policy-safe.

Model-assisted processing is allowed only in bounded processing stages where probabilistic behavior is operationally acceptable and can be governed, validated, and traced. These stages may include document classification or routing assist, extraction fallback, ambiguity resolution, normalization assist, reviewer-facing summarization or explanation, and other defined enrichment tasks.
Model-assisted stages must also use bounded input-shaping rules appropriate to the stage. This includes stage-specific limits on input size, context assembly, chunking, truncation where policy allows it, and other controls needed to keep model execution operationally safe, cost-bounded, and semantically reliable. Inputs that exceed the allowed bounds for a stage must follow an explicit alternate path such as chunked processing, deterministic fallback, or review escalation rather than silent overflow or implicit truncation.

LLM-assisted outputs must not become authoritative purely by generation. They must either pass downstream deterministic validation, remain subject to explicit business rules, or be routed to human review where confidence, policy, or workflow rules require it.
Model-assisted stages that are expected to produce structured outputs must treat schema-invalid or structurally malformed responses as explicit execution failures or exception outcomes rather than as successful stage completion. The architecture therefore requires a bounded handling path for parsing failure, contract mismatch, or other structurally invalid model output, such as retry within policy, alternate approved routing, deterministic fallback, or review escalation.

The architecture therefore uses a deterministic-core, model-assisted-edge pattern: control and governance stay deterministic, while model use is allowed in selected execution stages where it materially improves coverage or recovery without weakening auditability and policy enforcement.

#### 9.7.2 How the LLM Gateway chooses a provider by cost, latency, data sensitivity, capability, or tenant policy
Provider selection in the LLM Gateway follows a policy-first and quality-gated routing model rather than a generic cheapest-or-fastest-wins strategy.

The gateway must first evaluate whether model-assisted execution is allowed for the relevant tenant, workflow, stage, and data-handling context. This policy layer determines the permitted hosting modes, provider set, model families, and any workflow-specific restrictions such as approved-provider-only, on-prem-only, or no-LLM execution.

Within the allowed set, the gateway then selects from models that are qualified for the specific stage based on evaluation and benchmarking against platform-relevant tasks. Different model-assisted stages may require different quality thresholds and different capabilities such as structured extraction, classification, ambiguity resolution, long-context handling, or reviewer-facing explanation. A provider or model is eligible for routing only if it is both policy-allowed and quality-approved for the stage being executed.

Only after policy and quality qualification does the gateway optimize among the remaining eligible options using operational criteria such as service health, availability, latency, concurrency pressure, and cost.

Cost and latency are therefore optimization inputs inside an approved candidate set, not the top-level routing rule. This keeps model routing aligned with customer governance, measured task quality, and workflow safety rather than treating model choice as a generic infrastructure optimization problem.

#### 9.7.3 Fallback policy between model providers
Provider fallback is bounded and policy-governed rather than automatic across any available model endpoint.

For each model-assisted stage, the platform may define a preferred provider or model and a limited set of approved fallback candidates. A fallback candidate is eligible only if it is allowed by tenant and workflow policy, satisfies the same hosting and data-handling constraints, and is quality-qualified for that stage according to the platform’s evaluation standards.

Fallback is used only after bounded retry on the preferred provider or model where retry is appropriate. It is treated as a controlled failover mechanism, not as part of generic unbounded retry behavior.

If no approved fallback candidate exists for the stage and context, the platform must not silently degrade to an arbitrary provider or lower-governance route. The execution must instead follow the defined exception path, such as terminal failure, review escalation, or another policy-approved recovery path.

Fallback breadth may vary by stage. Lower-risk stages may allow broader approved fallback sets, while higher-risk stages such as outputs that materially affect validation, approval, or downstream write-back must use stricter fallback boundaries.

#### 9.7.4 Prompt and schema versioning model
Prompted model behavior is treated as versioned processing logic, not as informal runtime text.

Each model-assisted stage must have explicit versioning for the stage logic that governs it, including the prompt or prompt family used for that stage and the structured output contract or schema expected from that stage where applicable. These versions are tracked independently enough to preserve operational traceability, even if they are deployed together through the same software release process.

Execution lineage for a model-assisted stage must record the relevant model-routing identity and the versioned logic used to produce the result. This includes, where applicable, the stage logic version, prompt version, output-schema or contract version, and the provider or model identity selected through the gateway.

Changes to prompts or output schemas must therefore be observable as real logic changes for audit, evaluation, rollback analysis, and reprocessing decisions. A new Canonical Result or Delivery Payload version produced after such a change must remain traceable to the exact versioned model-assisted logic that generated it.

This document does not specify the exact packaging mechanism for prompts, the exact version-numbering convention, or whether some prompt assets are shared across stages. It does lock that prompt and output-contract changes are governed as first-class versioned logic for model-assisted stages.

#### 9.7.5 Logging and redaction boundaries for model inputs and outputs
Logging for model-assisted stages uses a metadata-first and least-exposure approach rather than full raw prompt and response capture by default.

The platform must always record structured execution metadata sufficient for auditability, support, and evaluation. This includes the acting workflow or stage, tenant and policy context, selected provider or model route, stage logic version, prompt version, output-contract version where applicable, timestamps, success or failure outcome, validation result, fallback or escalation path, and links to the affected operational entities.

Raw model inputs, prompt bodies, retrieved context, and full model outputs must not be logged or persisted by default in general-purpose application logs. Where operationally necessary, bounded capture of raw or partially redacted content may be allowed only through explicit policy-controlled paths such as approved debugging, evaluation workflows, incident investigation, or tenant-approved support modes.

When raw or near-raw model content is persisted, minimization and redaction rules must be applied according to tenant policy, workflow sensitivity, and governance requirements. This document does not specify one universal redaction technique, but it does lock the principle that content exposure must be intentionally limited and governed rather than treated as ordinary debug data.

This model preserves auditability and operational traceability for model-assisted execution without turning prompts, context payloads, or model outputs into an uncontrolled secondary data store.

#### 9.7.6 Evaluation and quality measurement for model-assisted stages
Evaluation for model-assisted processing is stage-specific and operationally grounded rather than based on one generic model benchmark.

Each model-assisted stage must have its own evaluation criteria, quality thresholds, and approval path based on the actual task it performs. Different stages may require different measures such as extraction accuracy, structured-output validity, routing accuracy, review deflection, correction rate, escalation rate, downstream validation pass rate, or other workflow-relevant quality signals.

Model and provider qualification must use platform-relevant evaluation data and benchmark scenarios rather than relying only on vendor claims or broad public benchmarks. Qualification may combine offline benchmark sets, curated regression cases, shadow or comparison testing, and production-oriented quality signals where appropriate.

Operational measurement does not stop at model output quality in isolation. The platform should judge model-assisted stages by their effect on end-to-end workflow outcomes such as review rate, recovery rate, exception rate, reprocessing rate, delivery safety, and total cost per successfully handled Document or Case where relevant.

This document does not specify the exact evaluation tooling, dataset storage pattern, or human-labeling workflow. It does lock that model-assisted stages are approved, monitored, and changed using explicit stage-level quality measurement tied to real platform outcomes.

#### 9.7.7 Support for on-prem inference endpoints and provider-specific constraints
On-prem inference endpoints and provider-specific execution constraints are treated as first-class supported routing conditions within the LLM Gateway, not as edge-case exceptions outside the main architecture.

The platform’s internal model-access contract remains provider-agnostic at the service boundary, but the gateway must preserve and enforce material differences between execution targets. These differences may include hosting location, customer-controlled versus vendor-hosted inference, approved region or residency boundaries, authentication model, throughput and concurrency limits, latency profile, context-window limits, structured-output support, tool-calling support, and other provider- or deployment-specific capabilities and restrictions.

On-prem or customer-controlled inference endpoints are therefore supported as real execution targets when exposed through an approved API contract. They must be routable under the same policy-governed framework as cloud-hosted providers, including tenant-specific allow rules, workflow restrictions, fallback boundaries, auditability, and stage-level quality qualification.

The provider-agnostic gateway abstraction must not assume that all providers are operationally interchangeable. Routing, fallback, evaluation approval, and workflow eligibility must account for provider-specific and deployment-specific constraints explicitly rather than hiding them behind a lowest-common-denominator abstraction.

This document does not specify the exact adapter pattern for each provider, the exact endpoint protocol set, or the exact configuration surface for provider metadata. It does lock that on-prem inference and provider-specific constraints are first-class concerns of gateway policy and routing.

### 9.8 Operations, observability, and cost
#### 9.8.1 Success metrics
Success metrics are defined as a balanced operational scorecard across flow, quality, recovery, provider health, and cost, rather than by throughput or latency alone.

At the system-architecture level, the platform must support measurement of:
-  Flow and timeliness, including throughput, queue delay, and end-to-end completion latency.
-  Outcome quality, including completion rate, review rate, exception rate, and downstream validation pass rate.
-  Recovery effectiveness, including fallback rate, recovery rate, and reprocessing rate where applicable.
-  Model and provider health for model-assisted stages, including provider error rate, fallback usage, and validation failure or escalation rates tied to those stages.
-  Cost efficiency, including cost per successfully completed Document and, where operationally relevant, cost per resolved Case.

Infrastructure metrics alone are not sufficient as platform success metrics. The architecture must support measurement of end-to-end workflow outcomes, because this is an operational automation and exception-resolution platform rather than a pure document-processing engine.

This document does not specify the exact dashboard design, exact SLO targets, or exact tenant-facing KPI set. It does lock that success measurement must cover performance, quality, exception handling, model-stage behavior, and cost together.

#### 9.8.2 Required traces and audit views across Source Artifact, Document, Case, Canonical Result, and Delivery Payload
The platform must provide end-to-end operational traceability across the primary entity chain and the execution chain, not only isolated technical logs or per-service traces.

At minimum, the architecture must support trace views and linked auditability across:
-  Source Artifact handling, including intake identity, storage reference, decomposition or expansion events, and lineage into resulting Documents.
-  Document execution, including workflow identity, stage progression, retries, fallback paths, review escalation, reprocessing history, and terminal outcome.
-  Case history where applicable, including exception trigger, review actions, approvals, overrides, reinsertion decisions, and resolution outcome.
-  Canonical Result versions, including version identity, schema version, logic version, model-assisted stage lineage where applicable, and linkage to the Document execution that produced each version.
-  Delivery Payload versions and delivery attempts, including payload identity, publication or write-back attempts, downstream target, idempotency context, and final delivery outcome.

The required trace model must support both entity lineage and execution lineage. Entity lineage answers how Source Artifacts, Documents, Cases, Canonical Results, and Delivery Payloads relate to one another. Execution lineage answers which workflow runs, retries, fallbacks, reviews, approvals, model-routing choices, and reprocessing paths produced the observed result.

Ordinary infrastructure telemetry remains necessary, but it is not sufficient on its own. Because the platform is operationally centered on document handling, exception resolution, review, and governed delivery, traceability must be aligned to business entities and execution paths rather than only to pods, queues, and service calls.

This document does not specify the exact UI for these trace views or the exact observability vendor stack. It does lock end-to-end traceability across the platform’s primary entities and execution history as a first-class operational requirement.
In addition to entity lineage and execution lineage, the platform should support distributed technical tracing across service, queue, workflow, and dependency boundaries so that cross-service latency, failure propagation, and dependency hot spots can be investigated at runtime. This technical tracing complements, but does not replace, the entity-centered operational trace model defined in this section.

#### 9.8.3 Alerting thresholds
Alerting is defined as a layered operational model across infrastructure, workflow execution, review backlog, external dependency health, and delivery behavior, rather than as infrastructure monitoring alone.

At the system-architecture level, the platform must support alerting for at least the following classes of operational risk:
-  Queue and worker pressure, including excessive queue depth, excessive queue age, dead-letter growth, and worker-capacity mismatch for SQS-backed stages.
-  Workflow execution health, including abnormal Step Functions failure rates, repeated retry patterns, stuck or long-running executions beyond policy, and unexpected shifts in terminal outcome mix.
-  Case and review backlog health, including stuck open Cases, approval or review backlog growth, and breach of defined operational handling windows where such windows are configured.
-  External provider and dependency degradation, including elevated provider error rates, abnormal latency, fallback surges, exhaustion of approved routing options, and other signs that a model provider or integration dependency is no longer operating within acceptable bounds.
-  Delivery and downstream action health, including repeated webhook delivery failures, write-back failures, downstream throttling, or integration outage patterns.

This document does not specify exact numeric thresholds, paging rules, or on-call policy. Those depend on actual workload, customer commitments, and production baselines. It does lock that alerting must cover business-operational failure modes of the platform, not only underlying infrastructure symptoms.

This is required because a document-automation and exception-resolution platform may appear technically healthy at the cluster level while still failing operationally through stuck workflows, silent backlog growth, degraded provider behavior, or blocked review and delivery paths.
#### 9.8.4 Backup, restore, and disaster recovery
High availability is not sufficient on its own as the platform resilience model. The architecture must also support backup, restore, and disaster-recovery readiness appropriate to the operational role of the system, including recoverability of the operational database, retained artifacts, and material audit history. This document does not specify exact RPO, RTO, cross-region topology, or restore procedure design, but it does require recoverability to be treated as an explicit platform concern rather than an assumed property of Multi-AZ deployment alone.

#### 9.8.5 Cost controls
Cost control is a first-class operational control layer of the platform, enforced through admission, routing, concurrency, and backpressure mechanisms rather than handled only as post hoc spend reporting.

At the system-architecture level, the architecture must support cost-governing controls such as:
-  Tenant-scoped quotas and guardrails, including limits or policy controls on submission volume, batch volume, model-assisted usage, connector-intensive workflows, or other materially cost-driving behaviors where needed.
-  Concurrency and execution caps, including limits on worker parallelism, stage-specific concurrency, provider call concurrency, and other execution paths that can amplify spend or destabilize shared capacity.
-  Model-routing controls, where cost may be used only to optimize among policy-approved and quality-qualified models for a given stage. Cost must not justify routing to a model that does not meet the required quality bar for that stage. High-cost model use, fallback breadth, or escalation to model-assisted stages may also be restricted by tenant, workflow, or stage policy.
-  Batch backpressure controls, including delayed admission, staged release, throttled expansion, pause, or rejection of large batch-oriented work when required to protect shared capacity, operational stability, or cost boundaries.

These controls are required because the platform operates as a shared multi-tenant system with potentially bursty intake, variable processing cost, external dependency constraints, and model-assisted stages whose spend profile can differ significantly across workflows.

This document does not specify exact quota values, pricing policy, or customer packaging. It does lock that the platform must be able to prevent one tenant, one batch, or one expensive execution path from consuming disproportionate cost or capacity without explicit policy approval.

#### 9.8.6 Operational tooling for replay, cancel, force review, reopen case, and republish delivery
The platform must anticipate operational actions such as reprocess or replay, cancel, force review, reopen Case, and republish Delivery Payload, but the exact operator tooling and action surface are not specified in this document.

These actions are recognized as important operational capabilities for recovery, exception handling, and controlled intervention, but their exact UX, API shape, and operator workflow remain open for later product and implementation design.

Where such actions are supported, they must respect the platform’s existing control model, including authorization boundaries, auditability, lineage preservation, and immutable version history where applicable. They must not rely on silent state mutation that breaks traceability.

This document defines the need for operational intervention capabilities in principle, without specifying the exact administrative tooling model, internal support workflow, or full action catalog.
