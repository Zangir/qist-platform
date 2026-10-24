"""The database survives a host whose local disk is wiped: snapshots to a folder, restore at start-up."""
import os
import sqlite3
import time
from pathlib import Path

import pytest

from backend.app import persist


def make_db(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS t (v TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [(r,) for r in rows])
    con.commit(); con.close()


def read(path: Path):
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT v FROM t ORDER BY rowid")]
    finally:
        con.close()


def test_snapshot_then_restore_after_the_local_disk_is_wiped(tmp_path):
    db, folder = tmp_path / "local" / "qist.db", tmp_path / "bucket"
    make_db(db, ["alice", "bob"])
    snap = persist.take_snapshot(db, folder)
    assert snap and snap.parent == folder and read(snap) == ["alice", "bob"]
    db.unlink()                                                              # the host restarts with an empty disk
    assert persist.restore_if_needed(db, folder).startswith("restored:")
    assert read(db) == ["alice", "bob"]


def test_restore_never_overwrites_a_database_that_is_present(tmp_path):
    db, folder = tmp_path / "qist.db", tmp_path / "bucket"
    make_db(db, ["old"]); persist.take_snapshot(db, folder)
    make_db(db, ["new"])
    assert persist.restore_if_needed(db, folder) == "present" and read(db) == ["old", "new"]


def test_nothing_to_restore_is_not_an_error(tmp_path):
    assert persist.restore_if_needed(tmp_path / "qist.db", tmp_path / "empty-bucket") == "empty"
    assert persist.take_snapshot(tmp_path / "missing.db", tmp_path / "b") is None


def test_a_corrupt_newest_snapshot_falls_back_to_the_previous_good_one(tmp_path):
    db, folder = tmp_path / "qist.db", tmp_path / "bucket"
    make_db(db, ["good"]); good = persist.take_snapshot(db, folder)
    time.sleep(0.01)
    bad = folder / "qist-99999999T999999999999.db"                          # a half-written copy sorts as the newest
    bad.write_bytes(b"SQLite format 3\x00" + os.urandom(2000))
    db.unlink()
    assert persist.restore_if_needed(db, folder) == f"restored:{good.name}" and read(db) == ["good"]
    db.unlink(); good.unlink()
    assert persist.restore_if_needed(db, folder) == "unusable"                # only garbage left: refuse rather than start from it


def test_old_snapshots_are_pruned_only_after_the_new_one_is_verified(tmp_path, monkeypatch):
    db, folder = tmp_path / "qist.db", tmp_path / "bucket"
    make_db(db, ["x"])
    for _ in range(persist.KEEP + 3):
        persist.take_snapshot(db, folder); time.sleep(0.002)
    assert len(persist.snapshots(folder)) == persist.KEEP
    before = persist.snapshots(folder)
    monkeypatch.setattr(persist, "_ok", lambda p: False)                     # the new copy fails its check
    with pytest.raises(RuntimeError):
        persist.take_snapshot(db, folder)
    assert persist.snapshots(folder) == before                               # nothing was deleted, the bad copy was removed


def test_snapshotter_copies_changes_and_not_idle_time(tmp_path):
    db, folder = tmp_path / "qist.db", tmp_path / "bucket"
    make_db(db, ["a"])
    s = persist.Snapshotter(db, folder, interval=3600)
    assert s.snapshot_now() is True and s.snapshot_now() is False             # unchanged: no new copy
    n = len(persist.snapshots(folder))
    make_db(db, ["b"])
    assert s.snapshot_now() is True and len(persist.snapshots(folder)) == n + 1
    assert read(persist.snapshots(folder)[0]) == ["a", "b"]


def test_snapshotter_survives_a_failing_folder(tmp_path):
    db = tmp_path / "qist.db"; make_db(db, ["a"])
    blocked = tmp_path / "file-not-folder"; blocked.write_text("x")
    logs = []
    s = persist.Snapshotter(db, blocked / "sub", interval=3600, log=logs.append)
    assert s.snapshot_now(force=True) is False and logs and "snapshot failed" in logs[0]


def test_stop_takes_a_final_snapshot(tmp_path):
    db, folder = tmp_path / "qist.db", tmp_path / "bucket"
    make_db(db, ["a"]); s = persist.Snapshotter(db, folder, interval=3600).start()
    make_db(db, ["late write"]); s.stop()
    assert read(persist.snapshots(folder)[0]) == ["a", "late write"]


def test_the_app_restores_its_accounts_after_a_wipe(tmp_path):
    """End to end through the real app, in fresh interpreters (the app module defines its tables once per process):
    create an account, stop (final snapshot), wipe the local disk, start again, sign in."""
    import subprocess, sys, textwrap
    db, bucket = tmp_path / "local" / "qist.db", tmp_path / "bucket"
    bucket.mkdir()
    env = dict(os.environ, QIST_DB_URL="sqlite:////" + str(db).lstrip("/"), QIST_BACKUP_DIR=str(bucket), QIST_JWT_SECRET="x" * 40,
               QIST_ADMIN_PASSWORD="admin-pass-for-tests", QIST_SNAPSHOT_SECONDS="3600")
    env.pop("QIST_ALLOW_EPHEMERAL", None)
    root = Path(__file__).resolve().parents[2]

    def run(code):
        r = subprocess.run([sys.executable, "-W", "ignore", "-c", textwrap.dedent(code)], cwd=root, env=env, capture_output=True, text=True, timeout=120)
        assert r.returncode == 0, r.stdout + r.stderr
        return r.stdout

    first = run("""
        from fastapi.testclient import TestClient
        from backend.app import main as m
        with TestClient(m.main_app) as c:
            r = c.post('/api/auth/register', json={'email': 'keep@example.org', 'name': 'Keep Me', 'password': 'correct-horse-battery'})
            print('registered', r.status_code)
    """)
    assert "registered 200" in first
    assert persist.snapshots(bucket), "the shutdown hook must leave a snapshot"
    db.unlink()                                                               # the host restarts with an empty disk
    second = run("""
        from fastapi.testclient import TestClient
        from backend.app import main as m
        print('note', m._restore_note)
        with TestClient(m.main_app) as c:
            print('keep', c.post('/api/auth/login', json={'email': 'keep@example.org', 'password': 'correct-horse-battery'}).status_code)
            print('admin', c.post('/api/auth/login', json={'email': 'admin@qist.kz', 'password': 'admin-pass-for-tests'}).status_code)
    """)
    assert "note restored:" in second and "keep 200" in second and "admin 200" in second, second


def test_startup_refuses_a_missing_backup_folder(monkeypatch, tmp_path):
    from backend.app import main as m
    monkeypatch.setattr(m, "BACKUP_DIR", str(tmp_path / "not-mounted"))
    monkeypatch.delenv("QIST_ALLOW_EPHEMERAL", raising=False)
    with pytest.raises(SystemExit) as e:
        m.check_deployment()
    assert "backup folder" in str(e.value)
    monkeypatch.setenv("QIST_ALLOW_EPHEMERAL", "1"); m.check_deployment()
