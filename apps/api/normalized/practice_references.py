"""Same-course, version-pinned generated references for notebook revision."""
from .service import one,fail,sha

def options(service,user,course):
 with service.database.transaction(user) as db:
  one(db,'courses',course)
  rows=db.execute('''SELECT r.id,r.topic,r."weekNumber",r.status,r."currentRevisionId",v."revisionNumber"
   FROM runs r JOIN "runRevisions" v ON v.id=r."currentRevisionId"
   WHERE r."courseId"=%s AND r."taskType"='lecture' AND NOT r."deleteYn"
   AND r.status IN ('waitingReview','succeeded') ORDER BY r."createdAt" DESC''',(course,)).fetchall()
  result=[]
  for r in rows:
   result.append({'kind':'draft','id':r['currentRevisionId'],'title':r['topic'],'weekNumber':r['weekNumber'],'version':r['revisionNumber'],'label':'강의 초안 (사실 검증 필요)'})
   materials=db.execute('''SELECT m."currentVersionId",v."versionNumber" FROM "generatedMaterials" m
    JOIN "generatedMaterialVersions" v ON v.id=m."currentVersionId" JOIN "runRevisions" rev ON rev.id=v."runRevisionId"
    WHERE rev."runId"=%s AND m."materialType"='lectureNote' ''',(r['id'],)).fetchall()
   for m in materials:result.append({'kind':'material','id':m['currentVersionId'],'title':r['topic'],'weekNumber':r['weekNumber'],'version':m['versionNumber'],'label':'생성된 강의자료'})
  return result

def snapshot(service,db,course,selections):
 result=[];total=0
 for selection in selections:
  if selection.kind=='draft':
   revision=one(db,'runRevisions',selection.id)
   r=one(db,'runs',revision['runId'])
   content=revision['content'];text=str(content.get('intro_slide',''))+'\n\n'+'\n\n'.join(content.get('main_slides',[]))
   version=revision['revisionNumber']
  else:
   v=one(db,'generatedMaterialVersions',selection.id);m=one(db,'generatedMaterials',v['generatedMaterialId'])
   revision=one(db,'runRevisions',v['runRevisionId']);r=one(db,'runs',revision['runId'])
   if m['courseId']!=course or m['materialType']!='lectureNote':fail(422,'같은 강의의 강의자료만 선택하세요.')
   a=db.execute('SELECT "storageKey" FROM artifacts WHERE "generatedMaterialVersionId"=%s AND "fileRole"=\'main\' AND format=\'md\'',(v['id'],)).fetchone()
   if not a:fail(404,'참고할 강의자료 파일이 없습니다.')
   text=service.files.read(a['storageKey']).decode();version=v['versionNumber']
  if r['courseId']!=course or r['taskType']!='lecture' or r['deleteYn'] or r['status'] not in ('waitingReview','succeeded'):fail(422,'사용 가능한 같은 강의 자료를 선택하세요.')
  total+=len(text)
  if total>60000:fail(422,'선택한 참고자료가 너무 큽니다. 자료 수를 줄여 주세요.')
  result.append({'kind':selection.kind,'id':str(selection.id),'version':version,'title':r['topic'],'contentHash':sha(text.encode()),'text':text})
 return result
