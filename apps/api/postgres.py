"""Postgres adapter for the pilot store; write transactions serialize state transitions."""
import re

SCHEMA = '''
CREATE TABLE IF NOT EXISTS invitations (id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL, identity TEXT NOT NULL, issuer TEXT NOT NULL, payload TEXT NOT NULL, revoked INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS courses (id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, owner TEXT NOT NULL, course_id TEXT NOT NULL, payload TEXT NOT NULL, content TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, owner TEXT NOT NULL, course_id TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL, request_hash TEXT NOT NULL, idempotency_key TEXT NOT NULL, UNIQUE(owner, course_id, idempotency_key));
CREATE TABLE IF NOT EXISTS feedback (id TEXT PRIMARY KEY, owner TEXT NOT NULL, run_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS courses_owner ON courses(owner);
CREATE INDEX IF NOT EXISTS documents_owner_course ON documents(owner,course_id);
CREATE INDEX IF NOT EXISTS runs_owner_course ON runs(owner,course_id);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);
'''


class Row(dict):
    def __getitem__(self, key):
        return tuple(self.values())[key] if isinstance(key, int) else super().__getitem__(key)


def row_factory(cursor):
    names = [column.name for column in cursor.description] if cursor.description else []
    return lambda values: Row(zip(names, values))


class Connection:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, params=()):
        if sql == 'BEGIN IMMEDIATE':
            # All mutation paths take the same transaction lock. No model calls occur inside it.
            return self.connection.execute('SELECT pg_advisory_xact_lock(73928461)')
        sql = sql.replace('?', '%s')
        sql = re.sub(r'ORDER BY rowid', "ORDER BY (payload::jsonb ->> 'created_at')", sql)
        return self.connection.execute(sql, params)
