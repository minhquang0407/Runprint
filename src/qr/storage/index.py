"""
SQLite Run Index
================
Maintains a local SQLite cache for fast `qr list` queries and run lookups.
Manifest files remain the source of truth; the index can be fully rebuilt.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from qr.manifest import RunManifest


class RunIndex:
    """Manages `.qr/index.sqlite` cache."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    parent_run_id TEXT,
                    status TEXT NOT NULL,
                    command TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_seconds REAL,
                    exit_code INTEGER,
                    git_commit TEXT,
                    git_branch TEXT,
                    git_dirty INTEGER,
                    tags TEXT,
                    cwd TEXT NOT NULL
                )
                """
            )
            # Migration check: add columns if missing in older databases
            cursor = conn.execute("PRAGMA table_info(runs)")
            cols = [row["name"] for row in cursor.fetchall()]
            if "tags" not in cols:
                conn.execute("ALTER TABLE runs ADD COLUMN tags TEXT")
            if "restorability_score" not in cols:
                conn.execute("ALTER TABLE runs ADD COLUMN restorability_score INTEGER")
            if "restorability_status" not in cols:
                conn.execute("ALTER TABLE runs ADD COLUMN restorability_status TEXT")
            conn.commit()

    def upsert_run(self, manifest: RunManifest) -> None:
        """Insert or update a run entry in the index."""
        tags_str = ",".join(manifest.tags) if manifest.tags else ""
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs (
                    run_id, parent_run_id, status, command, started_at, finished_at,
                    duration_seconds, exit_code, git_commit, git_branch, git_dirty, tags, cwd,
                    restorability_score, restorability_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    manifest.parent_run_id,
                    manifest.status,
                    " ".join(manifest.command),
                    manifest.timestamps.started_at,
                    manifest.timestamps.finished_at,
                    manifest.duration_seconds,
                    manifest.exit_code,
                    manifest.git.commit if manifest.git else None,
                    manifest.git.branch if manifest.git else None,
                    1 if (manifest.git and manifest.git.dirty) else 0,
                    tags_str,
                    manifest.cwd,
                    manifest.restorability_score,
                    manifest.restorability_status,
                ),
            )
            conn.commit()

    def list_runs(self, limit: int = 50, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieve recent runs ordered by start time desc, optionally filtered by tag."""
        with self._get_connection() as conn:
            if tag:
                cursor = conn.execute(
                    """
                    SELECT run_id, parent_run_id, status, command, started_at, finished_at,
                           duration_seconds, exit_code, git_commit, git_dirty, tags,
                           restorability_score, restorability_status
                    FROM runs
                    WHERE (',' || tags || ',') LIKE ?
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (f"%,{tag},%", limit),
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT run_id, parent_run_id, status, command, started_at, finished_at,
                           duration_seconds, exit_code, git_commit, git_dirty, tags,
                           restorability_score, restorability_status
                    FROM runs
                    ORDER BY started_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]

    def rebuild_from_manifests(self, manifests: List[RunManifest]) -> None:
        """Wipe and rebuild the SQLite index from manifests."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM runs")
            for mf in manifests:
                self.upsert_run(mf)
            conn.commit()
