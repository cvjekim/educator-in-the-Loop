"""Real PostgreSQL constraints/RLS tests in a disposable, uniquely named schema."""
import os
from uuid import uuid4
import pytest
import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb
from apps.database.migrate import apply

HASH='a'*64

@pytest.fixture(scope='module')
def database():
    dsn=os.getenv('TEST_DATABASE_URL')
    if not dsn:pytest.skip('TEST_DATABASE_URL required; use PostgreSQL with pgvector available')
    schema='test_schema_'+uuid4().hex
    role='test_role_'+uuid4().hex
    result=apply(dsn,schema)
    assert result['applied']
    assert not apply(dsn,schema)['applied']
    with psycopg.connect(dsn,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS').format(sql.Identifier(role)))
        # Current migration role can SET ROLE; no login/password or public schema rights are granted.
        admin.execute(sql.SQL('GRANT {} TO {}').format(sql.Identifier(role),sql.Identifier(admin.info.user)))
        admin.execute(sql.SQL('GRANT USAGE ON SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(role)))
        for kind in ['TABLES','SEQUENCES','FUNCTIONS']:
            admin.execute(sql.SQL('GRANT ALL ON ALL '+kind+' IN SCHEMA {} TO {}').format(sql.Identifier(schema),sql.Identifier(role)))
    try:yield dsn,schema,role
    finally:
        with psycopg.connect(dsn,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))

@pytest.fixture
def db(database):
    dsn,schema,role=database
    with psycopg.connect(dsn) as c:
        c.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
        c.execute(sql.SQL('SET LOCAL search_path TO {}, public').format(sql.Identifier(schema)))
        try:yield c
        finally:c.rollback()

def as_user(db,user):
    db.execute("SELECT set_config('app.userId',%s,true)",(str(user),))

def insert(db,table,**values):
    cols=list(values)
    return db.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING *').format(
        sql.Identifier(table),sql.SQL(',').join(map(sql.Identifier,cols)),sql.SQL(',').join(sql.Placeholder() for _ in cols)),list(values.values())).fetchone()[0]

def user(db):
    ident=uuid4();as_user(db,ident)
    insert(db,'users',id=ident,name='Synthetic',department='Synthetic department')
    return ident

def course(db,owner):return insert(db,'courses',ownerId=owner,title='Synthetic course')

def run(db,owner,c,kind='lecture'):
    r=insert(db,'runs',courseId=c,requestedBy=owner,taskType=kind,topic='Synthetic topic',idempotencyKey=str(uuid4()),requestHash=HASH)
    insert(db,'runInputs',runId=r)
    return r

def document(db,owner,c):
    d=insert(db,'documents',ownerId=owner,title='Synthetic source')
    v=insert(db,'documentVersions',documentId=d,versionNumber=1,originalFileName='source.txt',storageKey='documents/'+str(uuid4()),mimeType='text/plain',byteSize=12,contentHash=HASH)
    db.execute('UPDATE "documents" SET "currentVersionId"=%s WHERE id=%s',(v,d))
    insert(db,'courseDocuments',courseId=c,documentId=d)
    i=insert(db,'documentIndexes',documentVersionId=v,status='ready',parserVersion='synthetic',chunkingConfig=Jsonb({}))
    ch=insert(db,'documentChunks',documentIndexId=i,chunkNumber=0,pageNumber=1,text='synthetic',textHash=HASH)
    return d,v,i,ch

def evaluated(db,owner,c):
    student=insert(db,'courseStudents',courseId=c,studentNumber='00123',name='Synthetic student')
    rubric=insert(db,'rubricDocuments',courseId=c,title='Synthetic rubric')
    version=insert(db,'rubricVersions',rubricDocumentId=rubric,versionNumber=1,origin='professor',storageKey='rubrics/'+str(uuid4())+'.md',contentHash=HASH)
    r=run(db,owner,c,'project')
    insert(db,'evaluationRuns',runId=r,courseStudentId=student,rubricVersionId=version,repositoryUrl='https://github.com/example/synthetic',commitSha='a'*40)
    insert(db,'evaluationDrafts',runId=r,versionNumber=1,storageKey='evaluations/'+str(uuid4())+'.md',fileName='draft.md',contentHash=HASH)
    return student,rubric,version,r

