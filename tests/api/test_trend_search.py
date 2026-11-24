from langchain_core.tools import StructuredTool
from apps.api import trend_search as search


def tool(name, fn):
    return StructuredTool.from_function(fn, name=name, description='Synthetic reference search')


def test_sources_and_partial_failures():
    def good(query:str):
        return [{'title':'Study','url':'https://doi.org/10.123/test','summary':'<p>Measured results</p>','evidenceType':'abstract'}, {'title':'Unsafe','url':'javascript:alert(1)'}]
    def failure(query:str):raise TimeoutError()
    def missing(query:str):raise search.MissingSearchKey('YOUTUBE_API_KEY')
    def empty(query:str):return []
    result=search.search_references('medical AI', {n:tool(n,f) for n,f in [('academic',good),('news',failure),('youtube',missing),('wikipedia',empty)]})
    assert len(result['references'])==1
    assert result['references'][0]['summary']=='Measured results'
    assert result['references'][0]['id']=='S1'
    assert [s['status'] for s in result['providers']]==['success','error','notConfigured','empty']
    assert 'https://doi.org/10.123/test' in search.reference_markdown(result['references'])


def test_duckduckgo_backend(monkeypatch):
    import ddgs
    class FakeDDGS:
        def __init__(self,**kwargs):pass
        def text(self,query,**kwargs):
            assert kwargs['backend']=='duckduckgo'
            return [{'title':'Result','href':'https://example.org','body':'Snippet'}]
    monkeypatch.setattr(ddgs,'DDGS',FakeDDGS)
    assert search.build_tools()['duckduckgo'].invoke({'query':'topic'})[0]['evidenceType']=='searchSnippet'


def test_tavily_domains_are_enforced(monkeypatch):
    import langchain_tavily
    monkeypatch.setenv('TAVILY_API_KEY','synthetic')
    class FakeTavily:
        def __init__(self,**kwargs):assert kwargs['include_domains']==list(search.NEWS_DOMAINS)
        async def ainvoke(self,payload):
            return {'results':[{'title':'Allowed','url':'https://www.yna.co.kr/view/test'}, {'title':'Geek','url':'https://news.hada.io/topic?id=1'}, {'title':'Excluded','url':'https://yna.co.kr.other.example/test'}]}
    monkeypatch.setattr(langchain_tavily,'TavilySearch',FakeTavily)
    assert len(search.tavily_news('topic'))==2


def test_youtube_without_key(monkeypatch):
    import youtube_search
    monkeypatch.delenv('YOUTUBE_API_KEY',raising=False)
    class FakeSearch:
        def __init__(self,query,**kwargs):
            assert kwargs=={'max_results':3,'retries':0,'timeout':12}
        def to_dict(self):
            return [{'id':'123','title':'Video','long_desc':'Description','publish_time':'2 days ago'}]
    monkeypatch.setattr(youtube_search,'YoutubeSearch',FakeSearch)
    result=search.search_references('topic',{'youtube':search.build_tools()['youtube']})
    assert result['providers'][0]['status']=='success'
    assert result['references'][0]['evidenceType']=='videoMetadata'
    assert result['references'][0]['publishedAt'] is None
