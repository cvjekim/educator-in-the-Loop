"""Real local PostgreSQL/API integration; only Google verification and model output are synthetic."""
import os
from pathlib import Path
from uuid import uuid4,UUID
import pytest
import psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from apps.database.migrate import apply
from apps.database.provision import provision_runtime
from apps.database.client import Database
from apps.api.normalized.app import create_app
from apps.api.normalized.files import Files
from apps.api.normalized.worker import process
from apps.api.legacy_runner import demo

@pytest.fixture(scope='module')
def environment(tmp_path_factory):
    dsn=os.getenv('TEST_DATABASE_URL')
    if not dsn:pytest.skip('Set TEST_DATABASE_URL to local PostgreSQL with pgvector')
    from urllib.parse import urlparse
    assert urlparse(dsn).hostname in ('127.0.0.1','localhost','::1'),'Tests use a local DB only'
    schema='test_proto_'+uuid4().hex;role='test_role_'+uuid4().hex
    apply(dsn,schema);provision_runtime(dsn,schema,role)
    database=Database(dsn,schema,role)
    app=create_app(database,Files(tmp_path_factory.mktemp('files')),mode='demo')
    try:yield app,database
    finally:
        with psycopg.connect(dsn,autocommit=True) as db:
            db.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
            db.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))

@pytest.fixture
def client(environment,monkeypatch):
    from apps.api import accounts
    monkeypatch.setenv('GOOGLE_CLIENT_ID','synthetic-client')
    monkeypatch.setattr(accounts,'verify_google',lambda credential,nonce,client_id:credential)
    return TestClient(environment[0])

def login(client):
    credentials={'credential':uuid4().hex,'nonce':'n'*32}
    assert client.post('/v1/auth/google',json=credentials).json()['needsRegistration']
    result=client.post('/v1/auth/google',json={**credentials,'profile':{'name':'Synthetic','department':'Teaching'}})
    assert result.status_code==200,result.text
    return {'Authorization':'Bearer '+result.json()['sessionToken']},UUID(result.json()['profile']['id'])

def add_course(client,h):
    response=client.post('/v1/courses',headers=h,json={'title':'Synthetic course'})
    assert response.status_code==201,response.text
    return response.json()['id']

def upload(client,h,c,name,text):
    r=client.post(f'/v1/courses/{c}/documents',headers=h,files={'file':(name,text.encode(),'text/plain')})
    assert r.status_code==201,r.text
    return r.json()

def setup_course(client,h):
    c=add_course(client,h)
    syllabus=upload(client,h,c,'plan.md','# Course goals\nUnderstand supervised learning and regression\n1주차 Classification\n2주차 Regression\n3주차 Clustering')
    weeks=[{'weekNumber':i,'topic':topic,'objectives':'Understand '+topic} for i,topic in enumerate(['Classification','Regression','Clustering'],1)]
    p=client.put(f'/v1/courses/{c}/plan',headers=h,json={'syllabusVersionId':syllabus['currentVersionId'],'goals':'Understand supervised learning and regression','weeks':weeks})
    assert p.status_code==200,p.text
    docs=[]
    for w in weeks:
        d=upload(client,h,c,f"week-{w['weekNumber']}.md",w['topic']+' synthetic lecture material evidence')
        assert client.put(f"/v1/courses/{c}/documents/{d['id']}/weeks",headers=h,json={'weekNumbers':[w['weekNumber']]}).status_code==200
        docs.append(d)
    return c,syllabus,docs

def generate(client,h,c,kind,weeks,docs,**extra):
    return client.post(f'/v1/courses/{c}/runs',headers={**h,'Idempotency-Key':uuid4().hex},json={'taskType':kind,'topic':'Classification Regression','weekNumbers':weeks,'documentIds':[d['id'] for d in docs],**extra})


