export type EducationReport={status:string;rubricVersion?:string;message?:string;criteria?:{criterionId:string;title:string;score:number|null;evidenceQuotes:string[];rationale:string;nextAction:string}[];criticalIssues?:string[]}
const labels:Record<string,string>={needsRevision:'보완 필요',inconclusive:'판단 유보',readyForInstructorReview:'자동 기준 충족 · 교수자 확인 필요',reviewFailed:'자동 검토 실패',notEvaluated:'검토 미실행'}
export default function EducationReview({report}:{report?:EducationReport|null}){
 if(!report)return <p>이 결과물에는 교육적 적합성 검토 기록이 없습니다.</p>
 return <section aria-label="교육적 적합성 검토"><h3>교육적 적합성 검토</h3><p>{labels[report.status]||report.status}</p><small>{report.rubricVersion} · AI 보조 검토이며 학습효과 검증이나 교수자 최종 판단을 대체하지 않습니다.</small>{report.message&&<p>{report.message}</p>}
 {report.criticalIssues?.map((x,i)=><p className="notice" key={i}>{x}</p>)}
 {report.criteria?.map(c=><details key={c.criterionId}><summary>{c.title} · {c.score===null?'판단 유보':`${c.score}/3`}</summary><p>{c.rationale}</p>{c.evidenceQuotes.map((q,i)=><blockquote key={i}>{q}</blockquote>)}<p>보완 행동: {c.nextAction}</p></details>)}
 </section>
}
