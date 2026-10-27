"""Single-host durable store. Every private lookup includes the authenticated owner."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.dsn = str(path) if str(path).startswith(('postgres://', 'postgresql://')) else None
        if self.dsn:
            import psycopg
            from .postgres import SCHEMA
            with psycopg.connect(self.dsn, connect_timeout=10) as db:
                db.execute('SELECT pg_advisory_xact_lock(73928460)')
                db.execute(SCHEMA)
            return
        if os.getenv('VERCEL'):
            raise ValueError('Vercel requires DATABASE_URL; SQLite cannot persist in serverless functions')
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS invitations (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, identity TEXT NOT NULL, issuer TEXT NOT NULL, payload TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS courses (id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, owner TEXT NOT NULL, course_id TEXT NOT NULL, payload TEXT NOT NULL, content TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, course_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, request_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL, UNIQUE(owner, course_id, idempotency_key));
            CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, owner TEXT NOT NULL, run_id TEXT NOT NULL, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        if self.dsn:
            import psycopg
            from .postgres import Connection, row_factory
            with psycopg.connect(self.dsn, row_factory=row_factory, connect_timeout=10) as db:
                yield Connection(db)
            return
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            changed = db.total_changes > 0
            db.commit()
            if changed:
                from .events import notify_local
                notify_local(self.path)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def pack(value):
    return json.dumps(value, ensure_ascii=False)


def update_run(db, run, state):
    db.execute('UPDATE runs SET status=?,payload=?,state=? WHERE id=?',
               (run['status'], pack(run), pack(state), run['id']))


def recover_expired(db, owner=None, course_id=None):
    from datetime import datetime, timezone
    query = "SELECT * FROM runs WHERE status='running'"
    params = []
    if owner is not None:
        query += ' AND owner=? AND course_id=?'
        params = [owner, course_id]
    for row in db.execute(query, params).fetchall():
        state = json.loads(row['state'])
        if state.get('lease_until', '') < datetime.now(timezone.utc).isoformat():
            run = json.loads(row['payload'])
            run.update(status='failed', error='worker_interrupted')
            update_run(db, run, state)
