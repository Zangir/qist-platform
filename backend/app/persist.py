"""Keeps the SQLite database safe on hosts whose local disk is wiped at every restart (Hugging Face Spaces).

The live database stays on the local disk, where SQLite's locking works. A second folder (a mounted storage bucket) holds
snapshots of it:
  - at start-up, if there is no local database, the newest snapshot that passes an integrity check is copied back;
  - while running, a background thread takes a consistent snapshot (SQLite's backup API) whenever the data changed, and at most
    every `interval` seconds, and once more on shutdown;
  - snapshots are written under a new timestamped name and verified before older ones are pruned, so a crash in the middle of a
    copy can never destroy the last good one.
Writes made in the last `interval` seconds before an abrupt crash can be lost; nothing older can.
"""
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PREFIX, SUFFIX = "qist-", ".db"
KEEP = 6


def _ok(path: Path) -> bool:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return con.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except Exception:
        return False


def snapshots(folder: Path) -> list[Path]:
    return sorted((p for p in folder.glob(f"{PREFIX}*{SUFFIX}") if p.is_file()), key=lambda p: p.name, reverse=True)


def restore_if_needed(db_path: Path, folder: Path) -> str:
    """Returns what happened: 'present' | 'restored:<name>' | 'empty' | 'unusable'."""
    if db_path.exists() and db_path.stat().st_size > 0:
        return "present"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    snaps = snapshots(folder) if folder.is_dir() else []
    if not snaps:
        return "empty"
    for s in snaps:                                   # newest first; the first one that is intact wins
        tmp = db_path.with_suffix(".restore")
        try:
            shutil.copyfile(s, tmp)
        except Exception:
            continue
        if _ok(tmp):
            os.replace(tmp, db_path)
            return f"restored:{s.name}"
        tmp.unlink(missing_ok=True)
    return "unusable"


def take_snapshot(db_path: Path, folder: Path) -> Path | None:
    """One verified snapshot; None if the database does not exist yet. Old snapshots are pruned only after this one is checked."""
    if not db_path.exists():
        return None
    work = db_path.with_suffix(".snap")
    src, dst = sqlite3.connect(db_path), sqlite3.connect(work)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    name = f"{PREFIX}{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}{SUFFIX}"
    target = folder / name
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(work, target)
    work.unlink(missing_ok=True)
    if not _ok(target) or target.stat().st_size == 0:
        target.unlink(missing_ok=True)
        raise RuntimeError("snapshot failed verification; older snapshots kept")
    for old in snapshots(folder)[KEEP:]:
        try:
            old.unlink()
        except Exception:
            pass
    return target


class Snapshotter:
    def __init__(self, db_path: Path, folder: Path, interval: float = 30.0, log=print):
        self.db, self.folder, self.interval, self.log = db_path, folder, interval, log
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="qist-snapshots", daemon=True)
        self._last = None

    def _version(self):
        """Changes whenever the database file is written (size+mtime of the file and its WAL)."""
        parts = []
        for p in (self.db, Path(str(self.db) + "-wal")):
            try:
                st = p.stat(); parts.append((st.st_size, st.st_mtime_ns))
            except FileNotFoundError:
                parts.append(None)
        return tuple(parts)

    def snapshot_now(self, force=False) -> bool:
        v = self._version()
        if not force and v == self._last:
            return False
        try:
            take_snapshot(self.db, self.folder)
            self._last = v
            return True
        except Exception as e:                        # a failed snapshot must never take the API down
            self.log(f"[qist] snapshot failed: {e}")
            return False

    def _run(self):
        while not self._stop.wait(self.interval):
            self.snapshot_now()

    def start(self):
        self.snapshot_now(force=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        self.snapshot_now(force=True)
