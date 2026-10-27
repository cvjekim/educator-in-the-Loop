import {useEffect,useRef,useState} from 'react'
import type {Citation,Client} from './api'

export default function SourceSearch({api,courseId}:{api:Client;courseId:string}){
  const [query,setQuery]=useState(''),[results,setResults]=useState<Citation[]|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const generation=useRef(0)
  useEffect(()=>{generation.current++;setQuery('');setResults(null);setError('');setBusy(false)},[courseId,api])
  return <section className="panel" aria-label="강의 자료 검색"><h2>자료에서 근거 찾기</h2><form onSubmit={async e=>{e.preventDefault();setBusy(true);setError('');const current=generation.current;try{const response=await api.search(courseId,query);if(current===generation.current)setResults(response.results)}catch(e){if(current===generation.current)setError(e instanceof Error?e.message:'검색하지 못했습니다.')}finally{if(current===generation.current)setBusy(false)}}}><label>찾을 개념이나 질문<input required maxLength={500} value={query} onChange={e=>setQuery(e.target.value)} placeholder="예: 지도학습은 어떤 데이터가 필요한가요?"/></label><button className="button secondary" disabled={busy||!query.trim()}>{busy?'검색 중…':'자료 검색'}</button></form>{error&&<p role="alert">{error}</p>}{results&&<div aria-live="polite">{results.length===0?<p>관련 근거를 찾지 못했습니다. 검색어를 바꾸거나 자료를 추가해 주세요.</p>:results.map((c,i)=><article key={c.document_id+':'+i}><h3>{c.filename} · {c.page}쪽</h3><p style={{whiteSpace:'pre-wrap'}}>{c.text}</p></article>)}</div>}</section>
}
