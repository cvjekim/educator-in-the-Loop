"""Transactional, checksum-verified schema migrations. Never changes the legacy public tables."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import psycopg
from psycopg import sql

from . import schema_v1

MIGRATIONS = Path(__file__).with_name('migrations')
SCHEMA_DEFAULT = 'educator'


def validate_schema(schema):
    if not re.fullmatch(r'(educator|educatorDev|test_[a-z0-9_]+)', schema):
        raise ValueError('Use the isolated educator schema or a test_ schema')
    return schema


def migration_steps():
    steps=[]
    for path in sorted(MIGRATIONS.glob('*.sql')):
        version=int(path.name.split('_')[0])
        if version==3:raise ValueError('Migration 3 is reserved for initial security policies')
        content=path.read_bytes()
        steps.append((version,hashlib.sha256(content).hexdigest(),content.decode()))
    policy_source=Path(schema_v1.__file__).read_bytes()
    steps.append((3,hashlib.sha256(policy_source).hexdigest(),None))
    if len({step[0] for step in steps})!=len(steps):raise ValueError('Duplicate migration version')
    return sorted(steps)


def apply(dsn, schema=SCHEMA_DEFAULT):
    validate_schema(schema)
    steps=migration_steps()
    with psycopg.connect(dsn,connect_timeout=15) as db:
        db.execute("SET LOCAL lock_timeout = '10s'")
        db.execute("SET LOCAL statement_timeout = '120s'")
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',('educator:migrate:'+schema,))
        db.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(schema)))
        db.execute(sql.SQL('REVOKE ALL ON SCHEMA {} FROM PUBLIC').format(sql.Identifier(schema)))
        db.execute(sql.SQL('SET LOCAL search_path TO {}, public').format(sql.Identifier(schema)))
        db.execute('CREATE TABLE IF NOT EXISTS "schemaMigrations" ("version" integer PRIMARY KEY, "checksum" text NOT NULL, "appliedAt" timestamptz NOT NULL DEFAULT now())')
        applied=dict(db.execute('SELECT "version","checksum" FROM "schemaMigrations"').fetchall())
        if set(applied)-{s[0] for s in steps}:raise ValueError('Database contains unknown newer migrations')
        if applied and sorted(applied)!=[s[0] for s in steps[:len(applied)]]:raise ValueError('Migration history has a gap')
        if not applied:
            objects=db.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema=%s AND table_name<>%s',(schema,'schemaMigrations')).fetchone()[0]
            if objects:raise ValueError('Target schema is not empty; refusing to overwrite existing objects')
        changed=[]
        for version,checksum,source in steps:
            if version in applied:
                if applied[version]!=checksum:raise ValueError('Applied migration checksum differs; add a new migration')
                continue
            if version==1:db.execute('CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public')
            if source is None:
                schema_v1.install_policies_and_triggers(db,schema)
            else:
                db.execute(source.replace('"__schema__"',sql.Identifier(schema).as_string(db)))
            db.execute('INSERT INTO "schemaMigrations" ("version","checksum") VALUES (%s,%s)',(version,checksum))
            changed.append(version)
        count=db.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema=%s',(schema,)).fetchone()[0]
        return {'schema':schema,'version':steps[-1][0],'applied':bool(changed),'appliedVersions':changed,'tableCount':count}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schema',default=SCHEMA_DEFAULT)
    args=parser.parse_args()
    dsn=os.getenv('DATABASE_URL_UNPOOLED') or os.getenv('DATABASE_URL')
    if not dsn:parser.error('Set DATABASE_URL_UNPOOLED or DATABASE_URL (do not pass secrets on the command line)')
    try:print(json.dumps(apply(dsn,args.schema)))
    except Exception as exc:
        # PostgreSQL details can include private values. Detailed diagnosis stays in private tooling.
        print(json.dumps({'error':type(exc).__name__,'sqlState':getattr(exc,'sqlstate',None)}))
        raise SystemExit(1) from None


if __name__=='__main__':main()
