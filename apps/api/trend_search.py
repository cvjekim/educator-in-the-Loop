"""LangChain tools for bounded external reference searches, separate from course RAG."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
import asyncio
import html
import os
import re
from urllib.parse import quote,urlparse
import httpx
import certifi
# Use a verified CA bundle on local Python installations without system CA paths.
os.environ.setdefault("SSL_CERT_FILE",certifi.where())
from langchain_core.tools import StructuredTool

NEWS_DOMAINS=('yna.co.kr','en.yna.co.kr','news.hada.io')
class MissingSearchKey(Exception):pass

def clean(value,limit=1200):return html.unescape(re.sub(r'<[^>]+>','',str(value or '')))[:limit]
def safe_url(value):
    try:
        u=urlparse(value)
        return value if u.scheme in ('https','http') and u.hostname and not u.username and not u.password else ''
    except ValueError:return ''

def in_domains(url,domains):
    host=urlparse(url).hostname or ''
    return any(host==d or host.endswith('.'+d) for d in domains)

def get_json(url,params,headers=None):
    with httpx.Client(timeout=httpx.Timeout(12,connect=5),follow_redirects=False,headers=headers or {'User-Agent':'EducatorReferenceSearch/1.0'}) as client:
        with client.stream('GET',url,params=params) as response:
            response.raise_for_status();body=b''
            for part in response.iter_bytes():
                body+=part
                if len(body)>2_000_000:raise ValueError('Search response too large')
        import json
        return json.loads(body)

def duckduckgo(query:str):
    from ddgs import DDGS
    rows=DDGS(timeout=12).text(query,max_results=3,backend='duckduckgo',timelimit='y')
    return [{'title':r['title'],'url':r['href'],'summary':r.get('body',''),'publishedAt':None,'evidenceType':'searchSnippet'} for r in rows]

def wikipedia(query:str):
    rows=duckduckgo('site:wikipedia.org '+query)
    return [{**r,'evidenceType':'background'} for r in rows if in_domains(r['url'],('wikipedia.org',))]

def crossref(query:str):
    today=datetime.now(timezone.utc).date()
    data=get_json('https://api.crossref.org/works',{'query':query,'rows':3,'filter':f'from-pub-date:{today-timedelta(days=730)},until-pub-date:{today}','sort':'score','order':'desc'})
    rows=[]
    for item in data['message']['items']:
        parts=item.get('published',{}).get('date-parts',[[]])[0]
        rows.append({'title':(item.get('title') or [''])[0],'url':'https://doi.org/'+quote(item['DOI'],safe='/'),
            'publishedAt':'-'.join(str(v).zfill(2) for v in parts),'summary':item.get('abstract') or ' · '.join(item.get('container-title',[])),
            'evidenceType':'abstract' if item.get('abstract') else 'metadata'})
    return rows

def arxiv_search(query:str):
    import arxiv
    import requests
    class BoundedSession(requests.Session):
        def request(self,*args,**kwargs):
            kwargs.setdefault('timeout',(5,12));return super().request(*args,**kwargs)
    client=arxiv.Client(page_size=3,num_retries=0)
    client._session.close();client._session=BoundedSession()
    since=(datetime.now(timezone.utc)-timedelta(days=730)).strftime('%Y%m%d')
    until=datetime.now(timezone.utc).strftime('%Y%m%d%H%M')
    terms=' AND '.join('all:'+word for word in query.split())
    search=arxiv.Search(query=f'({terms}) AND submittedDate:[{since}0000 TO {until}]',max_results=3,sort_by=arxiv.SortCriterion.Relevance)
    try:return [{'title':r.title,'url':r.entry_id,'summary':r.summary,'publishedAt':r.published.date().isoformat(),'evidenceType':'abstract'} for r in client.results(search)]
    finally:client._session.close()

def youtube(query:str):
    from youtube_search import YoutubeSearch
    rows=YoutubeSearch(query,max_results=3,retries=0,timeout=12).to_dict()
    return [{'title':r['title'],'url':'https://www.youtube.com/watch?v='+quote(r['id'],safe=''),
        'summary':' · '.join(str(v) for v in (r.get('channel'),r.get('long_desc'),r.get('publish_time')) if v),
        'publishedAt':None,'evidenceType':'videoMetadata'} for r in rows if r.get('id')]

def tavily_news(query:str):
    if not os.getenv('TAVILY_API_KEY'):raise MissingSearchKey('TAVILY_API_KEY')
    from langchain_tavily import TavilySearch
    tool=TavilySearch(max_results=4,include_domains=list(NEWS_DOMAINS),topic='general',time_range='month',search_depth='basic',include_answer=False,include_raw_content=False)
    async def run():return await asyncio.wait_for(tool.ainvoke({'query':query}),timeout=15)
    data=asyncio.run(run())
    if not isinstance(data,dict) or 'results' not in data:raise ValueError('Invalid Tavily response')
    return [{'title':r['title'],'url':r['url'],'summary':r.get('content',''),'publishedAt':r.get('published_date'),'evidenceType':'searchSnippet'} for r in data['results'] if in_domains(r['url'],NEWS_DOMAINS)]

def build_tools():
    functions={'duckduckgo':duckduckgo,'wikipedia':wikipedia,'academic':crossref,'arxiv':arxiv_search,'youtube':youtube,'news':tavily_news}
    return {name:StructuredTool.from_function(fn,name=name+'_reference_search',description=f'Search {name} for public lecture-topic references. Input must contain only topic keywords, never private course documents.') for name,fn in functions.items()}

def search_references(query,tools=None,now=None):
    now=now or datetime.now(timezone.utc);stamp=now.isoformat()
    query=re.sub(r'[^\w\s-]',' ',query)[:100].strip()
    tools=tools if tools is not None else build_tools()
    def search(pair):
        provider,tool=pair
        try:
            if not query:raise ValueError('Empty query')
            rows=tool.invoke({'query':query})
            rows=[{**r,'title':clean(r['title'],300),'summary':clean(r.get('summary')),'url':safe_url(r['url']),'provider':provider,'retrievedAt':stamp} for r in rows[:4] if r.get('title') and safe_url(r.get('url',''))]
            return rows,{'provider':provider,'status':'success' if rows else 'empty','count':len(rows),'tool':tool.name}
        except MissingSearchKey as e:return [],{'provider':provider,'status':'notConfigured','count':0,'requiredKey':str(e)}
        except Exception:return [],{'provider':provider,'status':'error','count':0}
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(search,tools.items()))
    references=[];seen=set()
    # Keep a representative item from each provider before adding extra items.
    for rank in range(4):
        for rows,_ in results:
            if rank>=len(rows):continue
            row=rows[rank]
            if row['url'] not in seen:references.append({**row,'id':f'S{len(references)+1}'});seen.add(row['url'])
    return {'query':query,'searchedAt':stamp,'providers':[status for _,status in results],'references':references}

def reference_markdown(refs):
    if not refs:return ''
    lines=['## 도입부 외부 참고자료']
    for r in refs:
        title=re.sub(r'[\[\]\\\n]',' ',r['title'])
        lines.append(f"- [{r['id']}] [{title}](<{r['url']}>) — {r['provider']}, {r.get('publishedAt') or '발행일 미확인'}, 조회 {r['retrievedAt'][:10]} ({r['evidenceType']})")
    return '\n'.join(lines)
