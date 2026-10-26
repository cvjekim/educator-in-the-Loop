import type {Run} from './api'

const names:Record<string,string>={intro_slide:'도입 슬라이드',main_slides:'본론 슬라이드',content:'문항',model_answer:'모범 답안',description:'평가 기준',overall_feedback:'종합 의견',summary:'요약',source:'셀 내용',context:'작업 내용',subject:'과목',feedback_items:'항목별 피드백',criteria:'채점 기준',questions:'문항',rubrics:'루브릭',evaluations:'학생별 평가',notebook:'노트북',cells:'셀',tasks:'계획',keywords:'핵심어'}
const protectedFields=new Set(['student_id','name','number','question_number','task_type','question_type','cell_type','id','notice','execution','iterations','guidelines','revision_note'])

export default function DraftEditor({value,onChange}:{value:NonNullable<Run['draft']>;onChange:(value:NonNullable<Run['draft']>)=>void}){
  function change(path:(string|number)[],text:string){const next=structuredClone(value);let node:unknown=next;for(const key of path.slice(0,-1))node=(node as Record<string|number,unknown>)[key];(node as Record<string|number,unknown>)[path[path.length-1]]=text;onChange(next)}
  function fields(node:unknown,path:(string|number)[]=[]):React.ReactNode{
    if(typeof node==='string')return <label key={path.join('.')}>{names[String(path.at(-1))]|| (typeof path.at(-1)==='number'?`항목 ${Number(path.at(-1))+1}`:String(path.at(-1)))}<textarea rows={Math.min(12,Math.max(3,node.split('\n').length+1))} value={node} onChange={e=>change(path,e.target.value)}/></label>
    if(Array.isArray(node))return node.map((item,i)=><section className="edit-section" key={i}>{fields(item,[...path,i])}</section>)
    if(node&&typeof node==='object')return Object.entries(node).filter(([key])=>!protectedFields.has(key)).map(([key,v])=><section key={key}>{typeof v!=='string'&&names[key]&&<h3>{names[key]}</h3>}{fields(v,[...path,key])}</section>)
    return null
  }
  return <div className="draft-editor"><p className="notice">내용을 직접 다듬어 저장하면 새 버전이 됩니다. 변경한 버전을 확인하고 승인해 주세요.</p>{fields(value)}</div>
}
