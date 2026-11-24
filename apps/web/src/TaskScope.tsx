import {useEffect,useState} from 'react'
import type {NormalClient,Plan,LibraryDocument} from './normalizedApi'

export default function TaskScope({api,courseId,kind,revision,weekNumbers,topic,selected,onChange,onSetup}:{api:NormalClient;courseId:string;kind:'lecture'|'exam';revision:number;weekNumbers:number[];topic:string;selected:string[];onChange:(weeks:number[],topic:string,ids:string[])=>void;onSetup:()=>void}){
  const [plan,setPlan]=useState<Plan>({syllabusVersionId:null,weeks:[]}),[docs,setDocs]=useState<LibraryDocument[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true)
  useEffect(()=>{let alive=true;setLoading(true);setError('');Promise.all([api.plan(courseId),api.courseDocuments(courseId)]).then(([p,d])=>{if(alive){setPlan(p);setDocs(d);setLoading(false)}}).catch(e=>{if(alive){setError(e.message);setLoading(false)}});return()=>{alive=false}},[api,courseId,revision])
  function choose(weeks:number[]){const ids=docs.filter(d=>d.weekNumbers.some(w=>weeks.includes(w))).map(d=>d.id);onChange(weeks,plan.weeks.filter(w=>weeks.includes(w.weekNumber)).map(w=>w.topic).join(' · ').slice(0,200),ids)}
  const eligible=docs.filter(d=>d.weekNumbers.some(w=>weekNumbers.includes(w)))
  return <section className="task-scope">
    {loading&&<p role="status">등록된 주차와 자료를 불러오고 있습니다.</p>}{error&&<p role="alert">{error}</p>}
    {kind==='lecture'&&<div className="notice"><strong>강의계획서</strong><p>{plan.syllabusVersionId?docs.find(d=>d.currentVersionId===plan.syllabusVersionId)?.originalFileName||'등록된 강의계획서':plan.saved?'저장된 강의계획서':'아직 강의계획서가 없습니다.'}</p><button type="button" className="text-button" onClick={onSetup}>강의계획서 보기·수정</button></div>}
    {!plan.weeks.length&&<p>등록된 주차가 없습니다. <button type="button" className="text-button" onClick={onSetup}>주차와 주제 등록하기</button></p>}
    {kind==='lecture'?<label>강의 주차와 주제<select required value={weekNumbers.length===1?weekNumbers[0]:''} onChange={e=>choose(e.target.value?[Number(e.target.value)]:[])}><option value="">주차를 선택하세요</option>{plan.weeks.map(w=><option key={w.weekNumber} value={w.weekNumber}>{w.weekNumber}주차 · {w.topic}</option>)}</select></label>:
    <fieldset><legend>출제 범위 · 여러 주차 선택</legend><div className="week-checks">{plan.weeks.map(w=><label key={w.weekNumber}><input type="checkbox" checked={weekNumbers.includes(w.weekNumber)} onChange={e=>choose(e.target.checked?[...weekNumbers,w.weekNumber].sort((a,b)=>a-b):weekNumbers.filter(n=>n!==w.weekNumber))}/>{w.weekNumber}주차 · {w.topic}</label>)}</div></fieldset>}
    <label>{kind==='lecture'?'이번 주 주제':'퀴즈 주제'}<input required maxLength={200} value={topic} onChange={e=>onChange(weekNumbers,e.target.value,selected)}/></label>
    {plan.weeks.filter(w=>weekNumbers.includes(w.weekNumber)&&w.objectives).map(w=><p className="notice" key={w.weekNumber}>{w.weekNumber}주차 학습 목표: {w.objectives}</p>)}
    <fieldset><legend>{kind==='exam'?'선택 주차에서 출제에 사용할 RAG 자료':'선택 주차의 강의 자료'}</legend>
      {!eligible.length&&<p>이 범위에 등록된 자료가 없습니다. 자료실에서 자료에 주차를 지정해 주세요.</p>}
      {eligible.map(d=><label className="document-check" key={d.id}><input type="checkbox" checked={selected.includes(d.id)} onChange={e=>onChange(weekNumbers,topic,e.target.checked?[...selected,d.id]:selected.filter(id=>id!==d.id))}/>{d.originalFileName}<small>{d.weekNumbers.join(', ')}주차</small></label>)}
      {weekNumbers.some(w=>!eligible.some(d=>d.weekNumbers.includes(w)&&selected.includes(d.id)))&&<p role="status">선택한 각 주차에서 자료를 하나 이상 선택하세요.</p>}
    </fieldset>
  </section>
}
