# PostgreSQL Sync Captures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Serve newly captured received sync data with existing PostgreSQL and Redis, without S3 configuration.

**Architecture:** Replace the capture body's private S3 dependency with a PostgreSQL repository and small storage adapter. Keep existing Redis metadata, atomic admission, ownership leases, fencing, user/run scoping, redaction, immutable publisher timestamp, preview limits and public response contracts. Insert bodies using a unique object key and ON CONFLICT DO NOTHING. Commit each capture in a separate database transaction so capture failures cannot roll back ingestion. Redis finalization remains fenced; a crash after database commit is recovered by an idempotent insert on retry.

**Tech Stack:** SQLAlchemy 2, PostgreSQL, Alembic, Celery, pytest.

**Spec:** Approved conversation: use PostgreSQL for capture storage, preserve viewer and user/run isolation, bound payload sizes, deny reads at 72 hours, and schedule expired-body deletion. No new infrastructure or S3 configuration. Existing raw debug storage stays unchanged.

## Global Constraints

- Do not commit or deploy without user request.
- Preserve 10 MiB per-artifact and 1,000-artifact per-run limits.
- Preserve 72-hour read expiry; deletion is asynchronous.
- Keep Redis metadata and separate user/run authorization unchanged.
- Use an independent database session per storage operation.
- Do not return captured payloads in logs or list responses.
- Keep raw debug storage configuration independent.

## Review Focus

- Concurrent duplicate writes must not overwrite existing body or extend expiry.
- Crash between body commit and Redis finalization must recover with current lease/fencing behavior.
- Expired objects must not be readable before physical cleanup runs.
- Database failure must not fail ingestion; previews must return existing unavailable response.
- Cleanup must be bounded, retry-safe, and safe with concurrent cleanup workers.

### Task 1: PostgreSQL immutable capture bodies

**Files:** Create `backend/app/models/received_capture.py`, `backend/app/repositories/received_capture_repository.py`, `backend/app/services/received_capture_storage.py`, a migration under `backend/migrations/versions/`, and repository regression tests. Modify `backend/app/models/__init__.py` and `backend/app/services/received_data_service.py`.

**Interfaces:** Adapter preserves internal `put_object(**kwargs)` and `get_object(**kwargs)` contracts used by capture service. Repository exposes immutable insert, expiry-checked read, and bounded cleanup. `_storage()` returns PostgreSQL adapter regardless of raw debug backend.

- [x] Write tests for immutable insert, concurrent duplicate writes, expiry, cleanup and capture failure isolation.
- [x] Run focused tests and establish failing baseline.
- [x] Implement table with key primary key, byte body, and indexed timezone-aware expiry. Add migration after current head.
- [x] Implement repository-owned independent transactions and adapter. Switch capture service to adapter without changing Redis admission/fencing.
- [x] Run focused tests and lint/type checks.

### Task 2: Scheduled cleanup and deployment documentation

**Files:** Create `backend/app/integrations/celery/tasks/received_capture_cleanup_task.py`. Modify task exports, Beat schedule, and `docs/api-reference/guides/sync-status-stream.mdx`.

**Interfaces:** Hourly cleanup task calls bounded repository cleanup. Locked-row batches use SKIP LOCKED so overlapping tasks do not contend for the same rows. Transaction rollback on worker crash leaves rows eligible for retry.

- [x] Test cleanup registration and bounded deletion of expired bodies without deleting live objects.
- [x] Register cleanup task and hourly schedule with bounded batch count.
- [x] Document required migration and process deployment, PostgreSQL bodies plus Redis metadata, independent raw debug settings, expiry and asynchronous deletion.
- [ ] Obtain independent review because captured health data and migration are sensitive.
- [x] Verification: 78 focused tests passed (capture storage, capture service, sync API, Garmin webhook, raw debug storage, SDK upload); focused ty checks and changed-file Ruff checks passed; migration upgrade/downgrade passed on PostgreSQL 18; Alembic has one head; git diff --check passed. Full backend suite and deployed verification were not run.