def rejected(db,callback,error=psycopg.IntegrityError):
    with pytest.raises(error):
        with db.transaction():callback()

def test_student_defaults_identity_and_unique_course(db):
    u=user(db);c=course(db,u)
    a=insert(db,'courseStudents',courseId=c,studentNumber='001',name='One')
    b=insert(db,'courseStudents',courseId=c,studentNumber='002',name='Two')
    assert b>a
    assert db.execute('SELECT "studentNumber","githubId","repositoryUrl" FROM "courseStudents" WHERE id=%s',(a,)).fetchone()==('001',None,None)
    rejected(db,lambda:insert(db,'courseStudents',courseId=c,studentNumber='001',name='Duplicate'))
    c2=course(db,u)
    insert(db,'courseStudents',courseId=c2,studentNumber='001',name='One')
    rejected(db,lambda:insert(db,'courseStudents',id=999,courseId=c,studentNumber='003',name='Forced'),psycopg.DatabaseError)

def test_rls_denies_other_owner_reads_writes_and_links(db):
    a=user(db);ca=course(db,a);d,*_=document(db,a,ca)
    b=user(db);cb=course(db,b)
    assert db.execute('SELECT id FROM "courses"').fetchall()==[(cb,)]
    rejected(db,lambda:insert(db,'courseStudents',courseId=ca,studentNumber='01',name='Forbidden'),psycopg.DatabaseError)
    rejected(db,lambda:insert(db,'courseDocuments',courseId=cb,documentId=d))
    assert db.execute('DELETE FROM "courses" WHERE id=%s RETURNING id',(ca,)).fetchall()==[]
    as_user(db,'')
    assert db.execute('SELECT id FROM "courses"').fetchall()==[]

def test_google_only_identity_unique_and_hash_sessions(db):
    u=user(db)
    insert(db,'oauthAccounts',userId=u,subject='synthetic-google-subject')
    rejected(db,lambda:insert(db,'oauthAccounts',userId=u,subject='another',provider='github'))
    rejected(db,lambda:insert(db,'sessions',userId=u,sessionTokenHash='plaintext',expiresAt='2099-01-01'))
    b=user(db)
    rejected(db,lambda:insert(db,'oauthAccounts',userId=b,subject='synthetic-google-subject'))

def test_document_reuse_and_version_pointer_scope(db):
    u=user(db);c=course(db,u);d,v,i,ch=document(db,u,c);c2=course(db,u)
    insert(db,'courseDocuments',courseId=c2,documentId=d)
    d2=insert(db,'documents',ownerId=u,title='Other')
    def wrong_pointer():
        db.execute('UPDATE "documents" SET "currentVersionId"=%s WHERE id=%s',(v,d2))
        db.execute('SET CONSTRAINTS ALL IMMEDIATE')
    rejected(db,wrong_pointer)
    rejected(db,lambda:db.execute('UPDATE "documentVersions" SET "storageKey"=%s WHERE id=%s',('documents/replaced',v)))
    db.execute('DELETE FROM "courseDocuments" WHERE "courseId"=%s AND "documentId"=%s',(c2,d))
    assert db.execute('SELECT id FROM "documentVersions" WHERE id=%s',(v,)).fetchone()

def test_generated_file_requires_matching_approval(db):
    u=user(db);c=course(db,u);r=run(db,u,c)
    rev=insert(db,'runRevisions',runId=r,revisionNumber=1,origin='ai',content=Jsonb({'text':'Synthetic'}))
    review=insert(db,'reviews',revisionId=rev,reviewerId=u,decision='revise',feedback='Improve')
    material=insert(db,'generatedMaterials',courseId=c,title='Lecture',materialType='lectureNote')
    rejected(db,lambda:insert(db,'generatedMaterialVersions',generatedMaterialId=material,versionNumber=1,runRevisionId=rev,approvalReviewId=review))
    approval=insert(db,'reviews',revisionId=rev,reviewerId=u,decision='approve')
    mv=insert(db,'generatedMaterialVersions',generatedMaterialId=material,versionNumber=1,runRevisionId=rev,approvalReviewId=approval)
    insert(db,'artifacts',generatedMaterialVersionId=mv,fileRole='main',format='md',storageKey='artifacts/'+str(uuid4()),byteSize=12,contentHash=HASH)
    c2=course(db,u);m2=insert(db,'generatedMaterials',courseId=c2,title='Other',materialType='lectureNote')
    rejected(db,lambda:insert(db,'generatedMaterialVersions',generatedMaterialId=m2,versionNumber=1,runRevisionId=rev,approvalReviewId=approval))

