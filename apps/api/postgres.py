"""Postgres adapter for the pilot store; write transactions serialize state transitions."""

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
CREATE OR REPLACE FUNCTION educator_notify_course() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE course_key TEXT;
BEGIN
    IF TG_TABLE_NAME = 'courses' THEN
        IF TG_OP = 'DELETE' THEN course_key := OLD.id; ELSE course_key := NEW.id; END IF;
    ELSE
        IF TG_OP = 'DELETE' THEN course_key := OLD.course_id; ELSE course_key := NEW.course_id; END IF;
    END IF;
    PERFORM pg_notify('course_' || md5(course_key), 'changed');
    RETURN NULL;
END;
$$;
CREATE OR REPLACE FUNCTION educator_notify_access() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('educator_access', 'changed');
    RETURN NULL;
END;
$$;
CREATE OR REPLACE TRIGGER educator_runs_changed AFTER INSERT OR UPDATE OR DELETE ON runs FOR EACH ROW EXECUTE FUNCTION educator_notify_course();
CREATE OR REPLACE TRIGGER educator_courses_changed AFTER UPDATE OR DELETE ON courses FOR EACH ROW EXECUTE FUNCTION educator_notify_course();
CREATE OR REPLACE TRIGGER educator_access_changed AFTER UPDATE OR DELETE ON invitations FOR EACH ROW EXECUTE FUNCTION educator_notify_access();
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
        return self.connection.execute(sql, params)
