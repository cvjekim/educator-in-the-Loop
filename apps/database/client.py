"""Authenticated transactions for the normalized schema; never use browser-supplied user IDs."""
from contextlib import contextmanager
from uuid import UUID
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from .migrate import validate_schema


class Database:
    def __init__(self, dsn, schema='educator', role='educatorApp'):
        self.dsn, self.schema, self.role = dsn, validate_schema(schema), role

    @contextmanager
    def transaction(self, authenticated_user_id):
        user_id=str(UUID(str(authenticated_user_id)))
        with psycopg.connect(self.dsn,connect_timeout=15,row_factory=dict_row) as db:
            if self.role:
                db.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(self.role)))
            role=db.execute('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            if role['rolsuper'] or role['rolbypassrls']:
                raise PermissionError('Application connections must not bypass row-level security')
            db.execute(sql.SQL('SET LOCAL search_path TO {}, public').format(sql.Identifier(self.schema)))
            db.execute("SELECT set_config('app.userId',%s,true)",(user_id,))
            yield db

    def add_student(self, authenticated_user_id, course_id, student_number, name):
        with self.transaction(authenticated_user_id) as db:
            row=db.execute('INSERT INTO "courseStudents" ("courseId","studentNumber","name") VALUES (%s,%s,%s) RETURNING *',
                (UUID(str(course_id)),student_number.strip(),name.strip())).fetchone()
            row['id']=str(row['id'])
            return row

    def students(self, authenticated_user_id, course_id):
        with self.transaction(authenticated_user_id) as db:
            rows=db.execute('SELECT * FROM "courseStudents" WHERE "courseId"=%s ORDER BY "studentNumber","id"',(UUID(str(course_id)),)).fetchall()
            for row in rows:row['id']=str(row['id'])
            return rows