def test_project_uses_md_without_score_or_json_body(db):
    u=user(db);c=course(db,u);student,rubric,version,r=evaluated(db,u,c)
    rejected(db,lambda:insert(db,'runRevisions',runId=r,revisionNumber=1,origin='ai',content=Jsonb({'score':90})))
    rejected(db,lambda:insert(db,'evaluationDrafts',runId=r,versionNumber=2,storageKey='evaluations/bad.json',fileName='bad.json',contentHash=HASH))
    c2=course(db,u);s2=insert(db,'courseStudents',courseId=c2,studentNumber='001',name='Other')
    r2=run(db,u,c,'project')
    rejected(db,lambda:insert(db,'evaluationRuns',runId=r2,courseStudentId=s2,rubricVersionId=version,repositoryUrl='https://github.com/example/synthetic'))
    db.execute('DELETE FROM "runs" WHERE id=%s',(r2,))
    db.execute('SET CONSTRAINTS ALL IMMEDIATE')

@pytest.mark.parametrize('target',['courseStudents','rubricDocuments'])
def test_student_or_rubric_delete_removes_evaluation_and_queues_files(db,target):
    u=user(db);c=course(db,u);student,rubric,version,r=evaluated(db,u,c)
    db.execute(sql.SQL('DELETE FROM {} WHERE id=%s').format(sql.Identifier(target)),(student if target=='courseStudents' else rubric,))
    assert not db.execute('SELECT id FROM "runs" WHERE id=%s',(r,)).fetchone()
    assert not db.execute('SELECT id FROM "evaluationDrafts" WHERE "runId"=%s',(r,)).fetchone()
    assert db.execute("SELECT count(*) FROM \"deletionJobs\" WHERE \"targetType\"='evaluationDrafts'").fetchone()[0]==1
    db.execute('SET CONSTRAINTS ALL IMMEDIATE')

def test_document_delete_removes_related_results_across_courses(db):
    u=user(db);c=course(db,u);d,v,i,ch=document(db,u,c)
    other=run(db,u,c)
    for n in range(2):
        cx=c if n==0 else course(db,u)
        if n:insert(db,'courseDocuments',courseId=cx,documentId=d)
        r=run(db,u,cx);insert(db,'runDocuments',runId=r,documentVersionId=v,documentIndexId=i)
        rev=insert(db,'runRevisions',runId=r,revisionNumber=1,origin='ai',content=Jsonb({'text':'Synthetic'}))
        insert(db,'revisionSources',revisionId=rev,chunkId=ch,rank=1)
        approval=insert(db,'reviews',revisionId=rev,reviewerId=u,decision='approve')
        m=insert(db,'generatedMaterials',courseId=cx,title='Synthetic',materialType='lectureNote')
        mv=insert(db,'generatedMaterialVersions',generatedMaterialId=m,versionNumber=1,runRevisionId=rev,approvalReviewId=approval)
        db.execute('UPDATE "generatedMaterials" SET "currentVersionId"=%s WHERE id=%s',(mv,m))
        insert(db,'artifacts',generatedMaterialVersionId=mv,fileRole='main',format='md',storageKey='artifacts/'+str(uuid4()),byteSize=12,contentHash=HASH)
    db.execute('DELETE FROM "documents" WHERE id=%s',(d,))
    assert db.execute('SELECT id FROM "runs"').fetchall()==[(other,)]
    assert db.execute('SELECT count(*) FROM "artifacts"').fetchone()[0]==0
    assert db.execute('SELECT count(*) FROM "deletionJobs"').fetchone()[0]==3
    db.execute('SET CONSTRAINTS ALL IMMEDIATE')

