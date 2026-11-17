# Sync Received Data Implementation Plan

1. Confirm API contract with frontend owner; preserve list/preview shapes and nullable expires_at.
2. Write service tests for isolation, immutable expiry, concurrent retries, redaction, pagination and unavailable/failed states. Observe missing implementation failure.
3. Implement private S3 body storage and Redis metadata/tombstones with best-effort capture.
4. Write API authorization/ownership tests; observe missing endpoints failure; add schemas and routes.
5. Connect SDK/XML worker boundaries, pull/backfill/linked response contexts, webhook user-resolved bodies and fetched responses, Garmin per-user fanout and binary FIT capture.
6. Update API navigation and source/retention/deployment documentation.
7. Run focused and full pytest, Ruff and ty; report exact coverage, limitations and any failures. No deploy or provisioning claims.
