const providers:Record<string,string>={duckduckgo:'DuckDuckGo',arxiv:'arXiv',youtube:'YouTube',academic:'학술 검색 (Crossref)',wikipedia:'위키피디아',news:'뉴스 검색'}
const status:Record<string,string>={success:'검색 완료',empty:'결과 없음',error:'검색 실패',notConfigured:'연결 설정 필요'}
type Reference={id:string;title:string;url:string;provider:string;publishedAt?:string;observedAt?:string;retrievedAt:string;evidenceType:string}
export default function TrendReferences({draft}:{draft:Record<string,unknown>|null}){
 const search=draft?.trend_search as {query:string;searchedAt:string;providers:{provider:string;status:string;count:number;via?:string}[]}|undefined
 const refs=draft?.trend_references as Reference[]|undefined
 if(!search)return null
 return <section><h3>도입부 외부 참고자료</h3><p>검색어: {search.query}</p><small>검색일 {search.searchedAt.slice(0,10)}</small>
 {search.providers.map(p=><p key={p.provider}>{providers[p.provider]||p.provider}: {status[p.status]||p.status} · {p.count}건{p.via==='webSearch'?' (웹 검색)':''}</p>)}
 {refs?.map(r=><article key={r.id}><a href={/^https?:\/\//.test(r.url)?r.url:undefined} target="_blank" rel="noopener noreferrer">[{r.id}] {r.title}</a><p><small>{providers[r.provider]} · {r.publishedAt||'발행일 미확인'}{r.observedAt?` · 뉴스 수집일 ${r.observedAt.slice(0,8)}`:''}</small></p><small>{r.evidenceType==='background'?'배경 설명':r.evidenceType==='abstract'?'초록 확인':r.evidenceType==='videoMetadata'?'영상 제목·설명 확인 (영상·자막 미확인)':r.evidenceType==='searchSnippet'?'검색 요약 확인 (원문 확인 필요)':r.evidenceType==='searchSummary'?'웹 검색 기반 요약 (원문 확인 필요)':'제목·서지정보 확인 (본문 미확인)'}</small></article>)}
 <p>외부 검색 근거는 도입부에 사용합니다. 본론은 선택한 강의 자료를 바탕으로 작성합니다.</p></section>
}