def test_course_plan_scope_and_isolation(client,environment):
    h,user=login(client);other,_=login(client);c,syllabus,docs=setup_course(client,h)
    assert client.get('/v1/courses',headers=other).json()==[]
    for path in [f'/v1/courses/{c}/plan',f'/v1/courses/{c}/documents',f"/v1/documents/{docs[0]['id']}/file"]:
        assert client.get(path,headers=other).status_code==404
    assert client.post(f'/v1/courses/{c}/search',headers=other,json={'query':'Classification'}).status_code==404
    assert client.delete(f"/v1/documents/{docs[0]['id']}",headers=other).status_code==404
    assert generate(client,h,c,'exam',[],docs[:1]).status_code==422
    assert generate(client,h,c,'exam',[1,2],docs[:1]).status_code==422
    assert generate(client,h,c,'exam',[1,2],[docs[2]]).status_code==422
    assert generate(client,h,c,'lecture',[1,2],docs[:2]).status_code==422
    assert generate(client,h,c,'lecture',[99],docs[:1]).status_code==422
    preview=client.get(f"/v1/documents/{syllabus['id']}/syllabus-preview",headers=h).json()
    assert len(preview['suggestedWeeks'])==3
    result=generate(client,h,c,'exam',[1,2],docs[:2]);assert result.status_code==202,result.text
    rid=result.json()['id'];service=environment[0].state.service
    seen=[]
    def runner(data):seen.append(data);return demo(data)
    assert process(service,user,UUID(rid),runner)
    draft=client.get(f'/v1/runs/{rid}',headers=h).json()
    assert draft['status']=='waitingReview'
    assert {x['documentId'] for x in draft['citations']}=={docs[0]['id'],docs[1]['id']}
    assert 'Clustering synthetic' not in seen[0]['raw_context']
    assert client.get(f'/v1/runs/{rid}/artifact',headers=h).status_code==409
    assert client.post(f'/v1/runs/{rid}/reviews',headers=other,json={'expectedRevision':1,'decision':'approve'}).status_code==404
    approved=client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':1,'decision':'approve'})
    assert approved.status_code==200,approved.text
    assert client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':1,'decision':'approve'}).status_code==409
    assert process(service,user,UUID(rid),runner)
    assert client.get(f'/v1/runs/{rid}',headers=h).json()['status']=='succeeded'
    assert client.get(f'/v1/runs/{rid}/artifact',headers=h).status_code==200
    assert len(client.get(f'/v1/courses/{c}/rubrics',headers=h).json())==1
    assert len(client.get(f'/v1/courses/{c}/materials',headers=h).json())==1
    # Two-course source reuse keeps personal files on course deletion; original deletion removes dependent results.
    c2=add_course(client,h)
    assert client.post(f'/v1/courses/{c2}/document-links',headers=h,json={'documentId':docs[0]['id']}).status_code==201
    assert client.delete(f'/v1/courses/{c2}',headers=h).status_code==204
    assert client.get(f"/v1/documents/{docs[0]['id']}/file",headers=h).status_code==200
    assert client.delete(f"/v1/documents/{docs[0]['id']}",headers=h).status_code==204
    assert client.get(f'/v1/runs/{rid}',headers=h).status_code==404
    assert client.post(f'/v1/courses/{c}/search',headers=h,json={'query':'Classification','documentIds':[docs[0]['id']]}).status_code==404


def test_lecture_plan_snapshot_review_edit_and_reuse(client,environment):
    h,user=login(client);c,syllabus,docs=setup_course(client,h)
    response=generate(client,h,c,'lecture',[1],docs[:1],guidelines='Use examples for beginners')
    assert response.status_code==202,response.text
    rid=response.json()['id'];service=environment[0].state.service;seen=[]
    def runner(data):seen.append(data);return demo(data)
    # Later plan edits cannot rewrite the context of a queued run.
    assert client.put(f'/v1/courses/{c}/plan',headers=h,json={'syllabusVersionId':None,'weeks':[{'weekNumber':1,'topic':'Changed topic'}]}).status_code==200
    process(service,user,UUID(rid),runner)
    assert 'Understand supervised learning' in seen[0]['syllabus_context']
    assert 'Changed topic' not in seen[0]['syllabus_context']
    draft=client.get(f'/v1/runs/{rid}',headers=h).json()
    edit=client.patch(f'/v1/runs/{rid}/draft',headers=h,json={'expectedRevision':1,'draft':{**draft['draft'],'main_slides':['Reviewed']}})
    assert edit.status_code==200 and edit.json()['revision']==2,edit.text
    assert client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':1,'decision':'approve'}).status_code==409
    assert client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':2,'decision':'revise','feedback':'Add examples'}).status_code==200
    process(service,user,UUID(rid),runner)
    assert 'Add examples' in seen[-1]['request']['guidelines']
    assert client.get(f'/v1/runs/{rid}',headers=h).json()['revision']==3


