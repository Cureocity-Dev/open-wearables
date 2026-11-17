# Sync Received Data Design

Approved scope: backend capture for all sync sources, user/run-scoped lazy inspection, 72-hour access retention. Frontend is owned separately. Never reconstruct old input from current rows.

Redis stores bounded metadata; existing private S3 configuration stores immutable content-addressed bodies under sync-received/. API lists metadata and proxies bounded previews with existing developer/admin authentication. Missing configuration is explicitly unavailable. JSON snapshots are normalized and secret/URL-redacted; XML/FIT original bytes have metadata-only previews.

Concurrency: immutable publisher task headers fix original age across retries; bounded SET NX run-expiry markers prevent extensions while metadata exists and old task age rejects late captures after eviction. Atomic Lua reserves capped artifact slots and 60-second recoverable ownership leases. Compare-owner metadata publication fences stale writers. Conditional immutable S3 writes recover crash-after-upload without overwrite. Deterministic user/run/content keys isolate users and deduplicate retries. A writer crash leaves retryable failed metadata; capture failure never fails ingestion. Provider response context is fenced to user and reset in finally blocks. Garmin fanout captures only resolved-user records.

No provisioning, commits, push, or deploy. Private bucket IAM/encryption, lifecycle physical deletion, shared API/worker configuration and durable non-evicting Redis are deployment prerequisites. Read expiry and S3 lifecycle deletion are separate mechanisms. See the sync status guide for limits and exact coverage.
