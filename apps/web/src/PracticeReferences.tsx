import {useEffect,useState} from 'react'
import type {NormalClient,PracticeReference,ReferenceSelection} from './normalizedApi'
export default function PracticeReferences({api,courseId,revision,selected,onChange}:{api:NormalClient;courseId:string;revision:number;selected:ReferenceSelection[];onChange:(v:ReferenceSelection[])=>void}){
 const [items,setItems]=useState<PracticeReference[]>([]),[error,setError]=useState(''),[loading,setLoading]=useState(true)
 useEffect(()=>{let cancelled=false;setLoading(true);setError('');api.practiceReferences(courseId).then(rows=>{if(!cancelled)setItems(rows)}).catch(e=>{if(!cancelled)setError(e.message)}).finally(()=>{if(!cancelled)setLoading(false)});return()=>{cancelled=true}},[api,courseId,revision])
 return <fieldset><legend>강의 초안·생성 자료 참고</legend><p>선택한 버전의 개념과 학습 목표를 실습 코드와 설명에 반영합니다. 기존 IPYNB 없이도 새 실습 노트북을 만들 수 있습니다.</p>
 {loading?<p role="status">참고자료를 불러오는 중입니다.</p>:error?<p role="alert">{error}</p>:!items.length?<p>저장된 강의 초안이나 생성 자료가 없습니다.</p>:items.map(item=>{
 const checked=selected.some(s=>s.id===item.id&&s.kind===item.kind)
 return <label className="document-check" key={item.kind+item.id}><input type="checkbox" checked={checked} onChange={e=>onChange(e.target.checked?[...selected,{kind:item.kind,id:item.id}]:selected.filter(s=>!(s.id===item.id&&s.kind===item.kind)))}/><span>{item.weekNumber?`${item.weekNumber}주차 · `:''}{item.title}<small>{item.label} · v{item.version}</small></span></label>
 })}</fieldset>
}