def test_students_rubric_and_md_only_evaluation(client,environment):
    h,user=login(client);c=add_course(client,h)
    s=client.post(f'/v1/courses/{c}/students',headers=h,json={'studentNumber':'00123','name':'Synthetic student'})
    assert s.status_code==201,s.text
    student=s.json();assert student['githubId'] is None and student['repositoryUrl'] is None and isinstance(student['id'],str)
    student_input={'studentNumber':'00123','name':'Synthetic student','repositoryUrl':'https://github.com/example/synthetic'}
    assert client.put(f"/v1/students/{student['id']}",headers=h,json=student_input).status_code==200
    rubric=client.post(f'/v1/courses/{c}/rubrics',headers=h,json={'title':'Reference rubric','markdown':'# Rubric\nAssess reasoning, no scores'}).json()
    response=generate(client,h,c,'project',[],[],courseStudentId=int(student['id']),rubricVersionId=rubric['currentVersionId'])
    assert response.status_code==202,response.text
    rid=response.json()['id'];service=environment[0].state.service
    process(service,user,UUID(rid),demo)
    assert client.get(f'/v1/runs/{rid}',headers=h).json()['status']=='succeeded'
    assert client.get(f'/v1/runs/{rid}/artifact',headers=h).status_code==200
    with environment[1].transaction(user) as db:
        assert db.execute('SELECT count(*) AS n FROM "runRevisions" WHERE "runId"=%s',(rid,)).fetchone()['n']==0
        assert db.execute('SELECT "taskConfig" FROM "runInputs" WHERE "runId"=%s',(rid,)).fetchone()['taskConfig']=={}
    assert client.delete(f"/v1/students/{student['id']}",headers=h).status_code==204
    assert client.get(f'/v1/runs/{rid}',headers=h).status_code==404


def test_practice_manager_and_cancel_restart(client,environment):
    import json
    h,user=login(client);c,syllabus,docs=setup_course(client,h);service=environment[0].state.service
    notebook=upload(client,h,c,'practice.ipynb',json.dumps({'nbformat':4,'nbformat_minor':5,'metadata':{},'cells':[{'id':'synthetic','cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':'print(1)'}]}))
    response=generate(client,h,c,'practice',[1],[notebook]);assert response.status_code==202,response.text
    rid=UUID(response.json()['id']);process(service,user,rid,demo)
    assert client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':1,'decision':'approve'}).status_code==200
    process(service,user,rid,demo)
    download=client.get(f'/v1/runs/{rid}/artifact',headers=h)
    assert json.loads(download.content)['nbformat']==4
    assert f'{c}_week01_practice_v1_' in download.headers['content-disposition']
    assert client.get(f'/v1/runs/{rid}',headers=h).json()['downloadFileName'] in download.headers['content-disposition']
    response=generate(client,h,c,'manager',[1],[]);assert response.status_code==202,response.text
    rid=UUID(response.json()['id']);process(service,user,rid,demo)
    assert client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':1,'decision':'approve'}).status_code==200
    process(service,user,rid,demo)
    dispatched=client.post(f'/v1/runs/{rid}/dispatches',headers=h);assert dispatched.status_code==200,dispatched.text
    child=dispatched.json()[0]['id']
    assert client.post(f'/v1/runs/{child}/cancellations',headers=h).json()['status']=='cancelled'
    assert client.get(f'/v1/courses/{c}/runs',headers=h).status_code==200
    assert child not in [r['id'] for r in client.get(f'/v1/courses/{c}/runs',headers=h).json()]
    assert client.post(f'/v1/runs/{child}/cancellations',headers=h).json()['deleteYn'] is True
    assert not process(service,user,UUID(child),demo)
    # New service/connection sees the same durable record.
    with environment[1].transaction(user) as db:assert service.run(db,UUID(child))['status']=='cancelled'


