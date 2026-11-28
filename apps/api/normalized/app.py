"""OAuth-only, camelCase API backed exclusively by normalized PostgreSQL tables."""
import json
import os
import re
from uuid import UUID,uuid4

from fastapi import Depends,FastAPI,File,Header,Request,Response,UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse,StreamingResponse
from fastapi.security import HTTPBearer
from psycopg import IntegrityError
from psycopg.types.json import Jsonb

from apps.database.client import Database
from apps.api.accounts import install_accounts
from apps.api.events import stream
from .cloud import storage as configured_storage, publish
from .models import *
from .service import Service,fail,insert,one


def create_app(database=None,storage=None,mode=None):
    schema=os.getenv('DATABASE_SCHEMA','educatorDev')
    database=database or Database(os.environ['DATABASE_URL'],schema)
    service=Service(database,storage or configured_storage(database),mode or os.getenv('API_MODE','real'),os.getenv('RAG_MODE')=='hybrid')
    app=FastAPI(title='Educator API',version='0.4.0',description='Google 로그인 → 이름·학과 등록 → 개인 강의·RAG·주차별 생성. camelCase 계약. 비공개 파일 저장소.')
    app.state.service=service
    app.add_middleware(CORSMiddleware,allow_origins=os.getenv('API_CORS_ORIGINS','http://localhost:5173,http://127.0.0.1:5173').split(','),allow_methods=['GET','POST','PUT','PATCH','DELETE'],allow_headers=['Authorization','Content-Type','Idempotency-Key'])
    accounts=install_accounts(app,database=database)
    bearer=HTTPBearer(auto_error=False)
    def owner(credentials=Depends(bearer)):
        profile=accounts.resolve(credentials.credentials) if credentials else None
        if not profile:fail(401,'Google 계정으로 다시 로그인해 주세요.')
        return UUID(profile['id'])

    from .uploads import install_uploads
    install_uploads(app,service,owner)

    from fastapi import HTTPException
    @app.exception_handler(HTTPException)
    async def error(request,exc):
        detail=exc.detail if isinstance(exc.detail,dict) else {'code':'request_error','message':str(exc.detail)}
        return JSONResponse({**detail,'requestId':str(uuid4())},status_code=exc.status_code,headers={'Cache-Control':'no-store'})
    @app.exception_handler(RequestValidationError)
    async def invalid(request,exc):return JSONResponse({'code':'validation_error','message':'입력 형식·길이·필수 항목을 확인하세요.'},status_code=422)
    @app.exception_handler(IntegrityError)
    async def conflict(request,exc):return JSONResponse({'code':'data_conflict','message':'중복되거나 다른 항목에 연결된 데이터입니다. 최신 정보를 확인하세요.'},status_code=409)
    @app.get('/',include_in_schema=False)
    @app.get('/health')
    def health():return {'status':'ok','mode':service.mode,'storage':'normalized'}
    @app.get('/ready')
    def ready():
        with database.transaction(uuid4()) as db:db.execute('SELECT 1 FROM users LIMIT 0')
        return {'status':'ready','storage':'normalized'}
    @app.get('/v1/me',tags=['인증'])
    def me(user=Depends(owner)):return {'id':str(user),'mode':service.mode,'admin':False,'storage':'normalized'}
    @app.get('/v1/courses',tags=['강의'])
    def courses(user=Depends(owner)):
        with database.transaction(user) as db:return db.execute('SELECT * FROM courses ORDER BY "createdAt" DESC').fetchall()
    @app.post('/v1/courses',status_code=201,tags=['강의'])
    def course_add(body:CourseInput,user=Depends(owner)):
        with database.transaction(user) as db:return insert(db,'courses',ownerId=user,**body.model_dump())
    @app.patch('/v1/courses/{courseId}',tags=['강의'])
    def course_update(courseId:UUID,body:CourseInput,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courses',courseId)
            return db.execute('UPDATE courses SET title=%s,syllabus=%s WHERE id=%s RETURNING *',(body.title,body.syllabus,courseId)).fetchone()
    @app.delete('/v1/courses/{courseId}',status_code=204,tags=['강의'])
    def course_delete(courseId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:one(db,'courses',courseId);db.execute('DELETE FROM courses WHERE id=%s',(courseId,))
        service.clean_files(user);return Response(status_code=204)
    @app.get('/v1/courses/{courseId}/plan',tags=['강의계획·주차'])
    def plan(courseId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            c=one(db,'courses',courseId)
            p=db.execute('SELECT * FROM "coursePlans" WHERE "courseId"=%s',(courseId,)).fetchone()
            return {'goals':p['goals'] if p else '', 'mainTextbooks':p['mainTextbooks'] if p else '', 'supplementaryTextbooks':p['supplementaryTextbooks'] if p else '', 'revision':p['revision'] if p else 0, 'saved':bool(p), 'syllabusVersionId':c['syllabusVersionId'],'weeks':db.execute('SELECT * FROM "courseWeeks" WHERE "courseId"=%s ORDER BY "weekNumber"',(courseId,)).fetchall()}
    @app.put('/v1/courses/{courseId}/plan',tags=['강의계획·주차'],description='강의계획서 버전과 주차 계획을 저장. 삭제한 주차의 자료 연결만 제거되며 기존 생성 요청의 스냅샷은 보존됩니다.')
    def plan_update(courseId:UUID,body:PlanInput,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courses',courseId)
            db.execute('SELECT id FROM courses WHERE id=%s FOR UPDATE',(courseId,))
            existing=db.execute('SELECT revision FROM "coursePlans" WHERE "courseId"=%s',(courseId,)).fetchone()
            revision=existing['revision'] if existing else 0
            if body.expectedRevision is not None and body.expectedRevision!=revision:fail(409,'다른 화면에서 계획서를 수정했습니다. 다시 불러온 뒤 수정해 주세요.')
            if body.syllabusVersionId:
                version=one(db,'documentVersions',body.syllabusVersionId)
                if not db.execute('SELECT 1 FROM "courseDocuments" WHERE "courseId"=%s AND "documentId"=%s',(courseId,version['documentId'])).fetchone():fail(422,'강의에 연결한 강의계획서를 선택하세요.')
            nums=[w.weekNumber for w in body.weeks]
            db.execute('DELETE FROM "courseWeeks" WHERE "courseId"=%s AND NOT ("weekNumber"=ANY(%s))',(courseId,nums))
            for w in body.weeks:
                db.execute('INSERT INTO "courseWeeks" ("courseId","weekNumber",topic,objectives,content) VALUES (%s,%s,%s,%s,%s) ON CONFLICT ("courseId","weekNumber") DO UPDATE SET topic=excluded.topic,objectives=excluded.objectives,content=excluded.content',(courseId,w.weekNumber,w.topic,w.objectives,w.content))
            db.execute('INSERT INTO "coursePlans" ("courseId",goals,"mainTextbooks","supplementaryTextbooks",revision) VALUES (%s,%s,%s,%s,%s) ON CONFLICT ("courseId") DO UPDATE SET goals=excluded.goals,"mainTextbooks"=excluded."mainTextbooks","supplementaryTextbooks"=excluded."supplementaryTextbooks",revision=excluded.revision',(courseId,body.goals,body.mainTextbooks,body.supplementaryTextbooks,revision+1))
            db.execute('UPDATE courses SET "syllabusVersionId"=%s WHERE id=%s',(body.syllabusVersionId,courseId))
        return plan(courseId,user)
    @app.get('/v1/documents/{documentId}/syllabus-preview',tags=['강의계획·주차'])
    def syllabus_preview(documentId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            d=one(db,'documents',documentId);v=one(db,'documentVersions',d['currentVersionId'])
            from .service import parse_file
            parsed=parse_file(v['originalFileName'],service.files.read(v['storageKey']),syllabus=True)
            pages=parsed['pages']
            from .syllabus import parse_syllabus
            text='\n\n'.join(pages)[:60000]
            structured=parse_syllabus(text,parsed.get('tables'))
            return {'documentVersionId':v['id'],'text':text,'suggestedWeeks':structured['weeks'],'suggestedPlan':structured,'requiresConfirmation':True}
    @app.get('/v1/documents',tags=['개인 자료실'])
    def library(user=Depends(owner)):return service.library(user)
    @app.post('/v1/documents',status_code=201,tags=['개인 자료실'])
    def library_upload(file:UploadFile=File(...),user=Depends(owner)):return service.upload(user,file.filename or 'upload',file.file.read(10_000_001))
    @app.get('/v1/courses/{courseId}/documents',tags=['강의 자료'])
    def course_documents(courseId:UUID,user=Depends(owner)):return service.library(user,courseId)
    @app.post('/v1/courses/{courseId}/documents',status_code=201,tags=['강의 자료'])
    def upload(courseId:UUID,file:UploadFile=File(...),user=Depends(owner)):
        with database.transaction(user) as db:one(db,'courses',courseId)
        return service.upload(user,file.filename or 'upload',file.file.read(10_000_001),courseId)
    @app.post('/v1/courses/{courseId}/document-links',status_code=201,tags=['강의 자료'])
    def link(courseId:UUID,body:LinkInput,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courses',courseId);one(db,'documents',body.documentId)
            db.execute('INSERT INTO "courseDocuments" ("courseId","documentId") VALUES (%s,%s) ON CONFLICT DO NOTHING',(courseId,body.documentId))
            service.set_weeks(db,courseId,body.documentId,body.weekNumbers)
        return service.library(user,courseId)
    @app.put('/v1/courses/{courseId}/documents/{documentId}/weeks',tags=['강의 자료'])
    def document_weeks(courseId:UUID,documentId:UUID,body:WeeksInput,user=Depends(owner)):
        with database.transaction(user) as db:one(db,'courses',courseId);service.set_weeks(db,courseId,documentId,body.weekNumbers)
        return service.library(user,courseId)
    @app.delete('/v1/courses/{courseId}/documents/{documentId}',status_code=204,tags=['강의 자료'])
    def unlink(courseId:UUID,documentId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            c=one(db,'courses',courseId);d=one(db,'documents',documentId)
            db.execute('UPDATE courses SET "syllabusVersionId"=NULL WHERE id=%s AND "syllabusVersionId" IN (SELECT id FROM "documentVersions" WHERE "documentId"=%s)',(courseId,documentId))
            db.execute('DELETE FROM "courseDocuments" WHERE "courseId"=%s AND "documentId"=%s',(courseId,documentId))
        return Response(status_code=204)
    @app.delete('/v1/documents/{documentId}',status_code=204,tags=['개인 자료실'],description='개인 원본과 관련 생성 결과를 연결된 모든 강의에서 삭제합니다.')
    def document_delete(documentId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:one(db,'documents',documentId);db.execute('DELETE FROM documents WHERE id=%s',(documentId,))
        service.clean_files(user);return Response(status_code=204)
    @app.get('/v1/documents/{documentId}/file',tags=['개인 자료실'])
    def document_file(documentId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            d=one(db,'documents',documentId);v=one(db,'documentVersions',d['currentVersionId'])
            return Response(service.files.read(v['storageKey']),media_type='application/octet-stream',headers={'Content-Disposition':'attachment','Cache-Control':'no-store'})
    @app.post('/v1/courses/{courseId}/search',tags=['RAG'])
    def search(courseId:UUID,body:SearchInput,user=Depends(owner)):return service.search(user,courseId,body)
    @app.get('/v1/courses/{courseId}/students',tags=['학생'])
    def students(courseId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courses',courseId)
            return [{**r,'id':str(r['id'])} for r in db.execute('SELECT * FROM "courseStudents" WHERE "courseId"=%s ORDER BY "studentNumber"',(courseId,))]
    @app.post('/v1/courses/{courseId}/students',status_code=201,tags=['학생'])
    def student_add(courseId:UUID,body:StudentInput,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courses',courseId);r=insert(db,'courseStudents',courseId=courseId,**body.model_dump());return {**r,'id':str(r['id'])}
    @app.put('/v1/students/{studentId}',tags=['학생'])
    def student_update(studentId:int,body:StudentInput,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courseStudents',studentId)
            r=db.execute('UPDATE "courseStudents" SET "studentNumber"=%s,name=%s,"githubId"=%s,"repositoryUrl"=%s WHERE id=%s RETURNING *',(body.studentNumber,body.name,body.githubId,body.repositoryUrl,studentId)).fetchone()
            return {**r,'id':str(r['id'])}
    @app.delete('/v1/students/{studentId}',status_code=204,tags=['학생'])
    def student_delete(studentId:int,user=Depends(owner)):
        with database.transaction(user) as db:one(db,'courseStudents',studentId);db.execute('DELETE FROM "courseStudents" WHERE id=%s',(studentId,))
        service.clean_files(user);return Response(status_code=204)
    @app.get('/v1/courses/{courseId}/rubrics',tags=['루브릭 MD'])
    def rubrics(courseId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courses',courseId)
            return db.execute('SELECT * FROM "rubricDocuments" WHERE "courseId"=%s ORDER BY "createdAt" DESC',(courseId,)).fetchall()
    def save_rubric(user,course,body,rubric_id=None):
        key,digest=service.files.write('rubrics',body.markdown.encode(),'.md')
        try:
            with database.transaction(user) as db:
                one(db,'courses',course)
                if rubric_id:
                    rubric=one(db,'rubricDocuments',rubric_id)
                    db.execute('SELECT id FROM "rubricDocuments" WHERE id=%s FOR UPDATE',(rubric_id,))
                    db.execute('UPDATE "rubricDocuments" SET title=%s WHERE id=%s',(body.title,rubric_id))
                else:rubric=insert(db,'rubricDocuments',courseId=course,title=body.title)
                num=db.execute('SELECT coalesce(max("versionNumber"),0)+1 AS n FROM "rubricVersions" WHERE "rubricDocumentId"=%s',(rubric['id'],)).fetchone()['n']
                v=insert(db,'rubricVersions',rubricDocumentId=rubric['id'],versionNumber=num,origin='professor',storageKey=key,contentHash=digest)
                return db.execute('UPDATE "rubricDocuments" SET "currentVersionId"=%s WHERE id=%s RETURNING *',(v['id'],rubric['id'])).fetchone()
        except Exception:service.files.delete(key);raise
    @app.post('/v1/courses/{courseId}/rubrics',status_code=201,tags=['루브릭 MD'])
    def rubric_add(courseId:UUID,body:RubricInput,user=Depends(owner)):return save_rubric(user,courseId,body)
    @app.put('/v1/rubrics/{rubricId}',tags=['루브릭 MD'])
    def rubric_update(rubricId:UUID,body:RubricInput,user=Depends(owner)):
        with database.transaction(user) as db:course=one(db,'rubricDocuments',rubricId)['courseId']
        return save_rubric(user,course,body,rubricId)
    @app.get('/v1/rubrics/{rubricId}',tags=['루브릭 MD'])
    def rubric_read(rubricId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            r=one(db,'rubricDocuments',rubricId);v=one(db,'rubricVersions',r['currentVersionId'])
            return {**r,'markdown':service.files.read(v['storageKey']).decode()}
    @app.delete('/v1/rubrics/{rubricId}',status_code=204,tags=['루브릭 MD'])
    def rubric_delete(rubricId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:one(db,'rubricDocuments',rubricId);db.execute('DELETE FROM "rubricDocuments" WHERE id=%s',(rubricId,))
        service.clean_files(user);return Response(status_code=204)
    @app.post('/v1/courses/{courseId}/runs',status_code=202,tags=['생성·검토'])
    def run_create(courseId:UUID,body:RunInput,idempotency_key:str=Header(min_length=8,max_length=128),user=Depends(owner)):
        return publish(service,user,service.create_run(user,courseId,body,idempotency_key))
    @app.get('/v1/courses/{courseId}/runs',tags=['생성·검토'])
    def runs(courseId:UUID,user=Depends(owner)):return service.runs(user,courseId)
    @app.get('/v1/runs/{runId}',tags=['생성·검토'])
    def run(runId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:return service.run(db,runId)
    @app.get('/v1/courses/{courseId}/events',response_class=StreamingResponse,tags=['실시간'])
    def events(courseId:UUID,user=Depends(owner),credentials=Depends(bearer)):
        with database.transaction(user) as db:one(db,'courses',courseId)
        def snapshot():
            owner(credentials)
            return service.runs(user,courseId)
        return StreamingResponse(stream(service,str(courseId),snapshot),media_type='text/event-stream',headers={'Cache-Control':'no-store'})
    @app.post('/v1/runs/{runId}/reviews',tags=['생성·검토'])
    def review(runId:UUID,body:ReviewInput,user=Depends(owner)):return publish(service,user,service.review(user,runId,body))
    @app.patch('/v1/runs/{runId}/draft',tags=['생성·검토'])
    def edit(runId:UUID,body:EditInput,user=Depends(owner)):
        with database.transaction(user) as db:
            db.execute('SELECT id FROM runs WHERE id=%s FOR UPDATE',(runId,));r=service.run(db,runId)
            if r['status']!='waitingReview' or r['revision']!=body.expectedRevision:fail(409,'최신 초안을 다시 확인하세요.')
            if len(json.dumps(body.draft))>200000:fail(422,'초안이 너무 큽니다.')
            old=one(db,'runRevisions',UUID(r['currentRevisionId']))
            required={'lecture':('main_slides',),'exam':('questions','rubrics'),'practice':('notebook',),'manager':('tasks',)}[r['taskType']]
            if not all(k in body.draft and isinstance(body.draft[k],type(old['content'][k])) for k in required):fail(422,'초안 구조를 유지해 주세요.')
            if r['taskType']=='exam':
                from apps.api.exam_review import prepare_edit
                try:prepare_edit(old['content'],body.draft)
                except (ValueError,KeyError,TypeError) as error:fail(422,str(error) if isinstance(error,ValueError) else '문항 형식을 확인하세요.')
            for field in ('trend_references','trend_search'):
                if field in old['content']:body.draft[field]=old['content'][field]
                else:body.draft.pop(field,None)
            rev=insert(db,'runRevisions',runId=runId,revisionNumber=r['revision']+1,origin='professor',createdBy=user,content=Jsonb(body.draft))
            db.execute('INSERT INTO "revisionSources" SELECT %s,"chunkId",rank,"retrievalScore","usageType" FROM "revisionSources" WHERE "revisionId"=%s',(rev['id'],old['id']))
            db.execute('UPDATE runs SET "currentRevisionId"=%s WHERE id=%s',(rev['id'],runId))
            return service.run(db,runId)
    @app.post('/v1/runs/{runId}/cancellations',tags=['생성·검토'])
    def cancel(runId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'runs',runId)
            db.execute('UPDATE runs SET status=\'cancelled\',"deleteYn"=true WHERE id=%s AND status IN (\'queued\',\'running\',\'waitingReview\')',(runId,))
            db.execute('UPDATE "runAttempts" SET status=\'cancelled\',"finishedAt"=now() WHERE "runId"=%s AND status IN (\'queued\',\'running\')',(runId,))
            return service.run(db,runId)
    @app.post('/v1/runs/{runId}/retries',tags=['생성·검토'])
    def retry(runId:UUID,body:RetryInput,user=Depends(owner)):
        with database.transaction(user) as db:
            db.execute('SELECT id FROM runs WHERE id=%s FOR UPDATE',(runId,));r=service.run(db,runId)
            if r['status']!='failed' or r['revision']!=body.expectedRevision:fail(409,'실패한 최신 작업만 재시도할 수 있습니다.')
            attempts=db.execute('SELECT * FROM "runAttempts" WHERE "runId"=%s ORDER BY "attemptNumber" DESC',(runId,)).fetchall()
            if sum(a['status']=='failed' for a in attempts)>=3:fail(409,'재시도 한도에 도달했습니다.')
            service.queue(db,runId,attempts[0]['phase']);result=service.run(db,runId)
        return publish(service,user,result)
    @app.delete('/v1/runs/{runId}',status_code=204,tags=['생성·검토'])
    def run_delete(runId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:one(db,'runs',runId);db.execute('DELETE FROM runs WHERE id=%s',(runId,))
        service.clean_files(user);return Response(status_code=204)
    @app.get('/v1/runs/{runId}/artifact',tags=['생성물'])
    def artifact(runId:UUID,user=Depends(owner)):
        data,ext=service.artifact(user,runId)
        with database.transaction(user) as db:filename=service.download_name(db,runId)
        return Response(data,media_type='application/octet-stream',headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})
    @app.get('/v1/runs/{runId}/exam-review-report',tags=['생성·검토'])
    def exam_review_report(runId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            r=one(db,'runs',runId)
            if r['taskType']!='exam':fail(422,'시험 작업만 조회할 수 있습니다.')
            from apps.api.exam_review import review_report
            revisions=db.execute('SELECT * FROM "runRevisions" WHERE "runId"=%s ORDER BY "revisionNumber"',(runId,)).fetchall()
            return {'markdown':review_report(revisions),'fileName':service.download_name(db,runId).replace('.md','_review-report.md')}
    @app.get('/v1/runs/{runId}/answer-key',tags=['생성물'])
    def exam_answer_key(runId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            r=one(db,'runs',runId)
            if r['taskType']!='exam' or r['status']!='succeeded':fail(409,'승인·생성이 완료된 시험만 다운로드할 수 있습니다.')
            from apps.api.exam_review import answer_key
            draft=one(db,'runRevisions',r['currentRevisionId'])['content']
            return {'markdown':answer_key(draft),'fileName':service.download_name(db,runId).replace('.md','_answer-key.md')}
    @app.get('/v1/courses/{courseId}/practice-references',tags=['실습 참고자료'])
    def practice_references(courseId:UUID,user=Depends(owner)):
        from .practice_references import options
        return options(service,user,courseId)
    @app.get('/v1/runs/{runId}/education-review',tags=['생성물'])
    def education_review(runId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'runs',runId);report=service.education_review(db,runId)
        if not report:fail(404,'이 결과물에는 저장된 교육 검토가 없습니다.')
        return report
    @app.get('/v1/courses/{courseId}/materials',tags=['생성물'])
    def materials(courseId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'courses',courseId)
            return db.execute('SELECT * FROM "generatedMaterials" WHERE "courseId"=%s AND "currentVersionId" IS NOT NULL ORDER BY "createdAt" DESC',(courseId,)).fetchall()
    @app.post('/v1/runs/{runId}/dispatches',tags=['생성·검토'])
    def dispatch(runId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:
            parent=service.run(db,runId)
            if parent['taskType']!='manager' or parent['status']!='succeeded':fail(409,'승인된 학기 계획만 실행할 수 있습니다.')
            tasks=parent['draft'].get('tasks',[])
            docs=service.documents(db,UUID(parent['courseId']))
        inputs=[]
        for n,task in enumerate(tasks):
            kind=task.get('task_type');week=task.get('week')
            if kind not in ('lecture','practice','exam'):fail(422,'프로젝트 평가는 학생과 루브릭을 선택해 별도로 생성하세요.')
            documents=[d['id'] for d in docs if week in d['weekNumbers']]
            inputs.append((n,RunInput(taskType=kind,topic=str(task.get('context') or task.get('subject') or parent['topic'])[:200],weekNumbers=[week],documentIds=documents,parentRunId=runId)))
        return [publish(service,user,service.create_run(user,UUID(parent['courseId']),body,f'plan-{runId}-{n}')) for n,body in inputs]
    @app.delete('/v1/materials/{materialId}',status_code=204,tags=['생성물'])
    def material_delete(materialId:UUID,user=Depends(owner)):
        with database.transaction(user) as db:one(db,'generatedMaterials',materialId);db.execute('DELETE FROM "generatedMaterials" WHERE id=%s',(materialId,))
        service.clean_files(user);return Response(status_code=204)
    @app.post('/v1/runs/{runId}/feedback',status_code=201,tags=['피드백'])
    def feedback(runId:UUID,body:FeedbackInput,user=Depends(owner)):
        with database.transaction(user) as db:
            one(db,'runs',runId)
            return db.execute('INSERT INTO feedback ("runId","userId",rating,comment) VALUES (%s,%s,%s,%s) ON CONFLICT ("runId","userId") DO UPDATE SET rating=excluded.rating,comment=excluded.comment RETURNING *',(runId,user,body.rating,body.comment)).fetchone()
    return app
