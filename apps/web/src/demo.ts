import type {Client,Course,Document,Run,RunInput} from './api'

export function createDemoClient():Client {
  const course:Course={id:'sample-course',title:'머신러닝 입문',syllabus:'1주차: 머신러닝의 기초\n2주차: 지도학습과 비지도학습\n3주차: 모델 평가와 일반화',created_at:new Date().toISOString()}
  const courses=[course]
  const documents:Document[]=[{id:'sample-material',course_id:course.id,filename:'01_머신러닝_기초.md',size:1240,pages:1,status:'ready'}]
  const runs:Run[]=[]
  const requests=new Map<string,string>()
  const inputs=new Map<string,RunInput>()
  const copy=<T,>(value:T):T=>structuredClone(value)
  const get=(id:string)=>{const run=runs.find(r=>r.id===id);if(!run)throw new Error('작업을 찾을 수 없습니다.');return run}
  function draft(input:RunInput):Record<string,unknown>{
    if(input.task_type==='lecture')return {intro_slide:'## 시작하기\n- 오늘의 학습 목표를 함께 확인합니다.\n- 시연에서는 최신 트렌드를 조회하지 않습니다.',main_slides:[`## ${input.topic}\n- 데이터로부터 패턴을 학습하는 방법을 이해합니다.\n- 실제 수업 사례에 개념을 적용해 봅니다.`,'## 함께 생각해 보기\n- 지도학습과 비지도학습은 어떤 점이 다를까요?\n- 학습한 모델은 어떻게 평가할 수 있을까요?'],notice:'합성 시연 초안 · 실제 모델 생성 결과가 아닙니다.'}
    if(input.task_type==='manager')return {tasks:[{task_type:'lecture',week:input.week,subject:input.topic,context:input.topic}],notice:'합성 시연 학기 계획'}
    if(input.task_type==='exam')return {questions:[{number:1,question_type:'short_answer',content:`${input.topic}의 핵심 개념을 설명하시오.`,model_answer:'학습 자료를 바탕으로 핵심 개념을 설명합니다. (시연)'}],rubrics:[{question_number:1,criteria:'핵심 개념의 정확성 / 설명의 구체성 (시연)'}]}
    if(input.task_type==='project')return {evaluations:input.roster.map(r=>({name:r.name,student_id:r.student_id,summary:'GitHub를 조회하지 않은 시연 예시',feedback_items:{기여도:'자료를 확인하고 교수자가 최종 판단합니다.'},overall_feedback:'시연 평가 초안'}))}
    return {notebook:{nbformat:4,nbformat_minor:5,metadata:{},cells:[{id:'demo',cell_type:'markdown',metadata:{},source:['# 시연 노트북\n','실행하지 않은 합성 예시입니다.']}]},execution:'not_executed_demo'}
  }
  const api:Client={
    invitations:async()=>[],invite:async()=>{throw new Error('실제 관리자 계정으로 연결하세요.')},revoke:async()=>{},
    me:async()=>({mode:'demo'}),courses:async()=>copy(courses),
    deleteCourse:async id=>{for(const list of [courses,documents,runs]){for(let i=list.length-1;i>=0;i--){const item=list[i] as {id:string;course_id?:string};if(item.id===id||item.course_id===id)list.splice(i,1)}}},
    search:async(c,query)=>({results:documents.filter(d=>d.course_id===c).map(d=>({document_id:d.id,filename:d.filename,page:1,text:`합성 검색 예시: ${query}. 실제 파일 본문을 검색하지 않습니다.`})),retrieval:'demo'}),
    retry:async id=>{const r=get(id);r.status='waiting_review';r.error=null;return copy(r)},
    createCourse:async(title,syllabus)=>{const item={id:crypto.randomUUID(),title,syllabus,created_at:new Date().toISOString()};courses.unshift(item);return copy(item)},
    documents:async c=>copy(documents.filter(d=>d.course_id===c)),
    upload:async(c,file)=>{if(file.size>10_000_000)throw new Error('10MB 이하의 파일을 선택하세요.');if(!/\.(pdf|pptx|md|txt|ipynb)$/i.test(file.name))throw new Error('지원하는 파일 형식을 선택하세요.');const d={id:crypto.randomUUID(),course_id:c,filename:file.name,size:file.size,pages:1,status:'ready'};documents.push(d);return copy(d)},
    deleteDocument:async id=>{const i=documents.findIndex(d=>d.id===id);if(i>=0)documents.splice(i,1);for(const r of runs){if(inputs.get(r.id)?.document_ids.includes(id)){r.status='cancelled';r.draft=null;r.output=null;r.citations=[]}}},
    runs:async c=>copy(runs.filter(r=>r.course_id===c)),
    createRun:async(c,input,key)=>{
      if(requests.has(key))return copy(get(requests.get(key)!))
      if(['lecture','exam'].includes(input.task_type)&&!input.document_ids.length)throw new Error('강의 자료를 선택하세요.')
      if(input.task_type==='practice'&&!documents.some(d=>input.document_ids.includes(d.id)&&d.filename.endsWith('.ipynb')))throw new Error('IPYNB 자료를 선택하세요.')
      if(input.task_type==='project'&&!input.roster.length)throw new Error('평가할 학생 명단을 입력하세요.')
      const r:Run={id:crypto.randomUUID(),course_id:c,task_type:input.task_type,topic:input.topic,status:'waiting_review',revision:1,mode:'demo',draft:draft(input),citations:documents.filter(d=>input.document_ids.includes(d.id)).map(d=>({document_id:d.id,filename:d.filename,page:1,text:'합성 예시: 머신러닝은 데이터로부터 패턴을 학습합니다. 시연에서 업로드한 파일 본문은 분석하지 않습니다.'})),output:null,output_format:input.task_type==='practice'?'ipynb':'md',error:null,created_at:new Date().toISOString(),child_ids:[]}
      inputs.set(r.id,copy(input));runs.unshift(r);requests.set(key,r.id);return copy(r)
    },
    review:async(id,revision,decision,feedback)=>{const r=get(id);if(r.status!=='waiting_review'||r.revision!==revision)throw new Error('초안이 변경됐거나 이미 처리됐습니다. 최신 상태를 확인하세요.');if(decision==='revise'){if(!feedback.trim())throw new Error('수정 요청 내용을 입력하세요.');r.revision++;r.draft={...r.draft,revision_note:feedback}}else{r.status='succeeded';r.output=r.output_format==='ipynb'?JSON.stringify(r.draft?.notebook,null,2):'# 합성 시연 결과\n\n'+Object.values(r.draft||{}).map(v=>typeof v==='string'?v:JSON.stringify(v,null,2)).join('\n\n')}return copy(r)},
    cancel:async id=>{const r=get(id);r.status='cancelled';return copy(r)},
    editDraft:async(id,revision,draft)=>{const r=get(id);if(r.status!=='waiting_review'||r.revision!==revision)throw new Error('초안이 변경됐습니다.');r.draft=copy(draft);r.revision++;return copy(r)},
    dispatch:async id=>{const parent=get(id);if(parent.task_type!=='manager'||parent.status!=='succeeded')throw new Error('계획 승인 후 실행하세요.');if(parent.child_ids.length)return parent.child_ids.map(id=>copy(get(id)));const input=inputs.get(id)!;const child=await api.createRun(parent.course_id,{...input,task_type:'lecture'},id+':dispatch');parent.child_ids=[child.id];return [child]},
    feedback:async()=>{},
    download:async run=>{const r=get(run.id);if(r.status!=='succeeded')throw new Error('승인이 필요합니다.');return new Blob([r.output||''],{type:r.output_format==='ipynb'?'application/x-ipynb+json':'text/markdown'})},
  }
  return api
}