def test_normalized_stream_uses_notifications_without_idle_queries(client,environment):
    import asyncio
    from apps.api.events import stream
    h,user=login(client);c=UUID(add_course(client,h));service=environment[0].state.service;reads=[]
    def snapshot():
        reads.append(1)
        with environment[1].transaction(user) as db:return [{'title':db.execute('SELECT title FROM courses WHERE id=%s',(c,)).fetchone()['title']}]
    async def exercise():
        generator=stream(service,str(c),snapshot,heartbeat=.05,duration=2)
        try:
            assert 'runs.snapshot' in await anext(generator)
            assert await anext(generator)==': keepalive\n\n'
            assert len(reads)==1
            with environment[1].transaction(user) as db:db.execute('UPDATE courses SET title=\'Updated synthetic title\' WHERE id=%s',(c,))
            assert 'Updated synthetic title' in await asyncio.wait_for(anext(generator),1)
            assert len(reads)==2
        finally:await generator.aclose()
    asyncio.run(exercise())


def test_plan_delete_and_reuse_keep_source_versions(client,environment):
    h,user=login(client);c,syllabus,docs=setup_course(client,h)
    created=generate(client,h,c,'lecture',[1],docs[:1]).json()['id']
    # Unlinking a course source must not remove the personal document or historical run.
    assert client.delete(f"/v1/courses/{c}/documents/{docs[0]['id']}",headers=h).status_code==204
    assert client.get(f'/v1/runs/{created}',headers=h).status_code==200
    assert client.get(f"/v1/documents/{docs[0]['id']}/file",headers=h).status_code==200
    # Deleting the original syllabus removes dependent jobs, and clears the course pointer.
    assert client.delete(f"/v1/documents/{syllabus['id']}",headers=h).status_code==204
    assert client.get(f'/v1/runs/{created}',headers=h).status_code==404
    assert client.get(f'/v1/courses/{c}/plan',headers=h).json()['syllabusVersionId'] is None


def legacy_fixture(tmp_path):
    import hashlib
    cid,did,rid=map(str,(uuid4(),uuid4(),uuid4()))
    text='Synthetic lecture evidence';path=tmp_path/'source.md';path.write_text(text)
    timestamp='2026-01-01T00:00:00+00:00'
    data={'courses':[{'id':cid,'owner':'legacy','payload':{'title':'Imported course','syllabus':'Goals\n1주차: Topic\nLearn the topic\n2주차: Next topic','created_at':timestamp}}],
          'documents':[{'id':did,'owner':'legacy','course_id':cid,'payload':{'filename':path.name,'size':len(text.encode())},'content':{'chunks':[{'chunk_id':'originalChunk','page':1,'text':text+'\x00','embedding':[0.01]*256}]}}],
          'runs':[{'id':rid,'owner':'legacy','course_id':cid,'request_hash':hashlib.sha256(b'request').hexdigest(),
                   'payload':{'task_type':'lecture','topic':'Topic','status':'waiting_review','revision':1,'mode':'real','draft':{'intro_slide':'Intro','main_slides':['Body']},'reviews':[],'output':None,'created_at':timestamp,
                              'citations':[{'document_id':did,'chunk_id':'originalChunk'}]},
                   'state':{'syllabus':'Original syllabus','request':{'week':1,'guidelines':'Original direction','document_ids':[did],'rubric_guidelines':'# Rubric\nExplain the reasoning'}}}], 'feedback':[]}
    return data,{did:str(path)}


