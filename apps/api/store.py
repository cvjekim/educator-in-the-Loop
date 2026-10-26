"""Single-host durable store. Every private lookup includes the authenticated owner."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS courses (id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, owner TEXT NOT NULL, course_id TEXT NOT NULL, payload TEXT NOT NULL, content TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, course_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, request_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL, UNIQUE(owner, course_id, idempotency_key));
            CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, owner TEXT NOT NULL, run_id TEXT NOT NULL, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
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
