"""Copy a private legacy snapshot into a local normalized account, without model calls.

The source snapshot and original-file map must stay outside public source control.
This importer deliberately accepts reviewed-pending non-project drafts only; it never
invents approvals, regenerates outputs, or silently discards unsupported records.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlparse
from uuid import UUID, uuid5, NAMESPACE_URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from psycopg.types.json import Jsonb
from apps.database.client import Database
from apps.api.normalized.files import Files
from apps.api.normalized.service import insert, sha


def plan_weeks(text):
    matches = list(re.finditer(r'^\s*(\d{1,2})\s*주차\s*[:：]\s*(.+)$', text, re.M))
    result = []
    for i, match in enumerate(matches):
        number = int(match[1])
        if not 1 <= number <= 52 or any(w['weekNumber'] == number for w in result):
            raise ValueError('Invalid or duplicated syllabus week')
        notes = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)].strip()
        result.append({'weekNumber': number, 'topic': match[2].strip()[:200], 'objectives': notes[:3000]})
    return result


def import_snapshot(database, files, data, originals, owner, legacy_owner, apply=False):
    if urlparse(database.dsn).hostname not in ('localhost', '127.0.0.1', '::1') or database.schema not in ('educatorDev',) and not database.schema.startswith('test_'):
        raise ValueError('Only a local development/test database is allowed')
    owner = UUID(str(owner))
    digest = sha(json.dumps(data, sort_keys=True, ensure_ascii=False).encode())
    courses = data['courses']; documents = data['documents']; runs = data['runs']
    if not courses or any(r['owner'] != legacy_owner for rows in data.values() for r in rows):
        raise ValueError('The snapshot must contain exactly the explicitly selected legacy owner')
    if data.get('feedback'):
        raise ValueError('Feedback requires a separate mapping; no rows imported')
    for r in runs:
        p = r['payload']
        if p['status'] != 'waiting_review' or p['task_type'] == 'project' or not p.get('draft') or p.get('reviews') or p.get('output'):
            raise ValueError('Unsupported historical run state; no rows imported')
    for d in documents:
        path = Path(originals[d['id']])
        if not path.is_file() or path.name != d['payload']['filename'] or path.stat().st_size != d['payload']['size']:
            raise ValueError('Original file missing or mismatched; no rows imported')
        if any(chunk.get('embedding') and len(chunk['embedding']) != 256 for chunk in d['content']['chunks']):
            raise ValueError('Unexpected embedding dimensions')
    weeks = {c['id']: plan_weeks(c['payload']['syllabus']) for c in courses}
    for r in runs:
        if r['state']['request']['week'] not in {w['weekNumber'] for w in weeks[r['course_id']]}:
            raise ValueError('Historical request week missing from syllabus')
    summary = {'courses':len(courses), 'sourceDocuments':len(documents), 'syllabi':sum(bool(c['payload']['syllabus']) for c in courses),
               'weeks':sum(map(len, weeks.values())), 'drafts':len(runs), 'rubrics':sum(bool(r['state']['request'].get('rubric_guidelines')) for r in runs)}
    created = []
    def write(category, content, suffix):
        key, checksum = files.write(category, content, suffix); created.append(key)
        return key, checksum
    try:
        with database.transaction(owner) as db:
            db.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ('legacy-import:'+str(owner),))
            if not db.execute('SELECT 1 FROM "oauthAccounts" WHERE "userId"=%s AND provider=\'google\'', (owner,)).fetchone():
                raise ValueError('Target must be an existing Google account')
            existing = [db.execute('SELECT id FROM courses WHERE id=%s', (UUID(c['id']),)).fetchone() for c in courses]
            if any(existing):
                markers = [db.execute('SELECT "generationConfig" FROM "runInputs" WHERE "runId"=%s', (UUID(r['id']),)).fetchone() for r in runs]
                if all(existing) and markers and all(m and m['generationConfig'].get('importDigest') == digest for m in markers):
                    return {**summary, 'status':'alreadyImported'}
                raise ValueError('Existing target records conflict; refusing overwrite')
            if not apply:
                return {**summary, 'status':'validated'}
            doc_map = {}; chunk_map = {}
            def document(ident, course, name, content, chunks, parser, mime):
                key, checksum = write('documents', content, Path(name).suffix)
                insert(db, 'documents', id=ident, ownerId=owner, title=name[:180])
                version = insert(db, 'documentVersions', documentId=ident, versionNumber=1, originalFileName=name,
                    storageKey=key, mimeType=mime, byteSize=len(content), contentHash=checksum)
                index = insert(db, 'documentIndexes', documentVersionId=version['id'], status='ready', parserVersion=parser,
                    chunkingConfig=Jsonb({'source':'legacyImport'}), embeddingModel='text-embedding-3-small', embeddingDimensions=256)
                for n, chunk in enumerate(chunks):
                    row = insert(db, 'documentChunks', documentIndexId=index['id'], chunkNumber=n, pageNumber=chunk['page'],
                        text=chunk['text'].replace('\x00',''), textHash=sha(chunk['text'].replace('\x00','').encode()), embedding=json.dumps(chunk['embedding']) if chunk.get('embedding') else None)
                    if chunk.get('chunk_id'): chunk_map[(str(ident), chunk['chunk_id'])] = row['id']
                db.execute('UPDATE documents SET "currentVersionId"=%s WHERE id=%s', (version['id'], ident))
                insert(db, 'courseDocuments', courseId=course, documentId=ident)
                doc_map[str(ident)] = (version['id'], index['id'])
                return version['id']
            for c in courses:
                p=c['payload']; ident=UUID(c['id'])
                insert(db, 'courses', id=ident, ownerId=owner, title=p['title'], syllabus=p['syllabus'], createdAt=p['created_at'])
                for w in weeks[c['id']]: insert(db, 'courseWeeks', courseId=ident, **w)
                if p['syllabus']:
                    # Legacy stored text, not a PDF. Keep it honestly as Markdown.
                    content=p['syllabus'].encode()
                    version=document(uuid5(NAMESPACE_URL,'legacy-syllabus:'+c['id']), ident, 'syllabus-imported.md', content,
                        [{'page':1,'text':p['syllabus']}], 'legacy-syllabus-text', 'text/markdown')
                    db.execute('UPDATE courses SET "syllabusVersionId"=%s WHERE id=%s', (version,ident))
            for d in documents:
                document(UUID(d['id']), UUID(d['course_id']), d['payload']['filename'], Path(originals[d['id']]).read_bytes(),
                    d['content']['chunks'], 'legacy-preserved-chunks-v1', 'application/pdf' if Path(originals[d['id']]).suffix.lower()=='.pdf' else 'application/octet-stream')
                assigned={r['state']['request']['week'] for r in runs if r['course_id']==d['course_id'] and d['id'] in r['state']['request']['document_ids']}
                for week in assigned: insert(db, 'courseDocumentWeeks', courseId=UUID(d['course_id']), documentId=UUID(d['id']), weekNumber=week)
            for r in runs:
                p=r['payload']; request=r['state']['request']; ident=UUID(r['id']); course=UUID(r['course_id'])
                sources=[]
                for citation in p['citations']:
                    chunk=chunk_map[(citation['document_id'], citation['chunk_id'])]
                    if chunk not in sources:sources.append(chunk)
                insert(db, 'runs', id=ident, courseId=course, requestedBy=owner, taskType=p['task_type'], topic=p['topic'], weekNumber=request['week'],
                    status='waitingReview', idempotencyKey='legacy:'+r['id'], requestHash=r['request_hash'], createdAt=p['created_at'])
                config={'weekNumbers':[request['week']], 'weeksSnapshot':[w for w in weeks[r['course_id']] if w['weekNumber']==request['week']],
                    'sourceChunkIds':list(map(str,sources)), 'parameters':[{'questionType':v['question_type'],'count':v['count']} for v in request.get('parameters',[])]}
                insert(db, 'runInputs', runId=ident, guidelines=request.get('guidelines',''), syllabusSnapshot=r['state'].get('syllabus',''),
                    taskConfig=Jsonb(config), generationConfig=Jsonb({'mode':p['mode'],'importDigest':digest,'importSource':'legacySnapshot'}))
                for did in request['document_ids']:
                    version,index=doc_map[did];insert(db,'runDocuments',runId=ident,documentVersionId=version,documentIndexId=index)
                rev=insert(db,'runRevisions',runId=ident,revisionNumber=p['revision'],origin='ai',content=Jsonb(p['draft']),createdAt=p['created_at'])
                db.execute('UPDATE runs SET "currentRevisionId"=%s WHERE id=%s',(rev['id'],ident))
                for rank,chunk in enumerate(sources,1):insert(db,'revisionSources',revisionId=rev['id'],chunkId=chunk,rank=rank,usageType='lectureMain' if p['task_type']=='lecture' else 'reference')
                rubric=request.get('rubric_guidelines','').strip()
                if rubric:
                    key,checksum=write('rubrics',rubric.encode(),'.md')
                    rub=insert(db,'rubricDocuments',courseId=course,title=(p['topic']+' 루브릭')[:180])
                    version=insert(db,'rubricVersions',rubricDocumentId=rub['id'],versionNumber=1,origin='professor',storageKey=key,contentHash=checksum)
                    db.execute('UPDATE "rubricDocuments" SET "currentVersionId"=%s WHERE id=%s',(version['id'],rub['id']))
        return {**summary,'status':'imported'}
    except Exception:
        for key in created:files.delete(key)
        raise


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env.development', override=True)
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True,type=Path);parser.add_argument('--original-map',required=True,type=Path)
    parser.add_argument('--owner-id',required=True,type=UUID);parser.add_argument('--legacy-owner',required=True)
    parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    database=Database(os.environ['DATABASE_URL'],os.environ['DATABASE_SCHEMA'])
    files=Files(os.environ.get('PRIVATE_STORAGE_ROOT',str(ROOT/'artifacts/development/files')))
    print(json.dumps(import_snapshot(database,files,json.loads(args.snapshot.read_text()),json.loads(args.original_map.read_text()),args.owner_id,args.legacy_owner,args.apply)))

if __name__=='__main__':main()
