import json
from pathlib import Path
from uuid import uuid4

import nbformat
import pytest
from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.worker import process_once
from apps.api.legacy_runner import demo
from apps.api.store import pack


@pytest.fixture
def service(tmp_path):
    app = create_app(tmp_path / 'test.sqlite3', tokens={'alice-secret': 'alice', 'bob-secret': 'bob'}, mode='demo')
    client = TestClient(app)
    client.headers['Authorization'] = 'Bearer alice-secret'
    return client, app.state.store


def course(client):
    response = client.post('/v1/courses', json={'title': '합성 강의', 'syllabus': '1주차: 지도학습'})
    assert response.status_code == 201
    return response.json()['id']


def document(client, course_id, notebook=False):
    if notebook:
        body = nbformat.writes(nbformat.v4.new_notebook(cells=[nbformat.v4.new_code_cell('print(1)')]))
        file = ('lesson.ipynb', body, 'application/json')
    else:
        file = ('lesson.md', '# 지도학습\n지도학습은 정답이 있는 데이터로 학습합니다.', 'text/markdown')
    response = client.post(f'/v1/courses/{course_id}/documents', files={'file': file})
    assert response.status_code == 201, response.text
    return response.json()['id']


def create_run(client, c, d, kind='lecture', key=None):
    return client.post(f'/v1/courses/{c}/runs', headers={'Idempotency-Key': key or str(uuid4())}, json={
        'task_type': kind, 'topic': '지도학습', 'document_ids': [d],
        'rubric_guidelines': '기여도 중심 정성 평가',
        'roster': [{'student_id': 's1', 'name': '합성 참여자', 'github_id': 'example', 'repo_name': 'demo'}],
    })


@pytest.mark.parametrize('kind', ['manager', 'lecture', 'exam', 'practice', 'project'])
def test_all_agents_review_revise_approve_download(service, kind):
    client, store = service
    c = course(client); d = document(client, c, notebook=kind == 'practice')
    response = create_run(client, c, d, kind)
    assert response.status_code == 202, response.text
    r = response.json()['id']
    assert client.get(f'/v1/runs/{r}/artifact').status_code == 409
    assert process_once(store)  # Actual isolated subprocess, synthetic runner.
    assert client.get(f'/v1/runs/{r}').json()['status'] == 'waiting_review'
    assert client.post(f'/v1/runs/{r}/reviews', json={'decision': 'revise', 'expected_revision': 1, 'feedback': '사례를 보완하세요'}).status_code == 202
    assert process_once(store)
    assert client.post(f'/v1/runs/{r}/reviews', json={'decision': 'approve', 'expected_revision': 1}).status_code == 409
    assert client.post(f'/v1/runs/{r}/reviews', json={'decision': 'approve', 'expected_revision': 2}).status_code == 202
    assert client.post(f'/v1/runs/{r}/reviews', json={'decision': 'approve', 'expected_revision': 2}).status_code == 409
    assert process_once(store)
    download = client.get(f'/v1/runs/{r}/artifact')
    assert download.status_code == 200 and download.content
    if kind == 'practice':
        nbformat.validate(nbformat.from_dict(download.json()))
    assert client.post(f'/v1/runs/{r}/feedback', json={'rating': 4, 'comment': '시연 평가'}).status_code == 201


def test_cross_user_access_and_cross_course_documents(service):
    client, store = service
    c = course(client); d = document(client, c); r = create_run(client, c, d).json()['id']
    another = course(client)
    assert create_run(client, another, d).status_code == 404
    client.headers['Authorization'] = 'Bearer bob-secret'
    for path in (f'/v1/courses/{c}/documents', f'/v1/courses/{c}/runs', f'/v1/runs/{r}', f'/v1/runs/{r}/artifact'):
        assert client.get(path).status_code == 404
    assert client.delete(f'/v1/documents/{d}').status_code == 404
    assert client.post(f'/v1/runs/{r}/reviews', json={'decision': 'approve', 'expected_revision': 1}).status_code == 404
    assert create_run(client, c, d).status_code == 404
    assert client.get('/v1/courses').json() == []


def test_idempotency_conflict_and_body_cannot_approve(service):
    client, _ = service
    c = course(client); d = document(client, c)
    first = create_run(client, c, d, key='same-request-key')
    second = create_run(client, c, d, key='same-request-key')
    assert first.json()['id'] == second.json()['id']
    assert create_run(client, c, d, kind='exam', key='same-request-key').status_code == 409
    assert client.post(f'/v1/courses/{c}/runs', headers={'Idempotency-Key': 'another-key'}, json={'task_type':'lecture','topic':'test','approved':True}).status_code == 422


