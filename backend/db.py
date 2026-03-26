"""SQLite-backed migration history storage."""
import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "migrations.db")


class MigrationDB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id TEXT PRIMARY KEY,
                source_provider TEXT,
                target_provider TEXT,
                source_repo TEXT,
                target_repo TEXT,
                status TEXT,
                results TEXT,
                created_at TEXT,
                completed_at TEXT
            )
        """)
        self.conn.commit()

    def save_migration(self, job_id: str, payload: dict, status: str, results: dict):
        self.conn.execute("""
            INSERT OR REPLACE INTO migrations
            (id, source_provider, target_provider, source_repo, target_repo, status, results, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            job_id,
            payload.get("source_provider", ""),
            payload.get("target_provider", ""),
            payload.get("source_repo", ""),
            payload.get("target_repo", ""),
            status,
            json.dumps(results),
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat(),
        ))
        self.conn.commit()

    def get_migration(self, job_id: str):
        cur = self.conn.execute("SELECT * FROM migrations WHERE id = ?", (job_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_all_migrations(self, limit=50):
        cur = self.conn.execute("SELECT * FROM migrations ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row_to_dict(row) for row in cur.fetchall()]

    def _row_to_dict(self, row):
        return {
            "id": row[0],
            "source_provider": row[1],
            "target_provider": row[2],
            "source_repo": row[3],
            "target_repo": row[4],
            "status": row[5],
            "results": json.loads(row[6]) if row[6] else {},
            "created_at": row[7],
            "completed_at": row[8],
        }
