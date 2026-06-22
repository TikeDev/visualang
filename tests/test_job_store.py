import dataclasses
import hashlib
import os
import sqlite3
import sys
import threading
import uuid

import pytest


BACKEND_DIR = os.path.join(os.path.dirname(__file__), "..", "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from job_store import JobAccess, JobStore


def test_job_survives_store_reopen(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job({"kind": "youtube", "url": "https://example.test/video"}, now=100.0)

    reopened = JobStore(tmp_path)
    job = reopened.require_by_resume_token(access.resume_token, now=101.0)

    assert job == {
        "id": access.job_id,
        "source": {"kind": "youtube", "url": "https://example.test/video"},
        "status": "queued",
        "stage": "transcript",
        "progress": {},
        "created_at": 100.0,
        "updated_at": 100.0,
        "expires_at": 86500.0,
    }
    assert store.job_dir(access.job_id).is_dir()
    with pytest.raises(dataclasses.FrozenInstanceError):
        access.secret = "replacement"


def test_resume_secret_is_not_stored_in_plaintext(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job("uploaded-audio", now=100.0)
    database_path = tmp_path / "jobs.sqlite3"

    with sqlite3.connect(database_path) as connection:
        stored_hash = connection.execute(
            "SELECT resume_token_hash FROM jobs WHERE id = ?", (access.job_id,)
        ).fetchone()[0]
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()

    assert stored_hash == hashlib.sha256(access.secret.encode()).hexdigest()
    storage_files = [
        path
        for path in (
            database_path,
            tmp_path / "jobs.sqlite3-wal",
            tmp_path / "jobs.sqlite3-shm",
        )
        if path.exists()
    ]
    assert storage_files
    for path in storage_files:
        assert access.secret.encode() not in path.read_bytes(), path.name
    assert "resume_token_hash" not in store.require_by_resume_token(
        access.resume_token, now=101.0
    )


def test_wrong_resume_secret_fails(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job("youtube", now=100.0)
    wrong_token = f"{access.job_id}.wrong-secret"

    assert store.get_by_resume_token(wrong_token, now=101.0) is None
    with pytest.raises(KeyError):
        store.require_by_resume_token(wrong_token, now=101.0)


def test_expired_lookup_deletes_metadata_and_artifacts(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    access = store.create_job("youtube", now=100.0)
    artifact = store.job_dir(access.job_id) / "frame.png"
    artifact.write_bytes(b"generated image")

    assert store.get_by_resume_token(access.resume_token, now=110.0) is None
    assert not store.job_dir(access.job_id).exists()

    reopened = JobStore(tmp_path, retention_seconds=10)
    assert reopened.get_by_resume_token(access.resume_token, now=105.0) is None


def test_update_persists_progress_without_extending_expiry(tmp_path):
    store = JobStore(tmp_path, retention_seconds=60)
    access = store.create_job("youtube", now=100.0)

    updated = store.update(
        access.job_id,
        status="running",
        stage="images",
        progress={"completed": 2, "total": 5},
        language="ja",
    )
    reopened = JobStore(tmp_path, retention_seconds=60)
    persisted = reopened.require_by_resume_token(access.resume_token, now=101.0)

    assert persisted["status"] == "running"
    assert persisted["stage"] == "images"
    assert persisted["progress"] == {"completed": 2, "total": 5}
    assert persisted["language"] == "ja"
    assert persisted["expires_at"] == 160.0
    assert persisted["updated_at"] == updated["updated_at"]
    assert persisted["updated_at"] >= persisted["created_at"]


def test_concurrent_updates_retain_distinct_top_level_fields(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    access = store.create_job("youtube")
    first_reached_write = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    failures = []
    original_dumps = sys.modules["job_store"].json.dumps

    def controlled_dumps(value, *args, **kwargs):
        if value.get("first_result") == "transcript-ready":
            first_reached_write.set()
            assert release_first.wait(timeout=2)
        return original_dumps(value, *args, **kwargs)

    monkeypatch.setattr("job_store.json.dumps", controlled_dumps)

    def update_first():
        try:
            store.update(access.job_id, first_result="transcript-ready")
        except Exception as error:  # pragma: no cover - asserted below
            failures.append(error)

    def update_second():
        try:
            store.update(access.job_id, second_result="concepts-ready")
        except Exception as error:  # pragma: no cover - asserted below
            failures.append(error)
        finally:
            second_finished.set()

    first = threading.Thread(target=update_first)
    second = threading.Thread(target=update_second)
    first.start()
    assert first_reached_write.wait(timeout=2)
    second.start()
    assert not second_finished.wait(timeout=0.25)
    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert failures == []
    persisted = store.require_by_resume_token(access.resume_token)
    assert persisted["first_result"] == "transcript-ready"
    assert persisted["second_result"] == "concepts-ready"


def test_delete_sql_failure_restores_artifacts_and_preserves_metadata(tmp_path):
    store = JobStore(tmp_path)
    access = store.create_job("youtube")
    artifact = store.job_dir(access.job_id) / "frame.png"
    artifact.write_bytes(b"frame")
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_job_delete
            BEFORE DELETE ON jobs
            BEGIN
                SELECT RAISE(ABORT, 'delete rejected');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="delete rejected"):
        store.delete_job(access.job_id)

    assert store.require_by_resume_token(access.resume_token)["id"] == access.job_id
    assert artifact.read_bytes() == b"frame"


def test_expiry_sql_failure_restores_artifacts_and_preserves_metadata(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    access = store.create_job("youtube", now=100.0)
    artifact = store.job_dir(access.job_id) / "frame.png"
    artifact.write_bytes(b"frame")
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_expired_job_delete
            BEFORE DELETE ON jobs
            BEGIN
                SELECT RAISE(ABORT, 'expiry delete rejected');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="expiry delete rejected"):
        store.expire_jobs(now=110.0)

    assert store.require_by_resume_token(access.resume_token, now=109.0)["id"] == access.job_id
    assert artifact.read_bytes() == b"frame"


def test_expire_jobs_restores_stale_tombstone_when_metadata_remains(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    access = store.create_job("youtube", now=995.0)
    artifact_dir = store.job_dir(access.job_id)
    artifact = artifact_dir / "frame.png"
    artifact.write_bytes(b"frame")
    tombstone = (
        tmp_path / "trash" / f"{access.job_id}.{uuid.uuid4().hex}.tombstone"
    )
    artifact_dir.rename(tombstone)
    os.utime(tombstone, (989.0, 989.0))

    assert store.expire_jobs(now=1000.0) == 0
    assert artifact.read_bytes() == b"frame"
    assert not tombstone.exists()


def test_expire_jobs_removes_stale_tombstone_after_metadata_commit(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    access = store.create_job("youtube")
    artifact_dir = store.job_dir(access.job_id)
    tombstone = (
        tmp_path / "trash" / f"{access.job_id}.{uuid.uuid4().hex}.tombstone"
    )
    artifact_dir.rename(tombstone)
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        connection.execute("DELETE FROM jobs WHERE id = ?", (access.job_id,))
    os.utime(tombstone, (989.0, 989.0))

    assert store.expire_jobs(now=1000.0) == 0
    assert not tombstone.exists()


def test_expire_jobs_preserves_fresh_canonical_orphan(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    orphan_dir = tmp_path / "jobs" / uuid.uuid4().hex
    orphan_dir.mkdir()
    os.utime(orphan_dir, (995.0, 995.0))

    assert store.expire_jobs(now=1000.0) == 0
    assert orphan_dir.is_dir()


def test_expire_jobs_removes_old_canonical_orphan(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    orphan_dir = tmp_path / "jobs" / uuid.uuid4().hex
    orphan_dir.mkdir()
    os.utime(orphan_dir, (989.0, 989.0))

    assert store.expire_jobs(now=1000.0) == 0
    assert not orphan_dir.exists()


def test_expire_jobs_preserves_noncanonical_directory(tmp_path):
    store = JobStore(tmp_path, retention_seconds=10)
    unrelated_dir = tmp_path / "jobs" / "unrelated-cache"
    unrelated_dir.mkdir()
    os.utime(unrelated_dir, (1.0, 1.0))

    assert store.expire_jobs(now=1000.0) == 0
    assert unrelated_dir.is_dir()


def test_job_artifact_paths_reject_traversal(tmp_path):
    store = JobStore(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="canonical UUID4"):
        store.job_dir("../../outside")
    with pytest.raises(ValueError, match="canonical UUID4"):
        store.delete_job("../../outside")

    assert outside.is_dir()


@pytest.mark.parametrize("retention_seconds", [0, -1])
def test_retention_seconds_must_be_positive(tmp_path, retention_seconds):
    with pytest.raises(ValueError, match="retention_seconds must be positive"):
        JobStore(tmp_path, retention_seconds=retention_seconds)


@pytest.mark.parametrize(
    "reserved_field",
    ["id", "created_at", "updated_at", "expires_at", "resume_token_hash"],
)
def test_update_rejects_reserved_fields(tmp_path, reserved_field):
    store = JobStore(tmp_path)
    access = store.create_job("youtube")

    with pytest.raises(ValueError, match="reserved job fields"):
        store.update(access.job_id, **{reserved_field: "replacement"})


def test_schema_has_version_and_expiry_index(tmp_path):
    JobStore(tmp_path)

    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        user_version = connection.execute("PRAGMA user_version").fetchone()[0]
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('jobs')").fetchall()
        }

    assert user_version == 1
    assert "idx_jobs_expires_at" in indexes


def test_schema_initializes_existing_version_zero_database(tmp_path):
    database_path = tmp_path / "jobs.sqlite3"
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0

    JobStore(tmp_path)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'jobs'"
        ).fetchone() == ("jobs",)


def test_schema_rejects_database_from_newer_version(tmp_path):
    database_path = tmp_path / "jobs.sqlite3"
    tmp_path.mkdir(exist_ok=True)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA user_version = 2")

    with pytest.raises(RuntimeError, match="newer schema version 2"):
        JobStore(tmp_path)

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2


def test_create_builds_artifact_directory_before_publishing_row(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    fixed_id = uuid.uuid4()
    monkeypatch.setattr("job_store.uuid.uuid4", lambda: fixed_id)
    original_connect = store._connect

    def connect_with_artifact_check():
        connection = original_connect()
        connection.create_function(
            "artifact_dir_exists",
            1,
            lambda job_id: int(store.job_dir(job_id).is_dir()),
        )
        return connection

    monkeypatch.setattr(store, "_connect", connect_with_artifact_check)
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        connection.execute(
            """
            CREATE TRIGGER require_artifact_dir_before_insert
            BEFORE INSERT ON jobs
            WHEN artifact_dir_exists(NEW.id) = 0
            BEGIN
                SELECT RAISE(ABORT, 'artifact directory missing');
            END
            """
        )

    access = store.create_job("youtube")

    assert access.job_id == fixed_id.hex
    assert store.job_dir(access.job_id).is_dir()


def test_create_cleans_artifact_directory_when_insert_fails(tmp_path, monkeypatch):
    store = JobStore(tmp_path)
    fixed_id = uuid.uuid4()
    monkeypatch.setattr("job_store.uuid.uuid4", lambda: fixed_id)
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_job_insert
            BEFORE INSERT ON jobs
            BEGIN
                SELECT RAISE(ABORT, 'insert rejected');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="insert rejected"):
        store.create_job("youtube")

    assert not store.job_dir(fixed_id.hex).exists()
    with sqlite3.connect(tmp_path / "jobs.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0