def test_legacy_import_preserves_scope_sources_and_is_idempotent(client,environment,tmp_path):
    from scripts.import_legacy_samples import import_snapshot
    h,user=login(client);other,_=login(client);app,database=environment
    data,originals=legacy_fixture(tmp_path);files=app.state.service.files
    assert import_snapshot(database,files,data,originals,user,'legacy')['status']=='validated'
    assert client.get('/v1/courses',headers=h).json()==[]
    assert import_snapshot(database,files,data,originals,user,'legacy',True)['status']=='imported'
    assert import_snapshot(database,files,data,originals,user,'legacy',True)['status']=='alreadyImported'
    cid=data['courses'][0]['id'];rid=data['runs'][0]['id'];did=data['documents'][0]['id']
    assert len(client.get('/v1/courses',headers=h).json())==1
    assert client.get('/v1/courses',headers=other).json()==[]
    assert client.get(f'/v1/runs/{rid}',headers=other).status_code==404
    plan=client.get(f'/v1/courses/{cid}/plan',headers=h).json()
    assert len(plan['weeks'])==2 and plan['syllabusVersionId']
    run=client.get(f'/v1/runs/{rid}',headers=h).json()
    assert run['status']=='waitingReview' and run['draft']==data['runs'][0]['payload']['draft']
    assert run['citations'][0]['text']=='Synthetic lecture evidence'
    assert client.get(f'/v1/documents/{did}/file',headers=h).content==Path(originals[did]).read_bytes()
    rubrics=client.get(f'/v1/courses/{cid}/rubrics',headers=h).json()
    assert client.get('/v1/rubrics/'+rubrics[0]['id'],headers=h).json()['markdown']=='# Rubric\nExplain the reasoning'
    with database.transaction(user) as db:
        assert db.execute('SELECT count(*) AS n FROM "runAttempts" WHERE "runId"=%s',(UUID(rid),)).fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM "generatedMaterials" WHERE "courseId"=%s',(UUID(cid),)).fetchone()['n']==0


def test_legacy_import_rolls_back_rows_and_private_files(client,environment,tmp_path):
    from scripts.import_legacy_samples import import_snapshot
    h,user=login(client);app,database=environment;files=app.state.service.files
    data,originals=legacy_fixture(tmp_path)
    data['runs'][0]['payload']['citations'][0]['chunk_id']='missing'
    before={p for p in files.root.rglob('*') if p.is_file()}
    with pytest.raises(KeyError):import_snapshot(database,files,data,originals,user,'legacy',True)
    assert client.get('/v1/courses',headers=h).json()==[]
    assert {p for p in files.root.rglob('*') if p.is_file()}==before


