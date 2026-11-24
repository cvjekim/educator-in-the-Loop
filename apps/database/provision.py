"""Provision a non-login runtime role; the backend uses SET LOCAL ROLE per transaction."""
import re
import psycopg
from psycopg import sql
from .migrate import validate_schema


def provision_runtime(dsn, schema='educator', role='educatorApp'):
    validate_schema(schema)
    if not re.fullmatch(r'(educatorApp|test_[a-z0-9_]+)',role):raise ValueError('Invalid runtime role')
    ident=sql.Identifier
    with psycopg.connect(dsn,connect_timeout=15) as db:
        db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',('educator:runtime:'+role,))
        existing=db.execute('SELECT rolsuper,rolbypassrls,rolcanlogin,rolcreaterole,rolcreatedb FROM pg_roles WHERE rolname=%s',(role,)).fetchone()
        if existing:
            if any(existing):raise ValueError('Existing runtime role has unsafe privileges')
        else:
            db.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS').format(ident(role)))
        db.execute(sql.SQL('GRANT {} TO {}').format(ident(role),ident(db.info.user)))
        db.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(ident(schema),ident(role)))
        tables=db.execute('SELECT table_name FROM information_schema.tables WHERE table_schema=%s AND table_name<>%s',(schema,'schemaMigrations')).fetchall()
        for (table,) in tables:
            db.execute(sql.SQL('GRANT SELECT, INSERT, UPDATE, DELETE ON {}.{} TO {}').format(ident(schema),ident(table),ident(role)))
        db.execute(sql.SQL('REVOKE INSERT, UPDATE ON {}."users" FROM {}').format(ident(schema),ident(role)))
        db.execute(sql.SQL('GRANT INSERT ("id","name","department"), UPDATE ("name","department","updatedAt") ON {}."users" TO {}').format(ident(schema),ident(role)))
        db.execute(sql.SQL('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}').format(ident(schema),ident(role)))
        db.execute(sql.SQL('GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {} TO {}').format(ident(schema),ident(role)))
        return {'schema':schema,'runtimeRole':role,'tableCount':len(tables)}
