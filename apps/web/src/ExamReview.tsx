import {useState} from 'react'
import ReactMarkdown from 'react-markdown'
type Question={number:number;question_type:string;content:string;model_answer:string;learningObjective?:string;bloomLevel?:string;expectedDifficulty?:string;cognitiveRationale?:unknown;difficultyRationale?:unknown;evidence?:unknown;distractorRationale?:unknown}
type Review={decision?:string;reason?:string;checks?:Record<string,boolean>}
const levels=[['remember','기억'],['understand','이해'],['apply','적용'],['analyze','분석'],['evaluate','평가'],['create','창안']]
const checks=[['alignment','학습목표 연계'],['cognitiveLevel','인지 수준 적합성'],['answerClarity','정답 명확성'],['distractors','오답 매력도'],['rubricClarity','루브릭 명확성·일관성']]
// Model explanations may be prose, lists, or choice-keyed objects. Preserve
// their structure for display without rewriting the saved review payload.
function Explanation({value}:{value:unknown}){
 if(value==null||value==='')return null
 if(Array.isArray(value))return <ul>{value.map((item,i)=><li key={i}><Explanation value={item}/></li>)}</ul>
 if(typeof value==='object')return <dl>{Object.entries(value).map(([key,item])=><div key={key}><dt>{key}</dt><dd><Explanation value={item}/></dd></div>)}</dl>
 return <ReactMarkdown>{String(value)}</ReactMarkdown>
}
export default function ExamReview({draft,onSave,busy,onDirty}:{onDirty:()=>void;draft:Record<string,unknown>;onSave:(draft:Record<string,unknown>)=>Promise<void>;busy:boolean}){
 const [value,setValue]=useState(()=>structuredClone(draft)),[error,setError]=useState('')
 const questions=value.questions as Question[],reviews=(value.itemReviews||{}) as Record<string,Review>
 const summary=value.reviewSummary as {editedCount:number;total:number;rejectedCount:number}|undefined
 function change(q:Question,patch:Partial<Question>){onDirty();setValue({...value,questions:questions.map(item=>item.number===q.number?{...item,...patch}:item),itemReviews:{...reviews,[q.number]:{...reviews[q.number],decision:'pending',checks:{}}}})}
 function review(q:Question,patch:Partial<Review>){onDirty();setValue({...value,itemReviews:{...reviews,[q.number]:{...reviews[q.number],...patch}}})}
 return <section><h3>문항별 교수자 검토</h3><p>인지 수준과 예상 난이도는 별개입니다. 학생 응답 전에는 실제 난이도가 아닙니다.</p>
 {summary&&<p>직접 수정 {summary.editedCount}/{summary.total}문항 · 반려 {summary.rejectedCount}문항 (저장된 버전 기준)</p>}
 <p>{levels.map(([key,label])=>`${label} ${questions.filter(q=>q.bloomLevel===key).length}`).join(' · ')}</p>
 <p>{[['easy','쉬움'],['medium','보통'],['hard','어려움']].map(([key,label])=>`${label} ${questions.filter(q=>q.expectedDifficulty===key).length}`).join(' · ')}</p>
 {questions.map(q=>{const r=reviews[q.number]||{};return <fieldset key={q.number}><legend>문항 {q.number} · {q.question_type==='single_choice'?'객관식':'주관식'}</legend>
 <label>문항 내용<textarea rows={5} value={q.content} onChange={e=>change(q,{content:e.target.value})}/></label>
 <label>모범 답안<textarea value={q.model_answer} onChange={e=>change(q,{model_answer:e.target.value})}/></label>
 <label>학습목표 연결<input value={q.learningObjective||''} onChange={e=>change(q,{learningObjective:e.target.value})}/></label>
 <label>인지 수준<select value={q.bloomLevel||''} onChange={e=>change(q,{bloomLevel:e.target.value})}><option value="">확인 필요</option>{levels.map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
 <label>예상 난이도<select value={q.expectedDifficulty||''} onChange={e=>change(q,{expectedDifficulty:e.target.value})}><option value="">확인 필요</option><option value="easy">쉬움</option><option value="medium">보통</option><option value="hard">어려움</option></select></label>
 <details><summary>생성 근거·루브릭 확인</summary><Explanation value={q.cognitiveRationale}/><Explanation value={q.difficultyRationale}/><Explanation value={q.evidence||'근거 연결 확인 필요'}/><Explanation value={q.distractorRationale}/>{(value.rubrics as {question_number:number;criteria:{points:number;description:string}[];scoringGuidance?:string}[]).filter(x=>x.question_number===q.number).map(x=><div key={x.question_number}><ul>{x.criteria.map((c,i)=><li key={i}>{c.points}점: {c.description}</li>)}</ul><p>{x.scoringGuidance}</p></div>)}</details>
 {checks.map(([key,label])=>key==='distractors'&&q.question_type!=='single_choice'?<p key={key}>오답 매력도: 주관식 해당 없음</p>:<label key={key}><input type="checkbox" checked={r.checks?.[key]===true} onChange={e=>review(q,{checks:{...r.checks,[key]:e.target.checked}})}/>{label}</label>)}
 <label>검토 결정<select value={r.decision||'pending'} onChange={e=>review(q,{decision:e.target.value})}><option value="pending">검토 중</option><option value="accept">채택</option><option value="revise">수정 필요</option><option value="reject">반려 · 문제지에서 제외</option></select></label>
 <label>수정·반려 사유<textarea value={r.reason||''} onChange={e=>review(q,{reason:e.target.value})}/></label>
 </fieldset>})}
 {error&&<p role="alert">{error}</p>}<button className="button primary" disabled={busy} onClick={async()=>{setError('');try{await onSave(value)}catch(e){setError(e instanceof Error?e.message:'저장 실패')}}}>문항 검토 저장</button><p>저장 후 전체 버전을 승인하세요. 내용 수정 시 체크리스트를 다시 확인합니다. 루브릭 수정은 ‘초안 직접 편집’에서 가능합니다.</p></section>
}
