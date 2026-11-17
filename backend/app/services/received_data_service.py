"""Best-effort immutable, user/run-scoped ingestion snapshots.

Redis holds metadata only; private S3 holds bodies. Absolute expiry is allocated
once with SET NX so retries and concurrent writers cannot extend retention.
"""

import hashlib
import json
import logging
from contextlib import suppress
from contextvars import ContextVar, Token
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from celery import current_task, signals
from fastapi import HTTPException

from app.integrations.redis_client import get_redis_client
from app.services import raw_payload_storage
from app.utils.structured_logging import json_serial

logger = logging.getLogger(__name__)
RETENTION_SECONDS = 72 * 60 * 60
METADATA_SECONDS = 7 * 24 * 60 * 60
MAX_BYTES = 10 * 1024 * 1024
MAX_ARTIFACTS = 1000
MAX_TEXT = 16000
_context: ContextVar[tuple[str, tuple[str, ...]] | None] = ContextVar("received_data_context", default=None)
_pending: ContextVar[list[tuple[str, Any, str]] | None] = ContextVar("received_pending", default=None)
_pending_incomplete: ContextVar[set[str] | None] = ContextVar("received_pending_incomplete", default=None)
_SECRET_KEYS = frozenset(
    {
        "authorization",
        "access_token",
        "refresh_token",
        "token",
        "client_secret",
        "password",
        "callbackurl",
        "signed_url",
        "api_key",
        "accesskey",
        "useraccesstoken",
        "accesstoken",
        "refreshtoken",
        "apikey",
        "clientsecret",
        "secret",
        "cookie",
        "headers",
    }
)


LEASE_SECONDS = 60


@signals.before_task_publish.connect
def stamp_capture_origin(headers: dict[str, Any] | None = None, **kwargs: Any) -> None:
    """Celery retry preserves custom headers, unlike worker-local timestamps."""
    if headers is not None:
        headers.setdefault("received_capture_created_at", datetime.now(UTC).isoformat())


def _origin(now: datetime) -> datetime | None:
    if current_task and current_task.request.id:
        raw = (current_task.request.headers or {}).get("received_capture_created_at")
        # Legacy queued tasks without an immutable publisher timestamp fail closed.
        return datetime.fromisoformat(raw) if raw else None
    return now


def _now() -> datetime:
    return datetime.now(UTC)


def _storage() -> tuple[Any, str | None]:
    if raw_payload_storage._storage_backend != "s3":
        return None, None
    return raw_payload_storage._s3_client, raw_payload_storage._s3_bucket


def _index_key(user_id: str, run_id: str) -> str:
    scope = hashlib.sha256(f"{user_id}:{run_id}".encode()).hexdigest()
    return f"sync:received:{scope}"


def begin(user_id: str, run_id: str, *authorized_run_ids: str) -> Token:
    return _context.set((str(user_id), (run_id, *authorized_run_ids)))


def end(token: Token) -> None:
    _context.reset(token)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]"
            if str(key).lower().replace("-", "_") in _SECRET_KEYS
            or any(word in str(key).lower() for word in ("token", "password", "secret", "authorization"))
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    # Provider URLs may contain credentials or signed query strings.
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return "[redacted URL]"
    return value


def begin_pending() -> tuple[Token, Token]:
    return _pending.set([]), _pending_incomplete.set(set())


def end_pending(token: tuple[Token, Token]) -> None:
    _pending.reset(token[0])
    _pending_incomplete.reset(token[1])


def flush_pending(user_id: str, run_id: str) -> None:
    for owner, payload, kind in _pending.get() or []:
        if owner == str(user_id):
            capture(user_id=owner, run_id=run_id, payload=payload, kind=kind)
    if str(user_id) in (_pending_incomplete.get() or set()):
        try:
            get_redis_client().set(_index_key(str(user_id), run_id) + ":partial", "1", ex=METADATA_SECONDS)
        except Exception:
            logger.warning("Received-data incomplete marker failed", exc_info=True)


def capture_response(user_id: str, payload: Any, *, kind: str = "api_response") -> None:
    context = _context.get()
    if context is not None and str(user_id) == context[0]:
        for run_id in context[1]:
            capture(user_id=context[0], run_id=run_id, payload=payload, kind=kind)
    elif _pending.get() is not None:
        pending = _pending.get()
        incomplete = _pending_incomplete.get()
        if pending is not None and len(pending) >= 20:
            if incomplete is not None:
                incomplete.add(str(user_id))
            return
        if pending is not None:
            # Serialize immediately: providers sometimes mutate response objects.
            try:
                encoded = payload if isinstance(payload, bytes) else json.dumps(payload, default=json_serial).encode()
                buffered_bytes = sum(
                    len(p) if isinstance(p, bytes) else len(json.dumps(p).encode()) for _, p, _ in pending
                )
                if len(encoded) <= MAX_BYTES and buffered_bytes + len(encoded) <= MAX_BYTES:
                    snapshot = encoded if isinstance(payload, bytes) else json.loads(encoded)
                    pending.append((str(user_id), snapshot, kind))
                elif incomplete is not None:
                    incomplete.add(str(user_id))
            except Exception:
                if incomplete is not None:
                    incomplete.add(str(user_id))
                logger.warning("Received-data response buffer failed", exc_info=True)