def test_restart_preserves_waiting_review(service, tmp_path):
    client, store = service
    c = course(client); d = document(client, c); r = create_run(client, c, d).json()['id']
    process_once(store, demo)
    restarted = TestClient(create_app(store.path, tokens={'alice-secret':'alice'}, mode='demo'))
    restarted.headers['Authorization'] = 'Bearer alice-secret'
    assert restarted.get(f'/v1/runs/{r}').json()['status'] == 'waiting_review'


def test_cancelled_job_cannot_publish_late_result(service):
    client, store = service
    c = course(client); d = document(client, c); r = create_run(client, c, d).json()['id']
    def late(data):
        assert client.post(f'/v1/runs/{r}/cancellations').status_code == 200
        return demo(data)
    process_once(store, late)
    assert client.get(f'/v1/runs/{r}').json()['status'] == 'cancelled'


def test_delete_removes_document_snapshots_and_outputs(service):
    client, store = service
    c = course(client); d = document(client, c); r = create_run(client, c, d).json()['id']
    assert client.delete(f'/v1/documents/{d}').status_code == 409
    process_once(store, demo)
    assert client.delete(f'/v1/documents/{d}').status_code == 204
    run = client.get(f'/v1/runs/{r}').json()
    assert run['citations'] == [] and run['draft'] is None
    with store.connect() as db:
        assert json.loads(db.execute('SELECT state FROM runs WHERE id=?',(r,)).fetchone()[0]) == {}


def test_upload_limits_auth_and_swagger(service):
    client, _ = service
    c = course(client)
    assert client.post(f'/v1/courses/{c}/documents', files={'file': ('bad.exe', b'x')}).status_code == 415
    assert client.post(f'/v1/courses/{c}/documents', files={'file': ('bad.pdf', b'not-pdf')}).status_code == 422
    client.headers.clear()
    assert client.get('/v1/courses').status_code == 401
    assert client.get('/docs').status_code == 200
    schema=client.get('/openapi.json').json()
    assert schema['components']['securitySchemes']['HTTPBearer']['scheme'] == 'bearer'
    assert len(schema['paths']) >= 13


def test_manager_dispatch_preserves_separate_child_review(service):
    client, store=service
    c=course(client);d=document(client,c);r=create_run(client,c,d,'manager').json()['id']
    assert client.post(f'/v1/runs/{r}/dispatches').status_code == 409
    process_once(store,demo)
    client.post(f'/v1/runs/{r}/reviews',json={'decision':'approve','expected_revision':1})
    process_once(store,demo)
    children=client.post(f'/v1/runs/{r}/dispatches').json()
    assert len(children)==1 and children[0]['status']=='queued'
    again=client.post(f'/v1/runs/{r}/dispatches').json()
    assert again[0]['id']==children[0]['id']
    process_once(store,demo)
    assert client.get(f"/v1/runs/{children[0]['id']}").json()['status']=='waiting_review'


def test_expired_worker_fails_without_repeating_model_calls(service):
    client, store=service
    c=course(client);d=document(client,c);r=create_run(client,c,d).json()['id']
    with store.connect() as db:
        row=db.execute('SELECT * FROM runs WHERE id=?',(r,)).fetchone()
        state=json.loads(row['state']);state['lease_until']='2000-01-01'
        db.execute("UPDATE runs SET status='running',state=? WHERE id=?",(pack(state),r))
    assert not process_once(store,demo)
    assert client.get(f'/v1/runs/{r}').json()['error']=='worker_interrupted'


def test_direct_edit_requires_new_version_and_preserves_shape(service):
    client,store=service
    c=course(client);d=document(client,c);r=create_run(client,c,d).json()['id']
    process_once(store,demo)
    draft=client.get(f'/v1/runs/{r}').json()['draft']
    draft['main_slides'][0]='## 교수자가 직접 편집한 슬라이드'
    result=client.patch(f'/v1/runs/{r}/draft',json={'expected_revision':1,'draft':draft})
    assert result.status_code==200 and result.json()['revision']==2
    assert client.post(f'/v1/runs/{r}/reviews',json={'decision':'approve','expected_revision':1}).status_code==409
    assert client.patch(f'/v1/runs/{r}/draft',json={'expected_revision':2,'draft':{'review_status':'approved'}}).status_code==422
    client.post(f'/v1/runs/{r}/reviews',json={'decision':'approve','expected_revision':2})
    process_once(store,demo)
    assert '직접 편집한' in client.get(f'/v1/runs/{r}/artifact').text
