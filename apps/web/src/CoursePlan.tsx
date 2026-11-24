import {useEffect,useState} from 'react'
import type {NormalClient,Plan,LibraryDocument,Week} from './normalizedApi'

const emptyPlan:Plan={syllabusVersionId:null,weeks:[],goals:'',mainTextbooks:'',supplementaryTextbooks:''}
export default function CoursePlan({api,courseId,onChange,compact=false}:{api:NormalClient;courseId:string;onChange:()=>void;compact?:boolean}){
  const [plan,setPlan]=useState<Plan>(emptyPlan),[saved,setSaved]=useState<Plan|null>(null),[library,setLibrary]=useState<LibraryDocument[]>([])
  const [loading,setLoading]=useState(true),[editing,setEditing]=useState(false),[replaceSource,setReplaceSource]=useState(false)
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState(''),[preview,setPreview]=useState('')
  useEffect(()=>{let active=true;setLoading(true);Promise.all([api.plan(courseId),api.library()]).then(([p,l])=>{if(active){setPlan(p);setSaved(p.saved||p.syllabusVersionId||p.weeks.length?p:null);setEditing(!(p.saved||p.syllabusVersionId||p.weeks.length));setLibrary(l);setLoading(false)}}).catch(e=>{if(active){setError(e.message);setLoading(false)}});return()=>{active=false}},[api,courseId])
  async function act(fn:()=>Promise<void>){setBusy(true);setError('');setMessage('');try{await fn()}catch(e){setError(e instanceof Error?e.message:'저장 실패')}finally{setBusy(false)}}
  async function readSource(id:string){
    await api.attach(courseId,id)
    const result=await api.syllabusPreview(id)
    setPlan(p=>({...p,...result.suggestedPlan,syllabusVersionId:result.documentVersionId}))
    setPreview(result.text);setLibrary(await api.library());setMessage('원문에서 읽은 내용을 확인하고 저장하세요. 인식되지 않은 항목은 직접 보완할 수 있습니다.')
  }
  function change(index:number,field:keyof Week,value:string|number){setPlan(p=>({...p,weeks:p.weeks.map((w,i)=>i===index?{...w,[field]:value}:w)}))}
  const source=library.find(d=>d.currentVersionId===plan.syllabusVersionId)?.originalFileName
  return <section className="panel course-plan"><h2>강의계획서와 주차</h2>
    {error&&<p role="alert" className="dialog-error">{error}</p>}{message&&<p role="status" className="notice">{message}</p>}
    {loading?<p role="status">저장된 강의계획서를 불러오고 있습니다.</p>:!editing?<>
      <p>저장된 강의계획서를 사용합니다. 변경할 내용이 있으면 계획서를 수정하세요.</p>
      <p><strong>원본 자료: </strong>{source||'직접 작성한 계획서'}</p>
      <h3>강의 목표</h3><p className="plan-text">{plan.goals||'등록된 목표가 없습니다.'}</p>
      <h3>주교재</h3><p className="plan-text">{plan.mainTextbooks||'등록된 주교재가 없습니다.'}</p>
      <h3>부교재</h3><p className="plan-text">{plan.supplementaryTextbooks||'등록된 부교재가 없습니다.'}</p>
      <details open={compact?undefined:true}><summary>주차별 주제와 내용 ({plan.weeks.length}개)</summary>{plan.weeks.map(w=><article key={w.weekNumber}><h4>{w.weekNumber}주차 · {w.topic}</h4><p className="plan-text">{w.objectives}</p><p className="plan-text">{w.content}</p></article>)}</details>
      <button type="button" className="button secondary" onClick={()=>{setEditing(true);setReplaceSource(false);setMessage('')}}>계획서 수정</button>
    </>:<>
      <p>{saved?'저장된 목표·교재·주차 내용을 수정합니다. 원본 파일을 다시 업로드할 필요가 없습니다.':'계획서를 업로드하거나 내 자료실에서 불러오세요. 직접 입력할 수도 있습니다.'}</p>
      {saved&&!replaceSource&&<button type="button" className="text-button" onClick={()=>setReplaceSource(true)}>다른 원본에서 다시 불러오기</button>}
      {(!saved||replaceSource)&&<fieldset disabled={busy}><legend>강의계획서 불러오기</legend>
        {saved&&<p>원본을 선택하면 편집 중인 목표·교재·주차가 새로 읽은 내용으로 바뀝니다. 저장 전에는 기존 계획이 유지됩니다.</p>}
        <label>강의계획서 업로드 (PDF · MD · TXT)<input type="file" accept=".pdf,.md,.txt" onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void act(async()=>{const doc=await api.upload(courseId,file);await readSource(doc.id)})}}/></label>
        <label>내 자료실에서 강의계획서 선택<select value="" onChange={e=>{if(e.target.value)void act(()=>readSource(e.target.value))}}><option value="">자료를 선택하세요</option>{library.filter(d=>/\.(pdf|md|txt)$/i.test(d.originalFileName)).map(d=><option key={d.id} value={d.id}>{d.originalFileName}</option>)}</select></label>
      </fieldset>}
      {preview&&<details><summary>강의계획서 원문 확인</summary><pre className="syllabus-preview">{preview}</pre></details>}
      <form onSubmit={e=>{e.preventDefault();void act(async()=>{const p=await api.savePlan(courseId,plan);setPlan(p);setSaved(p);setEditing(false);setReplaceSource(false);setPreview('');onChange();setMessage('강의계획서와 주차 계획을 저장했습니다.')})}}>
        <fieldset disabled={busy}><legend>강의계획서 기본 정보</legend>
          <label>강의 목표<textarea aria-label="강의 목표" rows={4} maxLength={10000} value={plan.goals||''} onChange={e=>setPlan(p=>({...p,goals:e.target.value}))}/></label>
          <label>주교재<textarea aria-label="주교재" rows={2} maxLength={10000} value={plan.mainTextbooks||''} onChange={e=>setPlan(p=>({...p,mainTextbooks:e.target.value}))}/></label>
          <label>부교재<textarea aria-label="부교재" rows={2} maxLength={10000} value={plan.supplementaryTextbooks||''} onChange={e=>setPlan(p=>({...p,supplementaryTextbooks:e.target.value}))}/></label>
          <h3>등록할 주차와 주제</h3>
          {plan.weeks.map((w,i)=><fieldset className="week-editor" key={i}><legend>주차 계획 {i+1}</legend>
            <label>주차 번호<input type="number" required min={1} max={52} value={w.weekNumber} onChange={e=>change(i,'weekNumber',Number(e.target.value))}/></label>
            <label>주제<input required maxLength={200} value={w.topic} onChange={e=>change(i,'topic',e.target.value)}/></label>
            <label>학습 목표<textarea aria-label="학습 목표" maxLength={3000} value={w.objectives} onChange={e=>change(i,'objectives',e.target.value)}/></label>
            <label>주차별 내용<textarea aria-label="주차별 내용" rows={3} maxLength={10000} value={w.content||''} onChange={e=>change(i,'content',e.target.value)}/></label>
            <button type="button" className="text-button danger" onClick={()=>setPlan(p=>({...p,weeks:p.weeks.filter((_,j)=>i!==j)}))}>{w.weekNumber}주차 제거</button>
          </fieldset>)}
          <button type="button" className="button" disabled={plan.weeks.length>=52} onClick={()=>setPlan(p=>({...p,weeks:[...p.weeks,{weekNumber:Array.from({length:52},(_,i)=>i+1).find(n=>!p.weeks.some(w=>w.weekNumber===n))!,topic:'',objectives:'',content:''}]}))}>주차 추가</button>
        </fieldset>
        <div className="account-actions"><button className="button primary" disabled={busy}>{busy?'저장 중…':'강의 계획 저장'}</button>{saved&&<button type="button" className="button" disabled={busy} onClick={()=>{setPlan(saved);setEditing(false);setPreview('');setError('');setMessage('')}}>수정 취소</button>}</div>
        <small>주차를 제거하면 해당 주차의 자료 연결도 해제됩니다. 기존에 생성한 작업의 계획은 보존됩니다.</small>
      </form>
    </>}
  </section>
}

