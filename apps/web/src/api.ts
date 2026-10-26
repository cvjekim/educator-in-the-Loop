export type TaskType = 'manager'|'lecture'|'practice'|'exam'|'project'
export type Course = {id:string;title:string;syllabus:string;created_at:string}
export type Document = {id:string;course_id:string;filename:string;size:number;pages:number;status:string}
export type Citation = {document_id:string;filename:string;page:number;text:string}
export type Run = {id:string;course_id:string;task_type:TaskType;topic:string;status:string;revision:number;mode:'demo'|'real';draft:Record<string,unknown>|null;citations:Citation[];output:string|null;output_format:string;error:string|null;created_at:string;child_ids:string[]}
export type RunInput = {task_type:TaskType;topic:string;week:number;guidelines:string;rubric_guidelines:string;document_ids:string[];parameters:{question_type:string;count:number}[];roster:{student_id:string;name:string;github_id:string;repo_name:string}[];execute_notebook:boolean;max_iterations:number}
export type Client = {
  me:()=>Promise<{mode:string}>
  courses:()=>Promise<Course[]>
  createCourse:(title:string,syllabus:string)=>Promise<Course>
  documents:(course:string)=>Promise<Document[]>
  upload:(course:string,file:File)=>Promise<Document>
  deleteDocument:(id:string)=>Promise<void>
  runs:(course:string)=>Promise<Run[]>
  createRun:(course:string,input:RunInput,key:string)=>Promise<Run>
  review:(id:string,revision:number,decision:'approve'|'revise',feedback:string)=>Promise<Run>
  editDraft:(id:string,revision:number,draft:Record<string,unknown>)=>Promise<Run>
  cancel:(id:string)=>Promise<Run>
  dispatch:(id:string)=>Promise<Run[]>
  feedback:(id:string,rating:number,comment:string)=>Promise<void>
  download:(run:Run)=>Promise<Blob>
}

export function createClient(base:string,token:string):Client {
  async function request<T>(path:string,init:RequestInit={}):Promise<T> {
    const response=await fetch(base.replace(/\/$/,'')+path,{...init,headers:{Authorization:`Bearer ${token}`,...(!(init.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...init.headers}})
    if(!response.ok){const error=await response.json().catch(()=>({message:'서버에 연결할 수 없습니다.'}));throw new Error(error.message||`요청 실패 (${response.status})`)}
    if(response.status===204)return undefined as T
    return response.json()
  }
  const post=<T,>(path:string,body:unknown,headers?:Record<string,string>)=>request<T>(path,{method:'POST',body:JSON.stringify(body),headers})
  return {
    me:()=>request('/v1/me'),courses:()=>request('/v1/courses'),
    createCourse:(title,syllabus)=>post('/v1/courses',{title,syllabus}),
    documents:c=>request(`/v1/courses/${c}/documents`),
    upload:(c,file)=>{const body=new FormData();body.append('file',file);return request(`/v1/courses/${c}/documents`,{method:'POST',body})},
    deleteDocument:id=>request(`/v1/documents/${id}`,{method:'DELETE'}),
    runs:c=>request(`/v1/courses/${c}/runs`),
    createRun:(c,input,key)=>post(`/v1/courses/${c}/runs`,input,{'Idempotency-Key':key}),
    review:(id,revision,decision,feedback)=>post(`/v1/runs/${id}/reviews`,{decision,expected_revision:revision,feedback}),
    editDraft:(id,revision,draft)=>request(`/v1/runs/${id}/draft`,{method:'PATCH',body:JSON.stringify({expected_revision:revision,draft})}),
    cancel:id=>post(`/v1/runs/${id}/cancellations`,{}),
    dispatch:id=>post(`/v1/runs/${id}/dispatches`,{}),
    feedback:async(id,rating,comment)=>{await post(`/v1/runs/${id}/feedback`,{rating,comment})},
    download:async(run)=>{const response=await fetch(`${base}/v1/runs/${run.id}/artifact`,{headers:{Authorization:`Bearer ${token}`}});if(!response.ok)throw new Error('승인된 결과만 다운로드할 수 있습니다.');return response.blob()},
  }
}
