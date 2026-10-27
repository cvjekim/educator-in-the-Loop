from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .models import Course, CourseCreate, Document, DraftUpdate, Error, FeedbackCreate, ReviewCreate, RetryCreate, SearchCreate, Run, RunCreate
from .store import Store, pack, update_run, recover_expired
from .queueing import schedule
from . import retrieval

ROOT = Path(__file__).resolve().parents[2]
NAMES = {'manager': '학기 계획', 'lecture': '강의 노트', 'practice': '실습 노트북', 'exam': '시험·루브릭', 'project': '프로젝트 평가'}


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(status, code, message):
    raise HTTPException(status, {'code': code, 'message': message})


def create_app(db_path=None, tokens=None, mode=None):
    store = Store(db_path or os.getenv('DATABASE_URL') or os.getenv('API_DATABASE', str(ROOT / 'artifacts/api/service.sqlite3')))
    access_tokens = tokens if tokens is not None else json.loads(os.getenv('API_ACCESS_TOKENS', '{}'))
    run_mode = mode or os.getenv('API_MODE', 'demo')
    semantic = os.getenv('RAG_MODE', 'keyword') == 'hybrid'
    upload_limit = 4_000_000 if os.getenv('VERCEL') else 10_000_000
    if os.getenv('VERCEL') and (not access_tokens or any(len(token) < 32 for token in access_tokens)):
        raise ValueError('Hosted API requires strong per-user access tokens')
    if run_mode not in ('demo', 'real'):
        raise ValueError('API_MODE must be demo or real')

    app = FastAPI(title='Educator-in-the-Loop API', version='0.2.0',
        description='교수자 강의 준비 API. Bearer 초대 토큰 인증. 202 작업 생성 → 상태 조회 → 버전별 교수자 검토 → 다운로드. demo 응답은 합성 데이터이며 실제 모델 실행이 아닙니다.',
        responses={401: {'model': Error}, 404: {'model': Error}, 409: {'model': Error}, 422: {'model': Error}})
    app.state.store = store
    app.state.mode = run_mode
    app.add_middleware(CORSMiddleware, allow_origins=os.getenv('API_CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173').split(','),
                       allow_methods=['GET', 'POST', 'PATCH', 'DELETE'], allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key'])
    bearer = HTTPBearer(auto_error=False)
    admin_ids = set(filter(None, os.getenv('API_ADMIN_IDS', '').split(',')))

    def owner(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if credentials:
            for token, identity in access_tokens.items():
                if hmac.compare_digest(credentials.credentials, token):
                    return identity
            token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
            with store.connect() as db:
                invite = db.execute('SELECT identity FROM invitations WHERE token_hash=? AND revoked=0', (token_hash,)).fetchone()
                if invite:
                    return invite['identity']
        fail(401, 'unauthorized', '유효한 초대 토큰으로 연결해 주세요.')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else {'code': 'request_error', 'message': str(exc.detail)}
        return JSONResponse({**detail, 'request_id': str(uuid4())}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'code': 'validation_error', 'message': '입력 형식·필수 항목·크기를 확인하세요.', 'request_id': str(uuid4())}, status_code=422)

    def owned(db, table, resource_id, identity):
        row = db.execute(f'SELECT * FROM {table} WHERE id=? AND owner=?', (resource_id, identity)).fetchone()
        if not row:
            fail(404, 'not_found', '항목을 찾을 수 없습니다.')
        return row

    @app.get('/', include_in_schema=False)
    def root():
        return {'service': 'educator-api', 'health': '/health', 'docs': '/docs'}

    @app.get('/health', tags=['운영'])
    def health():
        return {'status': 'ok', 'mode': run_mode}

    @app.get('/ready', tags=['운영'])
    def ready():
        try:
            with store.connect() as db:
                db.execute('SELECT 1').fetchone()
            if run_mode == 'real' and not os.getenv('OPENAI_API_KEY'):
                raise RuntimeError('model unavailable')
        except Exception:
            return JSONResponse({'status': 'unavailable'}, status_code=503)
        return {'status': 'ready', 'mode': run_mode}

    @app.get('/v1/me', tags=['인증'])
    def me(identity=Depends(owner)):
        return {'id': identity, 'mode': run_mode, 'admin': identity in admin_ids}

    def administrator(identity=Depends(owner)):
        if identity not in admin_ids:
            fail(403, 'admin_required', '관리자만 초대를 관리할 수 있습니다.')
        return identity

    @app.get('/v1/invitations', tags=['인증'])
    def invitations(identity=Depends(administrator)):
        with store.connect() as db:
            return [{**json.loads(row['payload']), 'revoked': bool(row['revoked'])} for row in db.execute('SELECT payload,revoked FROM invitations WHERE issuer=?', (identity,))]

    @app.post('/v1/invitations', status_code=201, tags=['인증'], description='발급 즉시 한 번만 원문 토큰을 반환합니다. DB에는 SHA-256 해시만 저장합니다.')
    def invite(identity=Depends(administrator)):
        token = secrets.token_urlsafe(36)
        item = {'id': str(uuid4()), 'created_at': now()}
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count = db.execute('SELECT COUNT(*) FROM invitations WHERE issuer=? AND revoked=0', (identity,)).fetchone()[0]
            if count >= 100:
                fail(409, 'invite_limit', '활성 초대는 최대 100개입니다.')
            db.execute('INSERT INTO invitations (id,token_hash,identity,issuer,payload,revoked) VALUES (?,?,?,?,?,0)', (item['id'], hashlib.sha256(token.encode()).hexdigest(), str(uuid4()), identity, pack(item)))
        return {**item, 'token': token}

    @app.delete('/v1/invitations/{invitation_id}', status_code=204, tags=['인증'])
    def revoke(invitation_id: str, identity=Depends(administrator)):
        with store.connect() as db:
            row = db.execute('SELECT id FROM invitations WHERE id=? AND issuer=?', (invitation_id, identity)).fetchone()
            if not row:
                fail(404, 'not_found', '초대를 찾을 수 없습니다.')
            db.execute('UPDATE invitations SET revoked=1 WHERE id=? AND issuer=?', (invitation_id, identity))
        return Response(status_code=204)

    @app.get('/v1/capabilities', tags=['에이전트'])
    def capabilities(identity=Depends(owner)):
        return {'mode': run_mode, 'agents': [{'id': k, 'name': v} for k, v in NAMES.items()],
                'notebook_execution': bool(os.getenv('NOTEBOOK_SANDBOX_IMAGE')), 'retrieval': 'hybrid' if semantic else 'keyword', 'upload_limit_bytes': upload_limit}

    @app.get('/v1/courses', response_model=list[Course], tags=['강의'])
    def courses(identity=Depends(owner)):
        with store.connect() as db:
            return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM courses WHERE owner=? ORDER BY rowid DESC', (identity,))]

    @app.post('/v1/courses', response_model=Course, status_code=201, tags=['강의'])
    def create_course(body: CourseCreate, identity=Depends(owner)):
        item = {**body.model_dump(), 'id': str(uuid4()), 'created_at': now()}
        with store.connect() as db:
            db.execute('INSERT INTO courses VALUES (?,?,?)', (item['id'], identity, pack(item)))
        return item

    @app.get('/v1/courses/{course_id}/documents', response_model=list[Document], tags=['자료'])
    def documents(course_id: str, identity=Depends(owner)):
        with store.connect() as db:
            owned(db, 'courses', course_id, identity)
            return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM documents WHERE owner=? AND course_id=?', (identity, course_id))]

    @app.post('/v1/courses/{course_id}/documents', response_model=Document, status_code=201, tags=['자료'], description='PDF/PPTX/MD/TXT/IPYNB, 로컬 최대 10MB / Vercel 최대 4MB. 파싱은 제한시간이 있는 별도 프로세스에서 실행하며 notebook은 실행하지 않습니다.')
    def upload(course_id: str, file: UploadFile = File(...), identity=Depends(owner)):
        with store.connect() as db:
            owned(db, 'courses', course_id, identity)
        name = Path((file.filename or '').replace('\\', '/')).name
        suffix = Path(name).suffix.lower()
        if suffix not in ('.pdf', '.pptx', '.md', '.txt', '.ipynb'):
            fail(415, 'unsupported_type', 'PDF, PPTX, MD, TXT, IPYNB 파일을 선택하세요.')
        content = file.file.read(upload_limit + 1)
        if len(content) > upload_limit:
            fail(413, 'too_large', f'파일 크기는 {upload_limit // 1_000_000}MB 이하이어야 합니다.')
        with tempfile.TemporaryDirectory(prefix='educator-upload-') as folder:
            path = Path(folder) / ('input' + suffix)
            path.write_bytes(content)
            try:
                env = {'PATH': os.environ.get('PATH', ''), 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPATH': os.pathsep.join(sys.path)}
                parsed = subprocess.run([sys.executable, str(ROOT / 'apps/api/parse_document.py'), str(path)],
                                        capture_output=True, timeout=30, text=True, env=env)
                if parsed.returncode:
                    fail(422, 'parse_failed', '텍스트를 추출할 수 없습니다. 파일 형식·페이지 수·OCR 필요 여부를 확인하세요.')
                data = json.loads(parsed.stdout)
            except subprocess.TimeoutExpired:
                fail(422, 'parse_timeout', '파일 분석 제한 시간을 초과했습니다.')
        item = {'id': str(uuid4()), 'course_id': course_id, 'filename': name[:180], 'size': len(content), 'pages': len(data['pages']), 'status': 'ready'}
        try:
            data = retrieval.index_document(item['id'], data, semantic=semantic)
        except Exception:
            fail(503, 'index_failed', '검색 색인을 만들지 못했습니다. 잠시 후 다시 업로드하세요.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owned(db, 'courses', course_id, identity)
            count = db.execute('SELECT COUNT(*) FROM documents WHERE owner=? AND course_id=?', (identity, course_id)).fetchone()[0]
            if count >= 50:
                fail(409, 'document_limit', '강의당 최대 50개 자료를 저장할 수 있습니다.')
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?)', (item['id'], identity, course_id, pack(item), pack(data)))
        return item

    @app.post('/v1/courses/{course_id}/search', tags=['자료'])
    def search_documents(course_id: str, body: SearchCreate, identity=Depends(owner)):
        with store.connect() as db:
            owned(db, 'courses', course_id, identity)
            rows = db.execute('SELECT * FROM documents WHERE owner=? AND course_id=?', (identity, course_id)).fetchall()
            if body.document_ids and not set(body.document_ids).issubset({row['id'] for row in rows}):
                fail(404, 'not_found', '강의에 속한 자료가 아닙니다.')
            records = [(json.loads(row['payload']), json.loads(row['content'])) for row in rows if not body.document_ids or row['id'] in body.document_ids]
        try:
            results = retrieval.search(records, body.query, body.limit, semantic=semantic)
        except Exception:
            fail(503, 'search_unavailable', '검색 서비스에 연결할 수 없습니다.')
        # Recheck after the external embedding request, so concurrently deleted documents cannot leak.
        with store.connect() as db:
            owned(db, 'courses', course_id, identity)
            live = {row['id'] for row in db.execute('SELECT id FROM documents WHERE owner=? AND course_id=?', (identity, course_id))}
        return {'results': [c for c in results if c['document_id'] in live], 'retrieval': 'hybrid' if semantic else 'keyword'}

    @app.delete('/v1/documents/{document_id}', status_code=204, tags=['자료'], description='연관 작업의 자료 snapshot과 산출물도 제거합니다. 실행 중인 작업은 먼저 취소하세요.')
    def delete_document(document_id: str, identity=Depends(owner)):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owned(db, 'documents', document_id, identity)
            linked = []
            for row in db.execute('SELECT * FROM runs WHERE owner=?', (identity,)):
                state = json.loads(row['state'])
                if document_id in state.get('request', {}).get('document_ids', []):
                    if row['status'] in ('running', 'queued'):
                        fail(409, 'active_run', '이 자료를 사용하는 작업을 먼저 취소하세요.')
                    linked.append(row)
            for row in linked:
                run = json.loads(row['payload'])
                run.update(status='cancelled', draft=None, output=None, citations=[], reviews=[], error='source_deleted')
                update_run(db, run, {})
                db.execute('DELETE FROM feedback WHERE owner=? AND run_id=?', (identity, run['id']))
            db.execute('DELETE FROM documents WHERE id=? AND owner=?', (document_id, identity))
        return Response(status_code=204)

    def enqueue(db, course_id, body, identity, key, query_vector=None):
        course = json.loads(owned(db, 'courses', course_id, identity)['payload'])
        fingerprint = hashlib.sha256(pack(body.model_dump()).encode()).hexdigest()
        prior = db.execute('SELECT * FROM runs WHERE owner=? AND course_id=? AND idempotency_key=?', (identity, course_id, key)).fetchone()
        if prior:
            if prior['request_hash'] != fingerprint:
                fail(409, 'idempotency_conflict', '같은 요청 키에 다른 입력을 사용할 수 없습니다.')
            return json.loads(prior['payload'])
        if body.execute_notebook and not os.getenv('NOTEBOOK_SANDBOX_IMAGE'):
            fail(409, 'sandbox_unavailable', '노트북 실행 sandbox가 설정되지 않았습니다. 실행 검증 없이 초안을 만들 수 있습니다.')
        count = db.execute("SELECT COUNT(*) FROM runs WHERE owner=? AND status IN ('queued','running')", (identity,)).fetchone()[0]
        if count >= 5:
            fail(429, 'run_limit', '동시에 최대 5개 작업을 실행할 수 있습니다.')
        citations, notebook, records = [], None, []
        for doc_id in body.document_ids:
            row = owned(db, 'documents', doc_id, identity)
            if row['course_id'] != course_id:
                fail(404, 'not_found', '강의에 속한 자료가 아닙니다.')
            meta, data = json.loads(row['payload']), json.loads(row['content'])
            if 'notebook' in data:
                notebook = data['notebook']
            records.append((meta, data))
        citations = retrieval.search(records, body.topic, query_vector=query_vector)
        if body.task_type in ('lecture', 'exam') and not citations:
            fail(422, 'source_required', '강의 자료를 먼저 업로드하고 선택하세요.')
        if body.task_type == 'practice' and notebook is None:
            fail(422, 'notebook_required', 'IPYNB 자료를 선택하세요.')
        if body.task_type == 'project' and (not body.roster or not body.rubric_guidelines):
            fail(422, 'roster_required', '학생 저장소 명단과 평가 기준이 필요합니다.')
        if body.task_type == 'manager' and not course['syllabus']:
            fail(422, 'syllabus_required', '강의 생성 시 강의계획서를 입력하세요.')
        run = {'id': str(uuid4()), 'course_id': course_id, 'task_type': body.task_type, 'topic': body.topic, 'status': 'queued',
               'revision': 1, 'mode': run_mode, 'draft': None, 'citations': citations, 'output': None, 'error': None,
               'output_format': 'ipynb' if body.task_type == 'practice' else 'md', 'created_at': now(), 'reviews': [], 'child_ids': []}
        state = {'request': body.model_dump(), 'syllabus': course['syllabus'], 'raw_context': '\n\n'.join('[SOURCE '+str(c.get('chunk_id',''))+' page '+str(c['page'])+']\n'+c['text']+'\n[/SOURCE]' for c in citations), 'notebook': notebook, 'phase': 'draft'}
        db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)', (run['id'], identity, course_id, 'queued', pack(run), pack(state), fingerprint, key))
        return run

    @app.post('/v1/courses/{course_id}/runs', response_model=Run, status_code=202, tags=['작업'])
    def create_run(course_id: str, body: RunCreate, idempotency_key: str = Header(min_length=8, max_length=128), identity=Depends(owner)):
        with store.connect() as db:
            owned(db, 'courses', course_id, identity)
        try:
            query_vector = retrieval.embed([body.topic])[0] if semantic and body.document_ids else None
        except Exception:
            fail(503, 'search_unavailable', '검색 서비스에 연결할 수 없습니다.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            run = enqueue(db, course_id, body, identity, idempotency_key, query_vector)
        return schedule(store, run)

    @app.get('/v1/courses/{course_id}/runs', response_model=list[Run], tags=['작업'])
    def runs(course_id: str, identity=Depends(owner)):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owned(db, 'courses', course_id, identity)
            recover_expired(db, identity, course_id)
            return [json.loads(r['payload']) for r in db.execute('SELECT payload FROM runs WHERE owner=? AND course_id=? ORDER BY rowid DESC', (identity, course_id))]

    @app.get('/v1/runs/{run_id}', response_model=Run, tags=['작업'])
    def run_detail(run_id: str, identity=Depends(owner)):
        with store.connect() as db:
            return json.loads(owned(db, 'runs', run_id, identity)['payload'])

    @app.post('/v1/runs/{run_id}/reviews', response_model=Run, status_code=202, tags=['검토'])
    def review(run_id: str, body: ReviewCreate, identity=Depends(owner)):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = owned(db, 'runs', run_id, identity)
            run, state = json.loads(row['payload']), json.loads(row['state'])
            if run['status'] != 'waiting_review' or run['revision'] != body.expected_revision:
                fail(409, 'stale_review', '초안이 변경됐거나 이미 처리됐습니다. 최신 상태를 확인하세요.')
            run['reviews'].append({**body.model_dump(), 'reviewer_id': identity, 'created_at': now()})
            if body.decision == 'revise':
                if run['revision'] >= 10:
                    fail(409, 'revision_limit', '최대 수정 횟수에 도달했습니다.')
                run['revision'] += 1
                state['request']['guidelines'] += '\n교수자 수정 요청: ' + body.feedback
                state['phase'] = 'draft'
            else:
                state['phase'] = 'finalize'
            run['status'] = 'queued'
            update_run(db, run, state)
        return schedule(store, run)

    @app.patch('/v1/runs/{run_id}/draft', response_model=Run, tags=['검토'], description='교수자가 초안을 직접 편집합니다. 버전이 증가하며 재승인이 필요합니다. 식별자와 구조를 임의로 변경할 수 없습니다.')
    def edit_draft(run_id: str, body: DraftUpdate, identity=Depends(owner)):
        def validate_shape(before, after):
            if type(before) is not type(after):
                fail(422, 'draft_shape', '초안의 데이터 형식을 유지하세요.')
            if isinstance(before, dict):
                if set(before) != set(after):
                    fail(422, 'draft_shape', '초안의 필드 구성을 유지하세요.')
                for key in before:
                    if key in ('student_id', 'number', 'question_number', 'task_type', 'cell_type', 'id') and before[key] != after[key]:
                        fail(422, 'draft_identity', '산출물 식별자와 유형은 변경할 수 없습니다.')
                    validate_shape(before[key], after[key])
            elif isinstance(before, list):
                if len(before) != len(after):
                    fail(422, 'draft_shape', '기존 항목의 내용을 수정하세요.')
                for a, b in zip(before, after):
                    validate_shape(a, b)
        if len(pack(body.draft)) > 200_000:
            fail(413, 'draft_too_large', '초안이 너무 큽니다.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = owned(db, 'runs', run_id, identity)
            run, state = json.loads(row['payload']), json.loads(row['state'])
            if run['status'] != 'waiting_review' or run['revision'] != body.expected_revision:
                fail(409, 'stale_review', '초안이 변경됐거나 이미 처리됐습니다.')
            if run['revision'] >= 10:
                fail(409, 'revision_limit', '최대 수정 횟수에 도달했습니다.')
            validate_shape(run['draft'], body.draft)
            run['reviews'].append({'decision': 'edit', 'expected_revision': run['revision'], 'reviewer_id': identity, 'created_at': now()})
            run['draft'] = body.draft
            run['revision'] += 1
            update_run(db, run, state)
            return run

    @app.post('/v1/runs/{run_id}/cancellations', response_model=Run, tags=['작업'])
    def cancel(run_id: str, identity=Depends(owner)):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = owned(db, 'runs', run_id, identity)
            run, state = json.loads(row['payload']), json.loads(row['state'])
            if run['status'] == 'succeeded':
                fail(409, 'completed', '이미 완료된 작업입니다.')
            run['status'] = 'cancelled'
            update_run(db, run, state)
            return run

    @app.post('/v1/runs/{run_id}/dispatches', response_model=list[Run], status_code=202, tags=['에이전트'], description='승인 완료된 Manager 계획을 별도 검토가 필요한 하위 작업으로 생성. 재요청해도 중복 생성하지 않습니다.')
    def dispatch(run_id: str, identity=Depends(owner)):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = owned(db, 'runs', run_id, identity)
            parent, state = json.loads(row['payload']), json.loads(row['state'])
            if parent['task_type'] != 'manager' or parent['status'] != 'succeeded':
                fail(409, 'plan_not_approved', '학기 계획 승인 완료 후 실행하세요.')
            tasks = parent['draft'].get('tasks', [])
            if not tasks or len(tasks) > 5:
                fail(422, 'plan_size', '한 번에 1~5개 작업을 포함하는 계획이 필요합니다.')
            children = []
            for index, task in enumerate(tasks):
                kind = task.get('task_type')
                if kind not in ('lecture', 'practice', 'exam', 'project'):
                    fail(422, 'invalid_task', '계획에 지원하지 않는 작업이 있습니다.')
                request = RunCreate(**{**state['request'], 'task_type': kind, 'week': task.get('week', 1), 'topic': task.get('context') or task.get('subject') or parent['topic']})
                children.append(enqueue(db, row['course_id'], request, identity, f'{run_id}:dispatch:{index}'))
            parent['child_ids'] = [c['id'] for c in children]
            update_run(db, parent, state)
        return [schedule(store, child) for child in children]

    @app.get('/v1/runs/{run_id}/artifact', tags=['산출물'], response_class=Response,
             responses={200: {'content': {'text/markdown': {}, 'application/x-ipynb+json': {}}}}, description='승인된 최종 산출물만 다운로드. 초안은 409.')
    def artifact(run_id: str, identity=Depends(owner)):
        with store.connect() as db:
            run = json.loads(owned(db, 'runs', run_id, identity)['payload'])
        if run['status'] != 'succeeded' or not run['output']:
            fail(409, 'approval_required', '교수자 승인과 최종 처리가 필요합니다.')
        fmt = run['output_format']
        return Response(run['output'], media_type='application/x-ipynb+json' if fmt == 'ipynb' else 'text/markdown',
                        headers={'Content-Disposition': f'attachment; filename="{run_id}.{fmt}"'})

    @app.post('/v1/runs/{run_id}/retries', response_model=Run, status_code=202, tags=['작업'])
    def retry_run(run_id: str, body: RetryCreate, identity=Depends(owner)):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = owned(db, 'runs', run_id, identity)
            run, state = json.loads(row['payload']), json.loads(row['state'])
            if run['revision'] != body.expected_revision or run['status'] not in ('failed', 'queued'):
                fail(409, 'retry_conflict', '실패하거나 전달 대기 중인 최신 작업만 재시도할 수 있습니다.')
            if not state.get('request'):
                fail(409, 'source_deleted', '자료가 삭제된 작업입니다.')
            if run['status'] == 'failed':
                state['attempt'] = state.get('attempt', 0) + 1
                if state['attempt'] > 3:
                    fail(409, 'retry_limit', '최대 재시도 횟수에 도달했습니다.')
            run.update(status='queued', error=None)
            update_run(db, run, state)
        return schedule(store, run)

    @app.delete('/v1/courses/{course_id}', status_code=204, tags=['강의'])
    def delete_course(course_id: str, identity=Depends(owner)):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            owned(db, 'courses', course_id, identity)
            active = db.execute("SELECT id FROM runs WHERE owner=? AND course_id=? AND status IN ('running','queued')", (identity, course_id)).fetchone()
            if active:
                fail(409, 'active_run', '진행 중인 작업을 먼저 취소하세요.')
            db.execute('DELETE FROM feedback WHERE owner=? AND run_id IN (SELECT id FROM runs WHERE owner=? AND course_id=?)', (identity, identity, course_id))
            db.execute('DELETE FROM runs WHERE owner=? AND course_id=?', (identity, course_id))
            db.execute('DELETE FROM documents WHERE owner=? AND course_id=?', (identity, course_id))
            db.execute('DELETE FROM courses WHERE id=? AND owner=?', (course_id, identity))
        return Response(status_code=204)

    @app.post('/v1/runs/{run_id}/feedback', status_code=201, tags=['피드백'])
    def feedback(run_id: str, body: FeedbackCreate, identity=Depends(owner)):
        item = {'id': str(uuid4()), **body.model_dump(), 'created_at': now()}
        with store.connect() as db:
            owned(db, 'runs', run_id, identity)
            db.execute('INSERT INTO feedback VALUES (?,?,?,?)', (item['id'], identity, run_id, pack(item)))
        return item

    return app


app = create_app()
