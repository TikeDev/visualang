from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import shutil
import sqlite3
import time
import uuid
from typing import Any


SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class JobAccess:
    job_id: str
    secret: str

    @property
    def resume_token(self) -> str:
        return f"{self.job_id}.{self.secret}"


class JobStore:
    _RESERVED_UPDATE_FIELDS = frozenset(
        {"id", "created_at", "updated_at", "expires_at", "resume_token_hash"}
    )

    def __init__(self, root: Path, retention_seconds: int = 86400) -> None:
        if retention_seconds <= 0:
            raise ValueError("retention_seconds must be positive")
        self.root = Path(root)
        self.retention_seconds = retention_seconds
        self.root.mkdir(parents=True, exist_ok=True)
        self._jobs_root = self.root / "jobs"
        self._jobs_root.mkdir(parents=True, exist_ok=True)
        self._trash_root = self.root / "trash"
        self._trash_root.mkdir(parents=True, exist_ok=True)
        self._database_path = self.root / "jobs.sqlite3"
        self._initialize_database()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize_database(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database uses newer schema version {version}; "
                    f"this application supports version {SCHEMA_VERSION}"
                )
            if version == SCHEMA_VERSION:
                return
            if version == 0:
                with connection:
                    connection.execute(
                        """
                        CREATE TABLE IF NOT EXISTS jobs (
                            id TEXT PRIMARY KEY,
                            resume_token_hash TEXT NOT NULL,
                            created_at REAL NOT NULL,
                            updated_at REAL NOT NULL,
                            expires_at REAL NOT NULL,
                            payload_json TEXT NOT NULL
                        )
                        """
                    )
                    connection.execute(
                        "CREATE INDEX IF NOT EXISTS idx_jobs_expires_at "
                        "ON jobs (expires_at)"
                    )
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                return
            raise RuntimeError(f"Unsupported schema version {version}")

    @staticmethod
    def _secret_hash(secret: str) -> str:
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        try:
            parsed = uuid.UUID(job_id)
        except (AttributeError, ValueError) as error:
            raise ValueError("job_id must be a canonical UUID4 hex string") from error
        if parsed.version != 4 or parsed.hex != job_id:
            raise ValueError("job_id must be a canonical UUID4 hex string")

    @staticmethod
    def _public_job(row: sqlite3.Row) -> dict[str, Any]:
        payload = json.loads(row["payload_json"])
        payload.pop("resume_token_hash", None)
        return {
            **payload,
            "id": row["id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
        }

    def create_job(self, source: Any, now: float | None = None) -> JobAccess:
        timestamp = time.time() if now is None else float(now)
        job_id = uuid.uuid4().hex
        secret = secrets.token_urlsafe(32)
        payload = {
            "source": source,
            "status": "queued",
            "stage": "transcript",
            "progress": {},
        }
        artifact_dir = self.job_dir(job_id)
        artifact_created = False
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                artifact_dir.mkdir()
                artifact_created = True
                connection.execute(
                    """
                    INSERT INTO jobs (
                        id, resume_token_hash, created_at, updated_at,
                        expires_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        self._secret_hash(secret),
                        timestamp,
                        timestamp,
                        timestamp + self.retention_seconds,
                        json.dumps(payload),
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                if artifact_created:
                    shutil.rmtree(artifact_dir)
                raise
        return JobAccess(job_id=job_id, secret=secret)

    def get_by_resume_token(
        self, token: str, now: float | None = None
    ) -> dict[str, Any] | None:
        job_id, separator, secret = token.partition(".")
        if not separator or not job_id or not secret:
            return None

        timestamp = time.time() if now is None else float(now)
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= timestamp:
            if self._delete_job(job_id, expires_at_or_before=timestamp):
                return None
            return self.get_by_resume_token(token, now=timestamp)
        if not hmac.compare_digest(
            row["resume_token_hash"], self._secret_hash(secret)
        ):
            return None
        return self._public_job(row)

    def require_by_resume_token(
        self, token: str, now: float | None = None
    ) -> dict[str, Any]:
        job = self.get_by_resume_token(token, now=now)
        if job is None:
            raise KeyError("Job not found or resume token is invalid")
        return job

    def update(self, job_id: str, **fields: Any) -> dict[str, Any]:
        self._validate_job_id(job_id)
        reserved = self._RESERVED_UPDATE_FIELDS.intersection(fields)
        if reserved:
            names = ", ".join(sorted(reserved))
            raise ValueError(f"Cannot update reserved job fields: {names}")
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                if row is None:
                    raise KeyError(f"Job not found: {job_id}")
                payload = json.loads(row["payload_json"])
                payload.update(fields)
                updated_at = time.time()
                connection.execute(
                    "UPDATE jobs SET payload_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(payload), updated_at, job_id),
                )
                updated_row = connection.execute(
                    "SELECT * FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self._public_job(updated_row)

    def job_dir(self, job_id: str) -> Path:
        self._validate_job_id(job_id)
        jobs_root = self._jobs_root.resolve()
        artifact_dir = (jobs_root / job_id).resolve()
        if artifact_dir.parent != jobs_root:
            raise ValueError("job artifact path must stay inside the jobs root")
        return artifact_dir

    def delete_job(self, job_id: str) -> None:
        self._delete_job(job_id)

    def _new_tombstone(self, job_id: str) -> Path:
        nonce = uuid.uuid4().hex
        return self._trash_root / f"{job_id}.{nonce}.tombstone"

    def _restore_tombstone(self, tombstone: Path | None, artifact_dir: Path) -> None:
        if tombstone is not None and tombstone.exists():
            tombstone.rename(artifact_dir)

    def _delete_job(
        self, job_id: str, expires_at_or_before: float | None = None
    ) -> bool:
        self._validate_job_id(job_id)
        artifact_dir = self.job_dir(job_id)
        tombstone = None
        if artifact_dir.exists():
            tombstone = self._new_tombstone(job_id)
            artifact_dir.rename(tombstone)

        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if expires_at_or_before is None:
                    cursor = connection.execute(
                        "DELETE FROM jobs WHERE id = ?", (job_id,)
                    )
                else:
                    cursor = connection.execute(
                        "DELETE FROM jobs WHERE id = ? AND expires_at <= ?",
                        (job_id, expires_at_or_before),
                    )
                deleted = cursor.rowcount > 0
                connection.commit()
            except Exception:
                connection.rollback()
                self._restore_tombstone(tombstone, artifact_dir)
                raise

        if not deleted and expires_at_or_before is not None:
            self._restore_tombstone(tombstone, artifact_dir)
            return False
        if tombstone is not None and tombstone.exists():
            shutil.rmtree(tombstone)
        return deleted

    def _row_exists(self, job_id: str) -> bool:
        with closing(self._connect()) as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM jobs WHERE id = ?", (job_id,)
                ).fetchone()
                is not None
            )

    def _sweep_stale_tombstones(self, timestamp: float) -> None:
        cutoff = timestamp - self.retention_seconds
        trash_root = self._trash_root.resolve()
        for tombstone in self._trash_root.iterdir():
            if tombstone.is_symlink() or not tombstone.is_dir():
                continue
            parts = tombstone.name.split(".")
            if len(parts) != 3 or parts[2] != "tombstone":
                continue
            job_id, nonce, _suffix = parts
            try:
                self._validate_job_id(job_id)
                self._validate_job_id(nonce)
            except ValueError:
                continue
            if tombstone.resolve().parent != trash_root:
                continue
            if tombstone.stat().st_mtime >= cutoff:
                continue
            artifact_dir = self.job_dir(job_id)
            if self._row_exists(job_id):
                if not artifact_dir.exists():
                    tombstone.rename(artifact_dir)
            else:
                shutil.rmtree(tombstone)

    def _sweep_old_orphan_artifacts(self, timestamp: float) -> None:
        cutoff = timestamp - self.retention_seconds
        jobs_root = self._jobs_root.resolve()
        for artifact_dir in self._jobs_root.iterdir():
            if artifact_dir.is_symlink() or not artifact_dir.is_dir():
                continue
            try:
                self._validate_job_id(artifact_dir.name)
            except ValueError:
                continue
            if artifact_dir.resolve().parent != jobs_root:
                continue
            if artifact_dir.stat().st_mtime >= cutoff:
                continue
            if not self._row_exists(artifact_dir.name):
                shutil.rmtree(artifact_dir)

    def expire_jobs(self, now: float | None = None) -> int:
        timestamp = time.time() if now is None else float(now)
        self._sweep_stale_tombstones(timestamp)
        with closing(self._connect()) as connection:
            job_ids = [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM jobs WHERE expires_at <= ?", (timestamp,)
                ).fetchall()
            ]
        deleted = sum(
            self._delete_job(job_id, expires_at_or_before=timestamp)
            for job_id in job_ids
        )
        self._sweep_old_orphan_artifacts(timestamp)
        return deleted
