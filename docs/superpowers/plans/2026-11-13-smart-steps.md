# Smart Steps Implementation Plan

**Goal:** Add opt-in interval-aware step merging to the existing activity summary API and dashboard without SDK changes.

**Architecture:** Preserve SDK sample end times in nullable storage. At read time, calculate steps independently of the legacy daily metric winner. Prefer ranked sources only during overlaps; prorate partial intervals uniformly and disclose estimation. Legacy samples without duration are treated as timestamp observations and marked partial/estimated. No persistent computed totals or background writes, so retries/crashes cannot publish stale aggregates.

**Approved scope:** Existing GET activity summaries gains `step_aggregation=priority|smart_merge` (default priority), step-specific metadata, unchanged other metrics; dashboard defaults to smart merge and offers legacy selection. SDK and downstream microservice repositories remain untouched.

## Constraints
- No claim of exact Apple Health parity.
- Preserve raw per-device samples and default API compatibility.
- Read-only calculation; deterministic source-ID tie breaking and input-order independence.
- Missing metric is not zero coverage. Unknown-duration history must disclose limitation.
- Existing archive lacks intervals; do not silently discard archived steps.

## Tasks
1. Preserve nullable sample `end_at` through SDK import, ORM/schema, bulk upsert, migration and archive boundary inspection. Test importer and storage roundtrip.
2. Build pure deterministic step merger and repository input query. Test phone 356 + watch 30, overlap, partial overlap, zero, missing duration, midnight, negative/invalid intervals, ties and reversed input order.
3. Extend existing API/service with validated mode and optional step metadata. Preserve legacy output; replace only steps in smart mode, including step-only days. Test API legacy/smart/invalid mode and no-step Watch interference.
4. Add dashboard selector and API types; send mode in both current/comparison requests and query cache identity. Display mixed-source/quality metadata for steps.
5. Document request/response and limitations. Run backend focused/full tests, lint/type checks and frontend checks/build. Independent diff review, fix findings, then commit/push and create PR.

## Verification
Use project pytest with PostgreSQL/Redis testcontainers, Ruff, frontend lint/type build and available frontend tests. Report any existing failures separately. Do not push until relevant tests pass. Review migration upgrade/downgrade and generated OpenAPI parameter. Compare deterministic merger output across input permutations; no cache/materialized state means no cross-worker fencing requirement.