def capture(
    *,
    user_id: str,
    run_id: str,
    payload: Any,
    kind: str,
    label: str | None = None,
    created_at: datetime | None = None,
) -> None:
    """Atomic admission and recoverable fenced upload; never fail ingestion."""
    try:
        client = get_redis_client()
        key = _index_key(str(user_id), run_id)
        now = _now()
        origin = created_at or _origin(now)
        if origin is None or now >= origin + timedelta(seconds=RETENTION_SECONDS):
            return
        expiry_key = key + ":expiry"
        client.set(
            expiry_key,
            (origin + timedelta(seconds=RETENTION_SECONDS)).isoformat(),
            nx=True,
            ex=RETENTION_SECONDS + METADATA_SECONDS,
        )
        raw_expiry = client.get(expiry_key)
        if raw_expiry is None:
            return
        expires = datetime.fromisoformat(raw_expiry.decode() if isinstance(raw_expiry, bytes) else raw_expiry)
        if now >= expires:
            return
        if isinstance(payload, bytes):
            body = payload
            representation = "original"
            content_type = "application/xml" if kind == "xml_file" else "application/octet-stream"
        else:
            if isinstance(payload, str):
                with suppress(ValueError):
                    payload = json.loads(payload)
            body = json.dumps(_redact(payload), default=json_serial, sort_keys=True).encode()
            representation = "normalized"
            content_type = "application/json"
        artifact_id = hashlib.sha256(kind.encode() + b":" + body).hexdigest()
        s3, bucket = _storage()
        status = "available"
        owner_hash = hashlib.sha256(str(user_id).encode()).hexdigest()
        run_hash = hashlib.sha256(run_id.encode()).hexdigest()
        object_key = f"sync-received/{owner_hash}/{run_hash}/{artifact_id}"
        if len(body) > MAX_BYTES:
            status = "oversized"
        elif s3 is None or not bucket:
            status = "failed"
        artifact = {
            "artifact_id": artifact_id,
            "captured_at": now.isoformat(),
            "expires_at": expires.isoformat(),
            "representation": representation,
            "kind": kind,
            "content_type": content_type,
            "size_bytes": len(body),
            "status": status,
            "label": label or kind.replace("_", " "),
            "object_key": object_key,
        }
        lease_key = key + ":writer:" + artifact_id
        owner = uuid4().hex
        pending = artifact | {"status": "failed"}
        # Reservation, cap check, and ownership are one Redis operation. Existing
        # failed slots are reused after lease expiry; successful slots never reopen.
        admitted = client.eval(
            """
            local old = redis.call('HGET', KEYS[1], ARGV[1])
            if old then
                local status = cjson.decode(old)['status']
                if status == 'available' or status == 'oversized' then return 0 end
            elseif redis.call('HLEN', KEYS[1]) >= tonumber(ARGV[2]) then
                redis.call('SET', KEYS[3], '1', 'EX', ARGV[6])
                return 0
            end
            if not redis.call('SET', KEYS[2], ARGV[3], 'NX', 'EX', ARGV[4]) then return 0 end
            if not old then redis.call('HSET', KEYS[1], ARGV[1], ARGV[5]) end
            redis.call('EXPIREAT', KEYS[1], ARGV[7])
            return 1
            """,
            3,
            key,
            lease_key,
            key + ":partial",
            artifact_id,
            MAX_ARTIFACTS,
            owner,
            LEASE_SECONDS,
            json.dumps(pending),
            METADATA_SECONDS,
            int(expires.timestamp()) + METADATA_SECONDS,
        )
        if not admitted:
            return
        if status == "available":
            try:
                # Conditional creation avoids overwriting a body uploaded by a
                # crashed or delayed previous owner. Such bodies are identical.
                s3.put_object(
                    Bucket=bucket,
                    Key=object_key,
                    Body=body,
                    ContentType=content_type,
                    ServerSideEncryption="AES256",
                    Expires=expires,
                    IfNoneMatch="*",
                )
            except Exception as exc:
                error_code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                if error_code not in ("PreconditionFailed", "412"):
                    status = "failed"
                    logger.warning("Received-data object write failed", exc_info=True)
        artifact["status"] = status
        # A delayed writer cannot publish metadata or release a newer lease.
        client.eval(
            """
            if redis.call('GET', KEYS[2]) ~= ARGV[1] then return 0 end
            redis.call('HSET', KEYS[1], ARGV[2], ARGV[3])
            redis.call('DEL', KEYS[2])
            return 1
            """,
            2,
            key,
            lease_key,
            owner,
            artifact_id,
            json.dumps(artifact),
        )
    except Exception:
        logger.warning("Received-data capture failed", exc_info=True)


