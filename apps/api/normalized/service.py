import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from uuid import UUID,uuid4

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from apps.api import retrieval
from .files import Files

ROOT=Path(__file__).resolve().parents[3]

def fail(status,message):raise HTTPException(status,{'code':'prototype_error','message':message})
def one(db,table,ident):
    # table names originate exclusively in server code.
    row=db.execute(f'SELECT * FROM "{table}" WHERE id=%s',(ident,)).fetchone()
    if not row:fail(404,'항목을 찾을 수 없습니다.')
    return row

def insert(db,table,**values):
    from psycopg import sql
    fields=list(values)
    return db.execute(sql.SQL('INSERT INTO {} ({}) VALUES ({}) RETURNING *').format(sql.Identifier(table),
        sql.SQL(',').join(map(sql.Identifier,fields)),sql.SQL(',').join(sql.Placeholder() for _ in fields)),list(values.values())).fetchone()

def sha(data):return hashlib.sha256(data).hexdigest()

def parse_file(name,content,*,syllabus=False):
    suffix=Path(name).suffix.lower()
    if suffix not in ('.pdf','.pptx','.md','.txt','.ipynb'):fail(415,'PDF, PPTX, MD, TXT, IPYNB 파일을 선택하세요.')
    if not content or len(content)>10_000_000:fail(413,'파일은 10MB 이하이며 비어 있지 않아야 합니다.')
    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/('input'+suffix);path.write_bytes(content)
        try:
            result=subprocess.run([sys.executable,str(ROOT/'apps/api/parse_document.py'),str(path),*(['--syllabus'] if syllabus else [])],capture_output=True,text=True,timeout=30,
                env={'PATH':os.environ.get('PATH',''),'PYTHONPATH':os.pathsep.join(dict.fromkeys([str(ROOT),*sys.path])),'PYTHONDONTWRITEBYTECODE':'1'})
            if result.returncode:fail(422,'문서를 읽을 수 없습니다. 파일 형식이나 OCR 필요 여부를 확인하세요.')
            data=json.loads(result.stdout)
        except subprocess.TimeoutExpired:fail(422,'문서 분석 시간이 초과되었습니다.')
    data['pages']=[p.replace('\x00','') for p in data['pages']]
    if not any(p.strip() for p in data['pages']):fail(422,'추출 가능한 본문이 없습니다. 텍스트가 포함된 파일을 사용하세요.')
    return data

