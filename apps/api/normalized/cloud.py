"""Private persistent files and post-commit queue delivery for Vercel."""
import asyncio
import hashlib
import os
from uuid import UUID, uuid4

import psycopg
from psycopg import sql


class DatabaseFiles:
    """Small private course files; accessed only after API ownership checks.

    Stored outside application tables, with no PUBLIC or educatorApp grants.
    This avoids ephemeral serverless disk and publicly accessible file URLs.
    """
    def __init__(self, dsn):
        self.dsn = dsn

    @staticmethod
    def provision(dsn):
        with psycopg.connect(dsn, connect_timeout=15) as db:
            db.execute('CREATE SCHEMA IF NOT EXISTS "educatorFiles"')
            db.execute('REVOKE ALL ON SCHEMA "educatorFiles" FROM PUBLIC')
            db.execute('CREATE TABLE IF NOT EXISTS "educatorFiles".objects (key text PRIMARY KEY, content bytea NOT NULL, "contentHash" text NOT NULL)')
            db.execute('REVOKE ALL ON "educatorFiles".objects FROM PUBLIC')
            db.execute("""CREATE TABLE IF NOT EXISTS "educatorFiles".uploads (id uuid PRIMARY KEY,"userId" uuid NOT NULL,"courseId" uuid NOT NULL,name text NOT NULL,"byteSize" integer NOT NULL CHECK ("byteSize" BETWEEN 1 AND 10000000),content bytea NOT NULL DEFAULT '',"nextPart" integer NOT NULL DEFAULT 0,"expiresAt" timestamptz NOT NULL DEFAULT now()+interval '30 minutes')""")

    def put(self, key, data):
        digest = hashlib.sha256(data).hexdigest()
        with psycopg.connect(self.dsn, connect_timeout=15) as db:
            existing = db.execute('SELECT "contentHash" FROM "educatorFiles".objects WHERE key=%s', (key,)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ValueError('Storage key conflict')
            else:
                db.execute('INSERT INTO "educatorFiles".objects VALUES (%s,%s,%s)', (key, data, digest))
        return key, digest

    def write(self, category, data, suffix=''):
        return self.put(f'{category}/{uuid4().hex}{suffix}', data)

    def read(self, key):
        with psycopg.connect(self.dsn, connect_timeout=15) as db:
            row = db.execute('SELECT content FROM "educatorFiles".objects WHERE key=%s', (key,)).fetchone()
        if not row:
            raise FileNotFoundError('Private file missing')
        return bytes(row[0])

    def delete(self, key):
        with psycopg.connect(self.dsn, connect_timeout=15) as db:
            db.execute('DELETE FROM "educatorFiles".objects WHERE key=%s', (key,))


def storage(database):
    if os.getenv('FILE_STORAGE') == 'postgres':
        return DatabaseFiles(database.dsn)
    if os.getenv('VERCEL'):
        raise RuntimeError('Vercel requires persistent private file storage')
    from .files import Files
    return Files(os.getenv('PRIVATE_STORAGE_ROOT', 'artifacts/development/files'))


def publish(service, user, run):
    """Called only after the transaction commits; queue contains opaque IDs."""
    if os.getenv('JOB_BACKEND') != 'vercel' or run['status'] != 'queued':
        return run
    from vercel.queue import send
    with service.database.transaction(user) as db:
        attempt = db.execute('SELECT id FROM "runAttempts" WHERE "runId"=%s AND status=\'queued\' ORDER BY "attemptNumber" DESC LIMIT 1', (UUID(run['id']),)).fetchone()
    if not attempt:
        return run
    try:
        asyncio.run(send('educator-jobs', {'run_id': run['id'], 'storage': 'normalized'}, idempotency_key=str(attempt['id'])))
    except Exception:
        with service.database.transaction(user) as db:
            changed = db.execute('UPDATE "runAttempts" SET status=\'failed\',"errorCode"=\'queue_unavailable\',"finishedAt"=now() WHERE id=%s AND status=\'queued\' RETURNING id', (attempt['id'],)).fetchone()
            if changed:
                db.execute('UPDATE runs SET status=\'failed\' WHERE id=%s AND status=\'queued\'', (UUID(run['id']),))
            return service.run(db, UUID(run['id']))
    return run


def consume(ident):
    from apps.database.client import Database
    from .service import Service
    from .worker import process
    database = Database(os.environ['DATABASE_URL'], os.getenv('DATABASE_SCHEMA', 'educator'))
    service = Service(database, storage(database), os.getenv('API_MODE', 'real'), os.getenv('RAG_MODE') == 'hybrid')
    with psycopg.connect(database.dsn, connect_timeout=15) as db:
        row = db.execute(sql.SQL('SELECT "requestedBy" FROM {}.runs WHERE id=%s').format(sql.Identifier(database.schema)), (UUID(ident),)).fetchone()
    if not row:
        return
    user = row[0]
    with database.transaction(user) as db:
        expired = db.execute('UPDATE "runAttempts" SET status=\'failed\',"errorCode"=\'worker_interrupted\',"finishedAt"=now() WHERE "runId"=%s AND status=\'running\' AND "leaseExpiresAt"<now() RETURNING id', (UUID(ident),)).fetchone()
        if expired:
            db.execute('UPDATE runs SET status=\'failed\' WHERE id=%s AND status=\'running\'', (UUID(ident),))
    process(service, user, UUID(ident))
    service.clean_files(user)