@pytest.mark.parametrize('suffix',['md','txt'])
def test_structured_plan_import_edit_and_snapshot(client,environment,monkeypatch,suffix):
    h,user=login(client);other,_=login(client);c=add_course(client,h)
    text='# 강의 목표\n1) 원리 이해\n2) 실습 적용\n## 주교재\nCore Book\n## 부교재\nReference\n## 주차별 계획\n| 1 | 분류 | 분류 개념과 예제 |\n2주차: 회귀\n회귀 모델 학습'
    doc=upload(client,h,c,'syllabus.'+suffix,text)
    preview=client.get(f"/v1/documents/{doc['id']}/syllabus-preview",headers=h).json()
    p=preview['suggestedPlan'];assert '1) 원리 이해' in p['goals'];assert p['mainTextbooks']=='Core Book'
    assert p['supplementaryTextbooks']=='Reference';assert p['weeks'][0]['content']=='분류 개념과 예제'
    assert len(p['weeks'])==2
    body={**p,'syllabusVersionId':doc['currentVersionId'],'expectedRevision':0}
    first=client.put(f'/v1/courses/{c}/plan',headers=h,json=body)
    assert first.status_code==200,first.text
    assert first.json()['saved'] and first.json()['revision']==1
    assert client.get(f'/v1/courses/{c}/plan',headers=other).status_code==404
    assert client.put(f'/v1/courses/{c}/plan',headers=other,json=body).status_code==404
    assert client.put(f'/v1/courses/{c}/plan',headers=h,json=body).status_code==409
    body.update(goals='Edited canonical goals',mainTextbooks='Edited book',expectedRevision=1)
    body['weeks'][0]['content']='Edited weekly content'
    assert client.put(f'/v1/courses/{c}/plan',headers=h,json=body).status_code==200
    service=environment[0].state.service
    # Reading the canonical plan must not read/reparse the source or query vectors.
    monkeypatch.setattr(service.files,'read',lambda key: (_ for _ in ()).throw(AssertionError('Unexpected source read')))
    with environment[1].transaction(user) as db:
        context=service.syllabus(db,UUID(c))
        assert 'Edited canonical goals' in context and 'Edited book' in context and 'Edited weekly content' in context
        assert '1) 원리 이해' not in context
    material=upload(client,h,c,'lecture.txt','분류 개념과 예제 분류 모델 원리')
    client.put(f"/v1/courses/{c}/documents/{material['id']}/weeks",headers=h,json={'weekNumbers':[1]})
    response=generate(client,h,c,'lecture',[1],[material]);assert response.status_code==202,response.text
    rid=UUID(response.json()['id'])
    body.update(goals='Later edit',expectedRevision=2)
    assert client.put(f'/v1/courses/{c}/plan',headers=h,json=body).status_code==200
    with environment[1].transaction(user) as db:
        snapshot=db.execute('SELECT "syllabusSnapshot" FROM "runInputs" WHERE "runId"=%s',(rid,)).fetchone()['syllabusSnapshot']
        assert 'Edited canonical goals' in snapshot and 'Later edit' not in snapshot
    # Cancel queued work: no model calls are needed for this verification.
    assert client.post(f'/v1/runs/{rid}/cancellations',headers=h).status_code==200


def test_trend_provenance_and_week_survive_edit(client,environment):
    h,user=login(client);c,_,docs=setup_course(client,h)
    response=generate(client,h,c,'lecture',[1],docs[:1]);rid=UUID(response.json()['id'])
    refs=[{'id':'S1','title':'Synthetic reference','url':'https://example.org/paper','provider':'academic','retrievedAt':'2026-11-24','evidenceType':'metadata'}]
    def runner(data):
        result=demo(data);result['draft'].update(trend_references=refs,trend_search={'query':'topic','providers':[]});return result
    process(environment[0].state.service,user,rid,runner)
    run=client.get(f'/v1/runs/{rid}',headers=h).json();assert run['weekNumbers']==[1]
    draft=run['draft'];draft['trend_references']=[];draft['main_slides']=['## Edited']
    changed=client.patch(f'/v1/runs/{rid}/draft',headers=h,json={'expectedRevision':1,'draft':draft})
    assert changed.status_code==200,changed.text
    assert changed.json()['draft']['trend_references']==refs