class Service:
    def __init__(self,database,files,mode='real',semantic=False):
        self.database=database;self.files=files;self.mode=mode;self.semantic=semantic
        self.dsn=database.dsn;self.event_prefix='educator_'

    def clean_files(self,user):
        with self.database.transaction(user) as db:
            for job in db.execute('SELECT * FROM "deletionJobs" WHERE status=\'pending\' FOR UPDATE SKIP LOCKED').fetchall():
                self.files.delete(job['storageKey'])
                db.execute('UPDATE "deletionJobs" SET status=\'completed\',"completedAt"=now() WHERE id=%s',(job['id'],))

    def documents(self,db,course=None):
        sql='''SELECT d.id,d.title,d."currentVersionId",v."originalFileName",v."byteSize",v."mimeType",
            i.id AS "indexId",i.status,(SELECT max("pageNumber") FROM "documentChunks" WHERE "documentIndexId"=i.id) AS pages
            FROM documents d JOIN "documentVersions" v ON v.id=d."currentVersionId"
            JOIN "documentIndexes" i ON i."documentVersionId"=v.id AND i.status='ready'
            WHERE d."deletedAt" IS NULL'''
        args=[]
        if course:
            one(db,'courses',course)
            sql+=' AND EXISTS (SELECT 1 FROM "courseDocuments" cd WHERE cd."documentId"=d.id AND cd."courseId"=%s)';args=[course]
        rows=db.execute(sql+' ORDER BY d."createdAt" DESC',args).fetchall()
        for row in rows:
            row['weekNumbers']=[r['weekNumber'] for r in db.execute('SELECT "weekNumber" FROM "courseDocumentWeeks" WHERE "courseId"=%s AND "documentId"=%s ORDER BY "weekNumber"',(course,row['id'])).fetchall()] if course else []
        return rows

    def upload(self,user,name,content,course=None):
        name=Path(name.replace('\\','/')).name[:180]
        data=parse_file(name,content)
        document_id=uuid4();indexed=retrieval.index_document(str(document_id),data,self.semantic)
        key,digest=self.files.write('documents',content,Path(name).suffix.lower())
        try:
            with self.database.transaction(user) as db:
                if course:one(db,'courses',course)
                insert(db,'documents',id=document_id,ownerId=user,title=name)
                version=insert(db,'documentVersions',documentId=document_id,versionNumber=1,originalFileName=name,storageKey=key,
                    mimeType={'.pdf':'application/pdf','.ipynb':'application/x-ipynb+json'}.get(Path(name).suffix.lower(),'application/octet-stream'),byteSize=len(content),contentHash=digest)
                index=insert(db,'documentIndexes',documentVersionId=version['id'],status='ready',parserVersion='isolated-parser-v1',
                    chunkingConfig=Jsonb({'size':1400,'overlap':200}),embeddingModel=retrieval.MODEL,embeddingDimensions=256)
                for n,chunk in enumerate(indexed['chunks']):
                    insert(db,'documentChunks',documentIndexId=index['id'],chunkNumber=n,pageNumber=chunk['page'],text=chunk['text'],textHash=sha(chunk['text'].encode()),embedding=json.dumps(chunk['embedding']) if chunk.get('embedding') else None)
                db.execute('UPDATE documents SET "currentVersionId"=%s WHERE id=%s',(version['id'],document_id))
                if course:insert(db,'courseDocuments',courseId=course,documentId=document_id)
            return next(r for r in self.library(user,course) if r['id']==document_id)
        except Exception:
            self.files.delete(key);raise

    def library(self,user,course=None):
        with self.database.transaction(user) as db:return self.documents(db,course)

    def set_weeks(self,db,course,document,weeks):
        valid={r['weekNumber'] for r in db.execute('SELECT "weekNumber" FROM "courseWeeks" WHERE "courseId"=%s',(course,))}
        if len(weeks)!=len(set(weeks)) or not set(weeks)<=valid:fail(422,'등록된 주차를 중복 없이 선택하세요.')
        if not db.execute('SELECT 1 FROM "courseDocuments" WHERE "courseId"=%s AND "documentId"=%s',(course,document)).fetchone():fail(404,'강의에 연결되지 않은 자료입니다.')
        db.execute('DELETE FROM "courseDocumentWeeks" WHERE "courseId"=%s AND "documentId"=%s',(course,document))
        for week in weeks:insert(db,'courseDocumentWeeks',courseId=course,documentId=document,weekNumber=week)

    def syllabus(self,db,course):
        c=one(db,'courses',course)
        plan=db.execute('SELECT * FROM "coursePlans" WHERE "courseId"=%s',(course,)).fetchone()
        if plan:
            from .syllabus import render_syllabus
            weeks=db.execute('SELECT * FROM "courseWeeks" WHERE "courseId"=%s ORDER BY "weekNumber"',(course,)).fetchall()
            return render_syllabus(plan,weeks)
        if not c['syllabusVersionId']:return c['syllabus']
        v=one(db,'documentVersions',c['syllabusVersionId'])
        data=parse_file(v['originalFileName'],self.files.read(v['storageKey']))
        text='\n\n'.join(data['pages'])
        if len(text)>60000:fail(422,'강의계획서 본문이 너무 깁니다. 강의계획서만 포함된 파일을 선택하세요.')
        return text

    def records(self,db,course,ids):
        docs={r['id']:r for r in self.documents(db,course)}
        if not set(ids)<=docs.keys():fail(404,'선택한 자료를 이 강의에서 찾을 수 없습니다.')
        records=[]
        for ident in ids:
            meta=docs[ident]
            rows=db.execute('SELECT id,"pageNumber",text,embedding::text FROM "documentChunks" WHERE "documentIndexId"=%s ORDER BY "chunkNumber"',(meta['indexId'],)).fetchall()
            chunks=[{'chunk_id':str(r['id']),'page':r['pageNumber'],'text':r['text'],**({'embedding':json.loads(r['embedding'])} if r['embedding'] else {})} for r in rows]
            records.append(({'id':str(ident),'filename':meta['originalFileName']},{'chunks':chunks,'embedding_model':retrieval.MODEL,'embedding_dimensions':256}))
        return docs,records

    def search(self,user,course,body):
        vector=retrieval.embed([body.query])[0] if self.semantic else None
        with self.database.transaction(user) as db:
            docs=self.documents(db,course)
            ids=body.documentIds or [d['id'] for d in docs]
            if body.weekNumbers:
                eligible={d['id'] for d in docs if set(d['weekNumbers'])&set(body.weekNumbers)}
                if body.documentIds and not set(ids)<=eligible:fail(422,'선택한 주차 범위 밖의 자료입니다.')
                ids=[d for d in ids if d in eligible]
            _,records=self.records(db,course,ids)
            return {'results':self.citations(retrieval.search(records,body.query,body.limit,self.semantic,vector)), 'retrieval':'hybrid' if self.semantic else 'keyword'}

    @staticmethod
    def citations(rows):
        return [{'chunkId':r['chunk_id'],'documentId':r['document_id'],'filename':r['filename'],'page':r['page'],'text':r['text']} for r in rows]

    def queue(self,db,run,phase):
        number=db.execute('SELECT coalesce(max("attemptNumber"),0)+1 AS n FROM "runAttempts" WHERE "runId"=%s',(run,)).fetchone()['n']
        attempt=insert(db,'runAttempts',runId=run,attemptNumber=number,phase=phase)
        insert(db,'jobOutbox',runId=run,eventKey=str(attempt['id']))
        db.execute('UPDATE runs SET status=\'queued\' WHERE id=%s',(run,))
        db.execute("SELECT pg_notify('educator_jobs',%s)",(str(run),))

    def create_run(self,user,course,body,key):
        digest=sha(body.model_dump_json().encode())
        with self.database.transaction(user) as db:
            c=one(db,'courses',course)
            db.execute('SELECT id FROM courses WHERE id=%s FOR UPDATE',(course,))
            prior=db.execute('SELECT id,"requestHash" FROM runs WHERE "courseId"=%s AND "idempotencyKey"=%s',(course,key)).fetchone()
            if prior:
                if prior['requestHash']!=digest:fail(409,'같은 요청 키에 다른 입력을 사용할 수 없습니다.')
                return self.run(db,prior['id'])
            if body.parentRunId:
                parent=one(db,'runs',body.parentRunId)
                if parent['courseId']!=course or parent['taskType']!='manager' or parent['status']!='succeeded':fail(409,'승인된 학기 계획에만 하위 작업을 연결할 수 있습니다.')
            weeks=db.execute('SELECT * FROM "courseWeeks" WHERE "courseId"=%s ORDER BY "weekNumber"',(course,)).fetchall()
            by_week={w['weekNumber']:w for w in weeks}
            if not set(body.weekNumbers)<=by_week.keys():fail(422,'등록된 주차에서 선택하세요.')
            if body.taskType=='lecture' and (len(body.weekNumbers)!=1 or not (c['syllabusVersionId'] or db.execute('SELECT 1 FROM "coursePlans" WHERE "courseId"=%s',(course,)).fetchone())):fail(422,'강의계획서와 한 개의 등록된 주차를 선택하세요.')
            if body.taskType=='exam' and not body.weekNumbers:fail(422,'출제할 주차를 하나 이상 선택하세요.')
            config=body.model_dump(mode='json');sources=[];syllabus='';versions=[]
            if body.taskType!='project':
                syllabus=self.syllabus(db,course)
                docs,records=self.records(db,course,body.documentIds)
                config['weeksSnapshot']=[jsonable_encoder(by_week[w]) for w in body.weekNumbers]
                if body.taskType in ('lecture','exam'):
                    if not records:fail(422,'선택한 주차의 강의 자료를 선택하세요.')
                    if any(not set(docs[i]['weekNumbers'])&set(body.weekNumbers) for i in body.documentIds):fail(422,'선택한 주차에 등록된 자료만 사용할 수 있습니다.')
                    for week in body.weekNumbers:
                        subset=[r for r in records if week in docs[UUID(r[0]['id'])]['weekNumbers']]
                        query=by_week[week]['topic']+' '+body.topic+' '+body.guidelines
                        evidence=retrieval.search(subset,query,8,self.semantic)
                        if not evidence:fail(422,f'{week}주차 자료에서 관련 근거를 찾지 못했습니다. 자료나 주제를 확인하세요.')
                        sources.extend(evidence)
                    sources=list({s['chunk_id']:s for s in sources}.values())
                if body.taskType=='practice':
                    notebooks=[docs[i] for i in body.documentIds if docs[i]['originalFileName'].lower().endswith('.ipynb')]
                    if len(notebooks)>1:fail(422,'수정할 실습 노트북은 한 개만 선택하세요.')
                    if notebooks:config['notebookVersionId']=str(notebooks[0]['currentVersionId'])
                    from .practice_references import snapshot
                    refs=snapshot(self,db,course,body.referenceSources)
                    if not records and not refs:fail(422,'참고할 강의 자료나 강의 초안·생성 자료를 선택하세요.')
                    config['referenceSnapshots']=refs
                    config['practiceReferenceText']='\n\n'.join(f"[{r['kind']} v{r['version']}: {r['title']}]\n{r['text']}" for r in refs)
                    sources=retrieval.search(records,body.topic+' '+body.guidelines,8,self.semantic) if records else []
                if body.taskType=='manager' and not syllabus:fail(422,'강의계획서를 먼저 등록하세요.')
                for i in body.documentIds:versions.append((docs[i]['currentVersionId'],docs[i]['indexId']))
                if c['syllabusVersionId'] and all(v[0]!=c['syllabusVersionId'] for v in versions):
                    index=db.execute('SELECT id FROM "documentIndexes" WHERE "documentVersionId"=%s AND status=\'ready\'',(c['syllabusVersionId'],)).fetchone()
                    if not index:fail(422,'강의계획서 색인이 준비되지 않았습니다.')
                    versions.append((c['syllabusVersionId'],index['id']))
                config['sourceChunkIds']=[s['chunk_id'] for s in sources]
            else:
                if not body.courseStudentId or not body.rubricVersionId:fail(422,'학생과 저장된 루브릭을 선택하세요.')
                student=one(db,'courseStudents',body.courseStudentId);rv=one(db,'rubricVersions',body.rubricVersionId)
                rubric=one(db,'rubricDocuments',rv['rubricDocumentId'])
                if student['courseId']!=course or rubric['courseId']!=course or not student['repositoryUrl']:fail(422,'학생 저장소와 루브릭의 강의를 확인하세요.')
                if body.guidelines:fail(422,'평가 요청사항은 루브릭 MD에 저장해 주세요.')
            run=insert(db,'runs',courseId=course,requestedBy=user,taskType=body.taskType,topic=body.topic,
                weekNumber=body.weekNumbers[0] if len(body.weekNumbers)==1 else None,idempotencyKey=key,requestHash=digest,parentRunId=body.parentRunId)
            insert(db,'runInputs',runId=run['id'],guidelines=body.guidelines if body.taskType!='project' else '',syllabusSnapshot=syllabus,
                taskConfig=Jsonb(config if body.taskType!='project' else {}),generationConfig=Jsonb({'mode':self.mode}))
            if body.taskType=='project':insert(db,'evaluationRuns',runId=run['id'],courseStudentId=student['id'],rubricVersionId=rv['id'],repositoryUrl=student['repositoryUrl'])
            for version,index in versions:insert(db,'runDocuments',runId=run['id'],documentVersionId=version,documentIndexId=index)
            self.queue(db,run['id'],'evaluate' if body.taskType=='project' else 'draft')
            return self.run(db,run['id'])

    def run(self,db,ident):
        r=one(db,'runs',ident);inputs=db.execute('SELECT * FROM "runInputs" WHERE "runId"=%s',(ident,)).fetchone()
        revision=one(db,'runRevisions',r['currentRevisionId']) if r['currentRevisionId'] else None
        attempt=db.execute('SELECT * FROM "runAttempts" WHERE "runId"=%s ORDER BY "attemptNumber" DESC LIMIT 1',(ident,)).fetchone()
        sources=[]
        if revision:
            sources=db.execute('''SELECT ch.id AS "chunkId",v."documentId",v."originalFileName" AS filename,ch."pageNumber" AS page,ch.text
                FROM "revisionSources" s JOIN "documentChunks" ch ON ch.id=s."chunkId" JOIN "documentIndexes" i ON i.id=ch."documentIndexId"
                JOIN "documentVersions" v ON v.id=i."documentVersionId" WHERE s."revisionId"=%s ORDER BY s.rank''',(revision['id'],)).fetchall()
        evaluations=db.execute('SELECT id,"versionNumber","fileName" FROM "evaluationDrafts" WHERE "runId"=%s ORDER BY "versionNumber" DESC',(ident,)).fetchall()
        return jsonable_encoder({**r,'revision':revision['revisionNumber'] if revision else (evaluations[0]['versionNumber'] if evaluations else 0),
            'draft':revision['content'] if revision else None,'citations':sources,'mode':inputs['generationConfig']['mode'],
            'error':attempt['errorCode'] if attempt else None,'weekNumbers':inputs['taskConfig'].get('weekNumbers',[]),
            'educationReview':self.education_review(db,ident),
            'downloadFileName':self.download_name(db,ident),
            'outputFormat':'ipynb' if r['taskType']=='practice' else 'md','evaluationDrafts':evaluations,
            'childIds':[x['id'] for x in db.execute('SELECT id FROM runs WHERE "parentRunId"=%s AND NOT "deleteYn"',(ident,))]})

    def runs(self,user,course):
        with self.database.transaction(user) as db:
            one(db,'courses',course)
            return [self.run(db,r['id']) for r in db.execute('SELECT id FROM runs WHERE "courseId"=%s AND NOT "deleteYn" ORDER BY "createdAt" DESC',(course,)).fetchall()]

    def review(self,user,ident,body):
        with self.database.transaction(user) as db:
            db.execute('SELECT id FROM runs WHERE id=%s FOR UPDATE',(ident,));r=self.run(db,ident)
            if r['status']!='waitingReview' or r['revision']!=body.expectedRevision:fail(409,'초안이 변경되었습니다. 최신 버전을 확인하세요.')
            if body.decision=='revise' and not body.feedback:fail(422,'수정 요청을 입력하세요.')
            if r['taskType']=='exam' and body.decision=='approve':
                from apps.api.exam_review import check_approval
                content=one(db,'runRevisions',UUID(r['currentRevisionId']))['content']
                try:check_approval(content)
                except ValueError as error:fail(422,str(error))
            insert(db,'reviews',revisionId=r['currentRevisionId'],reviewerId=user,decision=body.decision,feedback=body.feedback)
            self.queue(db,ident,'finalize' if body.decision=='approve' else 'revise')
            return self.run(db,ident)

    def education_review(self,db,ident):
        row=db.execute('SELECT v."educationReview" FROM "generatedMaterialVersions" v JOIN "runRevisions" rev ON rev.id=v."runRevisionId" WHERE rev."runId"=%s ORDER BY v."createdAt" DESC LIMIT 1',(ident,)).fetchone()
        return row['educationReview'] if row else None

    def download_name(self,db,ident):
        r=one(db,'runs',ident)
        inputs=db.execute('SELECT "taskConfig" FROM "runInputs" WHERE "runId"=%s',(ident,)).fetchone()
        weeks=inputs['taskConfig'].get('weekNumbers',[]) or ([r['weekNumber']] if r['weekNumber'] else [])
        revision=one(db,'runRevisions',r['currentRevisionId']) if r['currentRevisionId'] else None
        artifact=db.execute('SELECT v."createdAt",v."versionNumber" FROM "generatedMaterialVersions" v JOIN "runRevisions" rev ON rev.id=v."runRevisionId" WHERE rev."runId"=%s ORDER BY v."createdAt" DESC LIMIT 1',(ident,)).fetchone()
        stamp=(artifact['createdAt'] if artifact else r['createdAt']).strftime('%Y%m%d')
        # Courses currently have no institutional course-code field; use stable course ID.
        code=str(r['courseId'])
        week='-'.join(str(w).zfill(2) for w in weeks) or 'all'
        version=artifact['versionNumber'] if artifact else (revision['revisionNumber'] if revision else 1)
        ext='ipynb' if r['taskType']=='practice' else 'md'
        return f"{code}_week{week}_{r['taskType']}_v{version}_{stamp}_{str(ident)[:8]}.{ext}"

    def artifact(self,user,ident):
        with self.database.transaction(user) as db:
            r=one(db,'runs',ident)
            if r['status']!='succeeded':fail(409,'완료된 결과만 다운로드할 수 있습니다.')
            if r['taskType']=='project':
                file=db.execute('SELECT "storageKey" FROM "evaluationDrafts" WHERE "runId"=%s ORDER BY "versionNumber" DESC LIMIT 1',(ident,)).fetchone()
            else:
                file=db.execute('''SELECT a."storageKey" FROM artifacts a JOIN "generatedMaterialVersions" v ON v.id=a."generatedMaterialVersionId"
                    JOIN "runRevisions" rev ON rev.id=v."runRevisionId" WHERE rev."runId"=%s AND a."fileRole"='main' ORDER BY v."createdAt" DESC LIMIT 1''',(ident,)).fetchone()
            if not file:fail(404,'저장된 파일을 찾을 수 없습니다.')
            return self.files.read(file['storageKey']),('ipynb' if r['taskType']=='practice' else 'md')
