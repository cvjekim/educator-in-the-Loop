import {createClient,type Client,type Course,type Document,type Run,type RunInput} from './api'
import {readRunEvents} from './runEvents'
export type Week={weekNumber:number;topic:string;objectives:string;content?:string}
export type Plan={syllabusVersionId:string|null;weeks:Week[];goals?:string;mainTextbooks?:string;supplementaryTextbooks?:string;revision?:number;saved?:boolean}
export type LibraryDocument={id:string;title:string;currentVersionId:string;originalFileName:string;byteSize:number;pages:number;weekNumbers:number[]}
export type Student={id:string;studentNumber:string;name:string;githubId:string|null;repositoryUrl:string|null}
export type Rubric={id:string;title:string;currentVersionId:string;markdown?:string}
export type ReferenceSelection={kind:'draft'|'material';id:string}
export type PracticeReference=ReferenceSelection&{title:string;weekNumber:number|null;version:number;label:string}
type NormalRun={educationReview?:Run['educationReview'];downloadFileName:string;weekNumbers:number[];id:string;courseId:string;taskType:Run['task_type'];topic:string;status:string;revision:number;mode:'real'|'demo';draft:Record<string,unknown>|null;citations:{chunkId:string;documentId:string;filename:string;page:number;text:string}[];outputFormat:string;error:string|null;createdAt:string;childIds:string[]}
function run(r:NormalRun):Run{return {educationReview:r.educationReview,downloadFileName:r.downloadFileName,weekNumbers:r.weekNumbers,id:r.id,course_id:r.courseId,task_type:r.taskType,topic:r.topic,status:r.status==='waitingReview'?'waiting_review':r.status,revision:r.revision,mode:r.mode,draft:r.draft,citations:r.citations.map(c=>({...c,document_id:c.documentId})),output:null,output_format:r.outputFormat,error:r.error,created_at:r.createdAt,child_ids:r.childIds}}
export type NormalClient=Client&{
 examReport:(id:string)=>Promise<{markdown:string;fileName:string}>
 examKey:(id:string)=>Promise<{markdown:string;fileName:string}>
 normalized:true
 practiceReferences:(course:string)=>Promise<PracticeReference[]>
 plan:(course:string)=>Promise<Plan>
 savePlan:(course:string,plan:Plan)=>Promise<Plan>
 library:()=>Promise<LibraryDocument[]>
 courseDocuments:(course:string)=>Promise<LibraryDocument[]>
 attach:(course:string,documentId:string)=>Promise<unknown>
 unlink:(course:string,documentId:string)=>Promise<void>
 setDocumentWeeks:(course:string,documentId:string,weekNumbers:number[])=>Promise<unknown>
 syllabusPreview:(documentId:string)=>Promise<{documentVersionId:string;text:string;suggestedWeeks:Week[];suggestedPlan:Pick<Plan,'goals'|'mainTextbooks'|'supplementaryTextbooks'|'weeks'>}>
 students:(course:string)=>Promise<Student[]>
 saveStudent:(course:string,student:Omit<Student,'id'>,id?:string)=>Promise<Student>
 deleteStudent:(id:string)=>Promise<void>
 rubrics:(course:string)=>Promise<Rubric[]>
 readRubric:(id:string)=>Promise<Rubric>
 saveRubric:(course:string,title:string,markdown:string,id?:string)=>Promise<Rubric>
 deleteRubric:(id:string)=>Promise<void>
 updateCourse:(course:string,title:string,syllabus:string)=>Promise<Course>
 deleteRun:(id:string)=>Promise<void>
}
export function normalizedClient(base:string,token:string):NormalClient{
  const legacy=createClient(base,token)
  async function request<T>(path:string,method='GET',body?:unknown):Promise<T>{
    const response=await fetch(base.replace(/\/$/,'')+'/v1'+path,{method,headers:{Authorization:`Bearer ${token}`,...(body instanceof FormData?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:body instanceof FormData?body:JSON.stringify(body)})
    if(!response.ok){const e=await response.json().catch(()=>({}));throw new Error(e.message||'처리하지 못했습니다. 다시 시도해 주세요.')}
    return response.status===204?undefined as T:response.json()
  }
  const mapDoc=(d:LibraryDocument,course:string):Document=>({id:d.id,course_id:course,filename:d.originalFileName,size:d.byteSize,pages:d.pages,status:'ready'})
  const mapCourse=(c:Record<string,string>):Course=>({id:c.id,title:c.title,syllabus:c.syllabus,created_at:c.createdAt})
  return {...legacy,normalized:true,
    practiceReferences:course=>request(`/courses/${course}/practice-references`),
    courses:async()=>(await request<Record<string,string>[]>('/courses')).map(mapCourse),
    createCourse:async(title,syllabus)=>mapCourse(await request('/courses','POST',{title,syllabus})),
    updateCourse:async(c,title,syllabus)=>mapCourse(await request(`/courses/${c}`,'PATCH',{title,syllabus})),
    documents:async c=>(await request<LibraryDocument[]>(`/courses/${c}/documents`)).map(d=>mapDoc(d,c)),
    upload:async(c,file)=>{
      if(file.size>3_000_000&&base.startsWith('https://')){
        const upload=await request<{id:string;chunkSize:number}>(`/courses/${c}/document-uploads`,'POST',{name:file.name,byteSize:file.size})
        try{
          for(let start=0,part=0;start<file.size;start+=upload.chunkSize,part++){
            const body=new FormData();body.append('file',file.slice(start,start+upload.chunkSize),'part')
            await request(`/document-uploads/${upload.id}/parts/${part}`,'PUT',body)
          }
          return mapDoc(await request(`/document-uploads/${upload.id}/complete`,'POST'),c)
        }catch(error){await request(`/document-uploads/${upload.id}`,'DELETE').catch(()=>{});throw error}
      }
      const body=new FormData();body.append('file',file);return mapDoc(await request(`/courses/${c}/documents`,'POST',body),c)
    },
    library:()=>request('/documents'),courseDocuments:c=>request(`/courses/${c}/documents`),
    plan:c=>request(`/courses/${c}/plan`),savePlan:(c,p)=>request(`/courses/${c}/plan`,'PUT',{syllabusVersionId:p.syllabusVersionId,goals:p.goals||'',mainTextbooks:p.mainTextbooks||'',supplementaryTextbooks:p.supplementaryTextbooks||'',expectedRevision:p.revision??0,weeks:p.weeks.map(w=>({weekNumber:w.weekNumber,topic:w.topic,objectives:w.objectives,content:w.content||''}))}),
    attach:(c,documentId)=>request(`/courses/${c}/document-links`,'POST',{documentId}),
    unlink:(c,d)=>request(`/courses/${c}/documents/${d}`,'DELETE'),
    setDocumentWeeks:(c,d,weekNumbers)=>request(`/courses/${c}/documents/${d}/weeks`,'PUT',{weekNumbers}),
    syllabusPreview:d=>request(`/documents/${d}/syllabus-preview`),
    students:c=>request(`/courses/${c}/students`),saveStudent:(c,body,id)=>request(id?`/students/${id}`:`/courses/${c}/students`,id?'PUT':'POST',body),deleteStudent:id=>request(`/students/${id}`,'DELETE'),
    examReport:id=>request(`/runs/${id}/exam-review-report`),
    examKey:id=>request(`/runs/${id}/answer-key`),
    rubrics:c=>request(`/courses/${c}/rubrics`),readRubric:id=>request(`/rubrics/${id}`),saveRubric:(c,title,markdown,id)=>request(id?`/rubrics/${id}`:`/courses/${c}/rubrics`,id?'PUT':'POST',{title,markdown}),deleteRubric:id=>request(`/rubrics/${id}`,'DELETE'),
    runs:async c=>(await request<NormalRun[]>(`/courses/${c}/runs`)).map(run),
    subscribeRuns:(c,signal,onRuns)=>readRunEvents(base,token,c,signal,rows=>onRuns((rows as unknown as NormalRun[]).map(run))),
    createRun:async(c,input:RunInput,key)=>{
      const body={referenceSources:input.referenceSources||[],taskType:input.task_type,topic:input.topic,weekNumbers:input.weekNumbers||[input.week],documentIds:input.document_ids,guidelines:input.guidelines,parameters:input.parameters.map(p=>({questionType:p.question_type,count:p.count})),...(input.courseStudentId?{courseStudentId:input.courseStudentId}:{}),...(input.rubricVersionId?{rubricVersionId:input.rubricVersionId}:{})}
      const r=await fetch(base.replace(/\/$/,'')+`/v1/courses/${c}/runs`,{method:'POST',headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json','Idempotency-Key':key},body:JSON.stringify(body)})
      if(!r.ok){const e=await r.json();throw new Error(e.message||'생성 요청 실패')};return run(await r.json())
    },
    review:async(id,expectedRevision,decision,feedback)=>run(await request(`/runs/${id}/reviews`,'POST',{expectedRevision,decision,feedback})),
    editDraft:async(id,expectedRevision,draft)=>run(await request(`/runs/${id}/draft`,'PATCH',{expectedRevision,draft})),
    retry:async(id,expectedRevision)=>run(await request(`/runs/${id}/retries`,'POST',{expectedRevision})),
    cancel:async id=>run(await request(`/runs/${id}/cancellations`,'POST')),
    deleteRun:id=>request(`/runs/${id}`,'DELETE'),
    search:async(c,query)=>{const r=await request<{results:NormalRun['citations'];retrieval:string}>(`/courses/${c}/search`,'POST',{query});return {...r,results:r.results.map(x=>({...x,document_id:x.documentId}))}},
    dispatch:async id=>(await request<NormalRun[]>(`/runs/${id}/dispatches`,'POST')).map(run),
  }
}