def test_practice_references_pin_versions_and_isolate_courses(client,environment):
    import json
    h,user=login(client);course,syllabus,docs=setup_course(client,h);service=environment[0].state.service
    lecture=generate(client,h,course,'lecture',[1],[docs[0]]).json()['id']
    process(service,user,UUID(lecture),demo)
    assert client.post(f'/v1/runs/{lecture}/reviews',headers=h,json={'expectedRevision':1,'decision':'approve'}).status_code==200
    def finalized(data):
        result=demo(data);result['educationReview']={'status':'needsRevision','rubricVersion':'synthetic','criteria':[],'humanReviewRequired':True};return result
    process(service,user,UUID(lecture),finalized)
    report=client.get(f'/v1/runs/{lecture}/education-review',headers=h)
    assert report.json()['status']=='needsRevision'
    options=client.get(f'/v1/courses/{course}/practice-references',headers=h).json()
    assert {o['kind'] for o in options}=={'draft','material'}
    notebook=upload(client,h,course,'practice.ipynb',json.dumps({'nbformat':4,'nbformat_minor':5,'metadata':{},'cells':[{'id':'synthetic','cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':'print(1)'}]}))
    refs=[{'kind':o['kind'],'id':o['id']} for o in options]
    response=generate(client,h,course,'practice',[1],[notebook],referenceSources=refs)
    assert response.status_code==202,response.text
    rid=UUID(response.json()['id'])
    observed={}
    def capture(data):observed.update(data);return demo(data)
    process(service,user,rid,capture)
    assert 'Classification' in observed['practiceReferences']
    with environment[1].transaction(user) as db:
        inputs=db.execute('SELECT "taskConfig" FROM "runInputs" WHERE "runId"=%s',(rid,)).fetchone()['taskConfig']
        assert len(inputs['referenceSnapshots'])==2 and len(inputs['referenceSnapshots'][0]['contentHash'])==64
    h2,_=login(client);other,_,otherdocs=setup_course(client,h2)
    assert client.get(f'/v1/courses/{course}/practice-references',headers=h2).status_code==404
    assert client.get(f'/v1/runs/{lecture}/education-review',headers=h2).status_code==404
    nb2=upload(client,h2,other,'practice.ipynb',json.dumps({'nbformat':4,'nbformat_minor':5,'metadata':{},'cells':[{'id':'synthetic','cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':'print(1)'}]}))
    assert generate(client,h2,other,'practice',[1],[nb2],referenceSources=refs).status_code==404
    same,_,_=setup_course(client,h)
    nb3=upload(client,h,same,'practice.ipynb',json.dumps({'nbformat':4,'nbformat_minor':5,'metadata':{},'cells':[{'id':'synthetic','cell_type':'code','metadata':{},'execution_count':None,'outputs':[],'source':'print(1)'}]}))
    assert generate(client,h,same,'practice',[1],[nb3],referenceSources=refs).status_code==422


def test_practice_from_lecture_without_existing_notebook(client,environment):
    h,user=login(client);course,_,docs=setup_course(client,h)
    response=generate(client,h,course,'practice',[1],[docs[0]])
    assert response.status_code==202,response.text
    observed={}
    def capture(data):
        observed.update(data)
        return demo(data)
    process(environment[0].state.service,user,UUID(response.json()['id']),capture)
    assert 'notebook' not in observed
    assert 'Classification' in observed['raw_context']
    assert generate(client,h,course,'practice',[1],[]).status_code==422


def test_exam_item_review_gate_reports_and_answer_key(client,environment):
    h,user=login(client);other,_=login(client);course,_,docs=setup_course(client,h)
    params=[{'questionType':'single_choice','count':1},{'questionType':'open_answer','count':1}]
    r=generate(client,h,course,'exam',[1],docs[:1],parameters=params)
    assert r.status_code==202,r.text
    rid=r.json()['id'];service=environment[0].state.service
    def synthetic(data):
        if data['phase']=='finalize':return {'draft':data['draft'],'output':'# 학생용 문제지\n문제만 포함'}
        questions=[{'number':i+1,'question_type':p['question_type'],'content':'문제','model_answer':'SECRET ANSWER','learningObjective':'목표','bloomLevel':'understand','expectedDifficulty':'medium'} for i,p in enumerate(data['request']['parameters'])]
        return {'draft':{'reviewSchemaVersion':1,'questions':questions,'rubrics':[{'question_number':q['number'],'total_points':5,'criteria':[{'points':5,'description':'정확'}]} for q in questions],'itemReviews':{}}}
    process(service,user,UUID(rid),synthetic)
    assert client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':1,'decision':'approve'}).status_code==422
    draft=client.get(f'/v1/runs/{rid}',headers=h).json()['draft']
    draft['itemReviews']={'1':{'decision':'accept','checks':{k:True for k in ('alignment','cognitiveLevel','answerClarity','distractors','rubricClarity')}},'2':{'decision':'reject','reason':'학습목표 범위 초과'}}
    edit=client.patch(f'/v1/runs/{rid}/draft',headers=h,json={'expectedRevision':1,'draft':draft})
    assert edit.status_code==200,edit.text
    assert client.get(f'/v1/runs/{rid}/answer-key',headers=h).status_code==409
    assert client.post(f'/v1/runs/{rid}/reviews',headers=h,json={'expectedRevision':2,'decision':'approve'}).status_code==200
    process(service,user,UUID(rid),synthetic)
    answer=client.get(f'/v1/runs/{rid}/answer-key',headers=h).json()['markdown']
    assert 'SECRET ANSWER' in answer and '문항 2' not in answer
    assert '학습목표 범위 초과' in client.get(f'/v1/runs/{rid}/exam-review-report',headers=h).json()['markdown']
    for path in ('answer-key','exam-review-report'):
        assert client.get(f'/v1/runs/{rid}/{path}',headers=other).status_code==404
    assert generate(client,h,course,'exam',[1],docs[:1],parameters=[]).status_code==422


