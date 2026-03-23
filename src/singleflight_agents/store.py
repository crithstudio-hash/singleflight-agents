from __future__ import annotations

import hmac
import json
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .models import Receipt


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS receipts (
    fingerprint TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    scope TEXT NOT NULL,
    args_hash TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,
    output_preview TEXT NOT NULL,
    signature TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    latency_ms REAL NOT NULL,
    cost_usd REAL NOT NULL,
    executor_id TEXT NOT NULL,
    reuse_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS leases (
    fingerprint TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    expires_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_receipts_tool_name ON receipts(tool_name);
"""


class ReceiptStore:
    """SQLite-backed store for signed receipts and fingerprint leases.

    Handles persistence, HMAC signing/verification, lease acquisition,
    and aggregate summary queries.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        base_dir = Path.cwd() / ".singleflight"
        base_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = Path(db_path) if db_path else base_dir / "receipts.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._initialize()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            existing = connection.execute(
                "SELECT value FROM metadata WHERE key = 'signing_secret'"
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO metadata(key, value) VALUES (?, ?)",
                    ("signing_secret", secrets.token_hex(32)),
                )
            connection.commit()

    def _secret(self) -> bytes:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = 'signing_secret'"
            ).fetchone()
        assert row is not None
        return row["value"].encode("utf-8")

    def sign(
        self,
        *,
        fingerprint: str,
        args_hash: str,
        output_json: str,
        created_at: float,
        expires_at: float,
        latency_ms: float,
        cost_usd: float,
    ) -> str:
        payload = json.dumps(
            {
                "fingerprint": fingerprint,
                "args_hash": args_hash,
                "output_json": output_json,
                "created_at": created_at,
                "expires_at": expires_at,
                "latency_ms": latency_ms,
                "cost_usd": cost_usd,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(self._secret(), payload, "sha256").hexdigest()

    def verify(self, receipt: Receipt) -> bool:
        expected = self.sign(
            fingerprint=receipt.fingerprint,
            args_hash=receipt.args_hash,
            output_json=receipt.output_json,
            created_at=receipt.created_at,
            expires_at=receipt.expires_at,
            latency_ms=receipt.latency_ms,
            cost_usd=receipt.cost_usd,
        )
        return hmac.compare_digest(receipt.signature, expected)

    def fetch_valid_receipt(self, fingerprint: str, *, now: float | None = None) -> Receipt | None:
        now = now if now is not None else time.time()
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT *
                    FROM receipts
                    WHERE fingerprint = ? AND expires_at > ?
                    """,
                    (fingerprint, now),
                ).fetchone()
        if row is None:
            return None
        receipt = self._row_to_receipt(row)
        if not self.verify(receipt):
            return None
        return receipt

    def record_reuse(self, fingerprint: str) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE receipts
                    SET reuse_count = reuse_count + 1,
                        last_accessed_at = ?
                    WHERE fingerprint = ?
                    """,
                    (time.time(), fingerprint),
                )
                connection.commit()

    def try_acquire_lease(
        self,
        *,
        fingerprint: str,
        owner_id: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> bool:
        now = now if now is not None else time.time()
        expires_at = now + lease_seconds
        with self._lock:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT owner_id, expires_at FROM leases WHERE fingerprint = ?",
                    (fingerprint,),
                ).fetchone()
                if row is None:
                    connection.execute(
                        "INSERT INTO leases(fingerprint, owner_id, expires_at) VALUES (?, ?, ?)",
                        (fingerprint, owner_id, expires_at),
                    )
                    connection.commit()
                    return True
                if row["expires_at"] <= now:
                    connection.execute(
                        """
                        UPDATE leases
                        SET owner_id = ?, expires_at = ?
                        WHERE fingerprint = ?
                        """,
                        (owner_id, expires_at, fingerprint),
                    )
                    connection.commit()
                    return True
        return False

    def release_lease(self, fingerprint: str, owner_id: str) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    "DELETE FROM leases WHERE fingerprint = ? AND owner_id = ?",
                    (fingerprint, owner_id),
                )
                connection.commit()

    def save_receipt(self, receipt: Receipt) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO receipts(
                        fingerprint,
                        tool_name,
                        scope,
                        args_hash,
                        input_json,
                        output_json,
                        output_preview,
                        signature,
                        created_at,
                        expires_at,
                        latency_ms,
                        cost_usd,
                        executor_id,
                        reuse_count,
                        last_accessed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt.fingerprint,
                        receipt.tool_name,
                        receipt.scope,
                        receipt.args_hash,
                        receipt.input_json,
                        receipt.output_json,
                        receipt.output_preview,
                        receipt.signature,
                        receipt.created_at,
                        receipt.expires_at,
                        receipt.latency_ms,
                        receipt.cost_usd,
                        receipt.executor_id,
                        receipt.reuse_count,
                        receipt.created_at,
                    ),
                )
                connection.commit()

    def wait_for_receipt(
        self,
        fingerprint: str,
        *,
        timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> Receipt | None:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            receipt = self.fetch_valid_receipt(fingerprint)
            if receipt is not None:
                return receipt
            time.sleep(poll_interval_seconds)
        return None

    def summary(self) -> dict[str, Any]:
        with self._lock:
            with self._connect() as connection:
                receipts = connection.execute(
                    """
                    SELECT
                        COUNT(*) AS unique_executions,
                        COALESCE(SUM(reuse_count), 0) AS avoided_calls,
                        COALESCE(SUM(reuse_count * cost_usd), 0.0) AS dollars_saved,
                        COALESCE(SUM(reuse_count * latency_ms), 0.0) AS latency_saved_ms
                    FROM receipts
                    """
                ).fetchone()
                tools = connection.execute(
                    """
                    SELECT
                        tool_name,
                        COALESCE(SUM(reuse_count), 0) AS reuse_count,
                        COALESCE(SUM(reuse_count * cost_usd), 0.0) AS dollars_saved,
                        COALESCE(SUM(reuse_count * latency_ms), 0.0) AS latency_saved_ms
                    FROM receipts
                    GROUP BY tool_name
                    ORDER BY reuse_count DESC, tool_name ASC
                    """
                ).fetchall()
        return {
            "unique_executions": int(receipts["unique_executions"]),
            "avoided_calls": int(receipts["avoided_calls"]),
            "dollars_saved": float(receipts["dollars_saved"]),
            "latency_saved_ms": float(receipts["latency_saved_ms"]),
            "tools": [dict(row) for row in tools],
            "db_path": str(self._db_path),
        }

    def _row_to_receipt(self, row: sqlite3.Row) -> Receipt:
        return Receipt(
            fingerprint=row["fingerprint"],
            tool_name=row["tool_name"],
            scope=row["scope"],
            args_hash=row["args_hash"],
            input_json=row["input_json"],
            output_json=row["output_json"],
            output_preview=row["output_preview"],
            signature=row["signature"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            latency_ms=row["latency_ms"],
            cost_usd=row["cost_usd"],
            executor_id=row["executor_id"],
            reuse_count=row["reuse_count"],
        )