def test_course_delete_preserves_personal_library(db):
    u=user(db);c=course(db,u);d,v,i,ch=document(db,u,c);evaluated(db,u,c)
    db.execute('DELETE FROM "courses" WHERE id=%s',(c,))
    assert db.execute('SELECT id FROM "documents" WHERE id=%s',(d,)).fetchone()
    assert not db.execute('SELECT id FROM "runs"').fetchall()
    db.execute('SET CONSTRAINTS ALL IMMEDIATE')

def test_missing_inputs_rejected_at_commit(db):
    u=user(db);c=course(db,u)
    def missing():
        insert(db,'runs',courseId=c,requestedBy=u,taskType='lecture',topic='Synthetic',idempotencyKey=str(uuid4()),requestHash=HASH)
        db.execute('SET CONSTRAINTS ALL IMMEDIATE')
    rejected(db,missing)


def test_runtime_provisioning_and_client_bigint_identity(database):
    from apps.database.provision import provision_runtime
    from apps.database.client import Database
    dsn,schema,role=database
    assert provision_runtime(dsn,schema,role)['runtimeRole']==role
    runtime=Database(dsn,schema,role)
    uid=uuid4()
    try:
        with runtime.transaction(uid) as c:
            c.execute('INSERT INTO "users" (id,name,department) VALUES (%s,%s,%s)',(uid,'Synthetic client','Synthetic'))
            cid=c.execute('INSERT INTO "courses" ("ownerId",title) VALUES (%s,%s) RETURNING id',(uid,'Synthetic')).fetchone()['id']
        student=runtime.add_student(uid,cid,'00001','Synthetic student')
        assert isinstance(student['id'],str) and student['githubId'] is None and student['repositoryUrl'] is None
        assert runtime.students(uid,cid)[0]['studentNumber']=='00001'
        assert runtime.students(uuid4(),cid)==[]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with runtime.transaction(uid) as c:
                c.execute('UPDATE "users" SET role=%s WHERE id=%s',('admin',uid))
    finally:
        with runtime.transaction(uid) as c:c.execute('DELETE FROM "users" WHERE id=%s',(uid,))


def test_rollback_also_rolls_back_deletion_jobs(db):
    u=user(db);c=course(db,u);d,v,i,ch=document(db,u,c)
    with pytest.raises(RuntimeError):
        with db.transaction():
            db.execute('DELETE FROM "documents" WHERE id=%s',(d,))
            assert db.execute('SELECT count(*) FROM "deletionJobs"').fetchone()[0]==1
            raise RuntimeError('synthetic rollback')
    assert db.execute('SELECT id FROM "documents" WHERE id=%s',(d,)).fetchone()
    assert db.execute('SELECT count(*) FROM "deletionJobs"').fetchone()[0]==0


def test_migrations_reject_edits_and_rollback_failed_upgrade(database,monkeypatch):
    from apps.database import migrate
    dsn,schema,_=database
    original=migrate.migration_steps()
    modified=[(n,'invalid' if n==1 else digest,source) for n,digest,source in original]
    monkeypatch.setattr(migrate,'migration_steps',lambda:modified)
    with pytest.raises(ValueError,match='checksum'):migrate.apply(dsn,schema)
    monkeypatch.setattr(migrate,'migration_steps',lambda:original+[(original[-1][0]+1,'synthetic','CREATE TABLE "failedUpgrade" (id integer); SELECT 1/0;')])
    with pytest.raises(psycopg.errors.DivisionByZero):migrate.apply(dsn,schema)
    with psycopg.connect(dsn) as c:
        assert c.execute('SELECT count(*) FROM information_schema.tables WHERE table_schema=%s AND table_name=%s',(schema,'failedUpgrade')).fetchone()[0]==0
        assert c.execute(sql.SQL('SELECT max(version) FROM {}."schemaMigrations"').format(sql.Identifier(schema))).fetchone()[0]==original[-1][0]
