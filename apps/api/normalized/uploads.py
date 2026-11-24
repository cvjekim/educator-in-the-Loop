"""Authenticated chunked uploads preserve the 10MB limit on serverless hosts."""
from uuid import UUID,uuid4
from pathlib import Path
import psycopg
from fastapi import Depends,File,UploadFile
from pydantic import BaseModel,Field
from .service import one,fail

CHUNK_SIZE=3_000_000

class UploadInput(BaseModel):
    name:str=Field(min_length=1,max_length=255)
    byteSize:int=Field(ge=1,le=10_000_000)


def install_uploads(app,service,owner):
    @app.post('/v1/courses/{courseId}/document-uploads',tags=['강의 자료'],status_code=201)
    def begin(courseId:UUID,body:UploadInput,user=Depends(owner)):
        with service.database.transaction(user) as db:one(db,'courses',courseId)
        if Path(body.name).suffix.lower() not in ('.pdf','.pptx','.md','.txt','.ipynb'):fail(415,'지원하지 않는 파일 형식입니다.')
        with psycopg.connect(service.database.dsn,connect_timeout=15) as db:
            db.execute('DELETE FROM "educatorFiles".uploads WHERE "expiresAt"<now()')
            db.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',('upload:'+str(user),))
            if db.execute('SELECT count(*) FROM "educatorFiles".uploads WHERE "userId"=%s',(user,)).fetchone()[0]>=3:fail(429,'진행 중인 업로드를 완료하거나 취소해 주세요.')
            ident=uuid4()
            db.execute('INSERT INTO "educatorFiles".uploads (id,"userId","courseId",name,"byteSize") VALUES (%s,%s,%s,%s,%s)',(ident,user,courseId,body.name,body.byteSize))
        return {'id':ident,'chunkSize':CHUNK_SIZE}

    @app.put('/v1/document-uploads/{uploadId}/parts/{part}',tags=['강의 자료'])
    def part_upload(uploadId:UUID,part:int,file:UploadFile=File(...),user=Depends(owner)):
        data=file.file.read(CHUNK_SIZE+1)
        if not data or len(data)>CHUNK_SIZE:fail(413,'업로드 조각 크기가 올바르지 않습니다.')
        with psycopg.connect(service.database.dsn,connect_timeout=15) as db:
            row=db.execute('SELECT "nextPart","byteSize",octet_length(content) FROM "educatorFiles".uploads WHERE id=%s AND "userId"=%s AND "expiresAt">now() FOR UPDATE',(uploadId,user)).fetchone()
            if not row:fail(404,'업로드를 찾을 수 없습니다.')
            next_part,size,received=row
            expected=min(CHUNK_SIZE,size-received)
            if part!=next_part or len(data)!=expected:fail(409,'업로드 순서나 크기가 올바르지 않습니다. 다시 업로드해 주세요.')
            db.execute('UPDATE "educatorFiles".uploads SET content=content||%s,"nextPart"="nextPart"+1 WHERE id=%s',(data,uploadId))
        return {'receivedBytes':received+len(data)}

    @app.post('/v1/document-uploads/{uploadId}/complete',tags=['강의 자료'],status_code=201)
    def complete(uploadId:UUID,user=Depends(owner)):
        with psycopg.connect(service.database.dsn,connect_timeout=15) as db:
            row=db.execute('SELECT "courseId",name,"byteSize",content FROM "educatorFiles".uploads WHERE id=%s AND "userId"=%s AND "expiresAt">now() FOR UPDATE',(uploadId,user)).fetchone()
            if not row:fail(404,'업로드를 찾을 수 없습니다.')
            course,name,size,content=row
            if len(content)!=size:fail(409,'아직 업로드가 완료되지 않았습니다.')
            result=service.upload(user,name,bytes(content),course)
            db.execute('DELETE FROM "educatorFiles".uploads WHERE id=%s',(uploadId,))
        return result

    @app.delete('/v1/document-uploads/{uploadId}',status_code=204,tags=['강의 자료'])
    def abort(uploadId:UUID,user=Depends(owner)):
        with psycopg.connect(service.database.dsn,connect_timeout=15) as db:
            db.execute('DELETE FROM "educatorFiles".uploads WHERE id=%s AND "userId"=%s',(uploadId,user))