def _offset(cursor: str | None) -> int:
    if cursor is None:
        return 0
    if not cursor.isascii() or not cursor.isdigit() or len(cursor) > 9:
        raise HTTPException(400, "Invalid cursor")
    return int(cursor)


def list_artifacts(user_id: str, run_id: str, *, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
    offset = _offset(cursor)
    key = _index_key(str(user_id), run_id)
    try:
        client = get_redis_client()
        raw_expiry = client.get(key + ":expiry")
        if isinstance(raw_expiry, bytes):
            raw_expiry = raw_expiry.decode()
        expires = datetime.fromisoformat(raw_expiry) if raw_expiry else None
        artifacts = sorted((json.loads(value) for value in client.hvals(key)), key=lambda item: item["artifact_id"])
        expired = expires is not None and _now() >= expires
        if expired:
            state = "expired"
            for item in artifacts:
                item["status"] = "expired"
        elif _storage()[0] is None:
            state = "unavailable"
        elif any(item["status"] != "available" for item in artifacts) or client.exists(key + ":partial"):
            state = "partial"
        elif not artifacts:
            state = "not_captured"
        else:
            state = "available"
        page = [
            {k: v for k, v in item.items() if k != "object_key"}
            for item in artifacts[offset : offset + min(limit, 100)]
        ]
        next_offset = offset + len(page)
        return {
            "user_id": str(user_id),
            "run_id": run_id,
            "expires_at": expires.isoformat() if expires else None,
            "capture_status": state,
            "artifacts": page,
            "next_cursor": str(next_offset) if next_offset < len(artifacts) else None,
        }
    except HTTPException:
        raise
    except Exception:
        logger.warning("Received-data metadata read failed", exc_info=True)
        return {
            "user_id": str(user_id),
            "run_id": run_id,
            "expires_at": None,
            "capture_status": "unavailable",
            "artifacts": [],
            "next_cursor": None,
        }


def preview(
    user_id: str, run_id: str, artifact_id: str, *, limit: int = 100, cursor: str | None = None
) -> dict[str, Any]:
    offset = _offset(cursor)
    try:
        raw = get_redis_client().hget(_index_key(str(user_id), run_id), artifact_id)
        if raw is None:
            raise HTTPException(404, "Artifact not found")
        item = json.loads(raw)
        if _now() >= datetime.fromisoformat(item["expires_at"]):
            raise HTTPException(410, "Artifact expired")
        s3, bucket = _storage()
        if item["status"] != "available" or s3 is None:
            raise HTTPException(503, "Artifact unavailable")
        if item["content_type"] != "application/json":
            return {k: item[k] for k in ("artifact_id", "representation", "content_type", "size_bytes")} | {
                "preview": {"format": "binary", "records": None, "text": None, "truncated": False, "next_cursor": None}
            }
        response = s3.get_object(Bucket=bucket, Key=item["object_key"])
        stream = response["Body"]
        try:
            body = stream.read(MAX_BYTES + 1)
        finally:
            stream.close()
        if len(body) > MAX_BYTES:
            raise HTTPException(503, "Artifact exceeds preview limit")
        data: dict[str, Any] = {
            "format": "binary",
            "records": None,
            "text": None,
            "truncated": False,
            "next_cursor": None,
        }
        if item["content_type"] == "application/json":
            parsed = json.loads(body)
            records = parsed if isinstance(parsed, list) else [parsed]
            page = records[offset : offset + min(limit, 100)]
            # Bound serialized response size even for very large individual records.
            if len(json.dumps(page).encode()) > 256 * 1024:
                data.update(format="text", text=body.decode()[:MAX_TEXT], truncated=True)
            else:
                following = offset + len(page)
                data.update(
                    format="json_records",
                    records=page,
                    truncated=following < len(records),
                    next_cursor=str(following) if following < len(records) else None,
                )
        # XML is deliberately not parsed or echoed: it may include unredacted secrets.
        return {k: item[k] for k in ("artifact_id", "representation", "content_type", "size_bytes")} | {"preview": data}
    except HTTPException:
        raise
    except Exception:
        logger.warning("Received-data object read failed", exc_info=True)
        raise HTTPException(503, "Artifact unavailable") from None