def test_cloud_queue_runs_after_commit_and_failure_is_retryable(client,environment,monkeypatch):
    from vercel import queue
    app,database=environment
    h,user=login(client);course,syllabus,docs=setup_course(client,h)
    monkeypatch.setenv('JOB_BACKEND','vercel')
    sent=[]
    async def send(topic,payload,**kwargs):
        with database.transaction(user) as db:
            assert db.execute('SELECT status FROM runs WHERE id=%s',(payload['run_id'],)).fetchone()['status']=='queued'
        sent.append((topic,payload,kwargs))
    monkeypatch.setattr(queue,'send',send)
    body={'taskType':'lecture','topic':'Classification','weekNumbers':[1],'documentIds':[docs[0]['id']]}
    response=client.post(f'/v1/courses/{course}/runs',headers={**h,'Idempotency-Key':uuid4().hex},json=body)
    assert response.status_code==202,response.text
    assert len(sent)==1 and sent[0][1]['storage']=='normalized'
    assert set(sent[0][1])=={'run_id','storage'}
    async def unavailable(*args,**kwargs):raise RuntimeError('Synthetic queue outage')
    monkeypatch.setattr(queue,'send',unavailable)
    response=client.post(f'/v1/courses/{course}/runs',headers={**h,'Idempotency-Key':uuid4().hex},json=body)
    assert response.status_code==202,response.text
    assert response.json()['status']=='failed'
    assert response.json()['error']=='queue_unavailable'


def test_chunk_upload_ownership_order_and_completion(client,environment,monkeypatch):
    from apps.api.normalized.cloud import DatabaseFiles
    from apps.api.normalized import uploads
    app,database=environment;DatabaseFiles.provision(database.dsn)
    monkeypatch.setattr(uploads,'CHUNK_SIZE',16)
    h,user=login(client);other,_=login(client);course=add_course(client,h)
    data=b'Synthetic course notes for secure chunk upload.'
    r=client.post(f'/v1/courses/{course}/document-uploads',headers=h,json={'name':'notes.txt','byteSize':len(data)})
    assert r.status_code==201,r.text
    ident=r.json()['id'];url=f'/v1/document-uploads/{ident}'
    assert client.put(url+'/parts/0',headers=other,files={'file':('part',data[:16])}).status_code==404
    assert client.put(url+'/parts/1',headers=h,files={'file':('part',data[:16])}).status_code==409
    assert client.post(url+'/complete',headers=h).status_code==409
    for part,start in enumerate(range(0,len(data),16)):
        assert client.put(url+f'/parts/{part}',headers=h,files={'file':('part',data[start:start+16])}).status_code==200
    assert client.post(url+'/complete',headers=other).status_code==404
    result=client.post(url+'/complete',headers=h)
    assert result.status_code==201,result.text
    assert result.json()['byteSize']==len(data)
    assert client.post(url+'/complete',headers=h).status_code==404
    with database.transaction(user) as db:
        key=db.execute('SELECT "storageKey" FROM "documentVersions" WHERE id=%s',(result.json()['currentVersionId'],)).fetchone()['storageKey']
    assert app.state.service.files.read(key)==data
