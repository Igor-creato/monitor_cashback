# Monitor Cashback Constitution

## Core Principles

### I. Security First, Fail Closed

Security is the first constraint for every feature, bugfix, integration, and operational task. Public endpoints MUST have explicit authentication or a documented public contract, rate limiting, schema validation, safe error handling, and structured logging that never leaks PII, tokens, secrets, payment data, or cookies. Secrets MUST come only from environment, config, or secret storage. External failures MUST be handled explicitly with timeouts, retries/backoff where safe, terminal statuses, or DLQ behavior. When a safe result is uncertain, the system MUST fail closed.

### II. Idempotency and Ledger-First

Public requests, background workers, retries, queue consumers, CPA transaction flows, payout-related operations, and balance-affecting writes MUST have a verifiable idempotency key, dedup identity, unique constraint, or equivalent exactly-once/at-least-once safety mechanism. Money and balance behavior MUST be ledger-first: derived snapshots, cached summaries, and integration snapshots are not the source of truth. Cashback/rate snapshots may improve display or matching, but MUST NOT replace canonical partner, ledger, or transaction state.

### III. Test First and Verify After

Every implementation task MUST start with tests for that task before production code changes. The expected workflow is RED, implementation, GREEN, then refactor only while tests stay green. After implementation, run targeted checks for the touched behavior and broader checks proportional to risk. Any discovered error MUST be fixed and re-verified before the work is called complete. If application code is not changed, run the relevant governance/static validations instead and state why application tests were not required.

### IV. Local Computer → GitHub → Server

The source-of-truth workflow is local computer, then GitHub, then server pull/deploy according to project rules. Code, config, migrations, and docs are edited locally first, tested locally, committed, and pushed. The server MUST NOT be modified without an explicit user command. Without such a command, server access is limited to read-only diagnostics such as logs, status, readonly queries, and non-mutating checks. If a server-side change appears necessary, stop and ask for explicit permission.

### V. Prompt Scope and No Overreach

Implement exactly the requested task and the smallest supporting changes required to make it correct. Do not expand scope into adjacent features, broad refactors, product decisions, server changes, or speculative hardening unless the prompt asks for it or the current change would be unsafe without it. If a high-impact decision cannot be resolved from the repository, Obsidian, or existing project rules, ask before proceeding.

### VI. Documentation and Completion Discipline

Changes that affect architecture, API contracts, database schema, Redis/queue messages, integrations, deployment, or project workflow MUST be reflected briefly in the canonical Obsidian vault. Completion requires reporting changed files, verification commands, results, and anything not checked. After successful verification, commit and push the local changes unless the user explicitly asks not to.

## Project Constraints

Monitor Cashback is a Python/FastAPI microservice inside the wider Савелло Клуб cashback system. It MUST keep clear boundaries between API routes, service logic, repositories/database access, integration clients, and background workers. Incoming data MUST be validated through typed models or an existing validation layer. SQL MUST use ORM expressions or parameterized queries. Redis queue/message formats and WordPress/internal API contracts MUST be documented and versioned when changed.

The canonical knowledge vault is `F:\wamp64\www\kash-back\wp-content\plugins\cash-back\obsidian`. Do not create a local `obsidian/` copy in this repository. Use `rtk` as the command prefix for shell commands in this project.

All agent-facing communication for this project MUST be in Russian, including progress updates, questions, final answers, plans, and summaries. Keep code identifiers, file paths, shell commands, API names, and quoted external text in their original language when needed for correctness.

## Development Workflow

Before starting a task, read the relevant local code and Obsidian context. For behavior changes, create focused tests first and confirm the failing state when practical. Implement in small, scoped edits. Run targeted verification first, then broader tests/checks based on risk. Fix all failures introduced or exposed by the change before continuing. Update Obsidian when the change affects documented behavior or workflow. Commit with a focused message and push after verification.

## Governance

This constitution governs all Spec Kit specifications, plans, tasks, and implementation work in this repository. Feature specs and implementation plans MUST include a Constitution Check that explicitly addresses these principles. Tasks generated from specs MUST include test-first work and final verification/documentation/commit/push work.

Amendments require an explicit user request or approval. Versioning follows semantic versioning: MAJOR for principle removals or incompatible governance changes, MINOR for new principles or materially expanded requirements, and PATCH for clarifications or wording fixes. Compliance is reviewed during planning, before implementation, and before completion.

**Version**: 1.1.0 | **Ratified**: 2026-06-07 | **Last Amended**: 2026-06-07