export function MaterialWeeks({api,courseId,refresh,onChange}:{api:NormalClient;courseId:string;refresh:number;onChange:()=>void}){
  const [docs,setDocs]=useState<LibraryDocument[]>([]),[library,setLibrary]=useState<LibraryDocument[]>([]),[plan,setPlan]=useState<Plan>({syllabusVersionId:null,weeks:[]})
  const [error,setError]=useState(''),[busy,setBusy]=useState(false)
  async function reload(){setDocs(await api.courseDocuments(courseId));setLibrary(await api.library());setPlan(await api.plan(courseId))}
  useEffect(()=>{let alive=true;Promise.all([api.courseDocuments(courseId),api.library(),api.plan(courseId)]).then(([d,l,p])=>{if(alive){setDocs(d);setLibrary(l);setPlan(p)}}).catch(e=>{if(alive)setError(e.message)});return()=>{alive=false}},[api,courseId,refresh])
  async function act(fn:()=>Promise<unknown>){setBusy(true);setError('');try{await fn();await reload();onChange()}catch(e){setError(e instanceof Error?e.message:'저장 실패')}finally{setBusy(false)}}
  return <section className="panel"><h2>자료 재사용과 주차 지정</h2>{error&&<p role="alert">{error}</p>}
    <label>내 자료실의 기존 자료 연결<select value="" disabled={busy} onChange={e=>{if(e.target.value)void act(()=>api.attach(courseId,e.target.value))}}><option value="">자료를 선택하세요</option>{library.filter(d=>!docs.some(x=>x.id===d.id)).map(d=><option key={d.id} value={d.id}>{d.originalFileName}</option>)}</select></label>
    {!plan.weeks.length&&<p>먼저 강의계획서와 주차를 등록하세요.</p>}
    {docs.map(d=><fieldset key={d.id}><legend>{d.originalFileName}</legend><div className="week-checks">{plan.weeks.map(w=><label key={w.weekNumber}><input type="checkbox" disabled={busy} checked={d.weekNumbers.includes(w.weekNumber)} onChange={e=>{const next=e.target.checked?[...d.weekNumbers,w.weekNumber]:d.weekNumbers.filter(n=>n!==w.weekNumber);setDocs(values=>values.map(value=>value.id===d.id?{...value,weekNumbers:next}:value));void act(async()=>{try{return await api.setDocumentWeeks(courseId,d.id,next)}catch(e){setDocs(values=>values.map(value=>value.id===d.id?d:value));throw e}})}}/>{w.weekNumber}주차 · {w.topic}</label>)}</div><button type="button" className="text-button" disabled={busy} onClick={()=>void act(()=>api.unlink(courseId,d.id))}>이 강의에서 연결 해제</button></fieldset>)}
    <p className="notice">연결 해제는 개인 원본과 기존 결과를 보존합니다. 원본 삭제는 연결된 모든 강의의 관련 결과도 삭제합니다.</p>
  </section>
}
