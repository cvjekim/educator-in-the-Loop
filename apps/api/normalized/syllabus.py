"""Format adapters feed one conservative syllabus model; no inferred learning goals."""
import re

FIELDS = {
    'goals': r'교육\s*목표|교과(?:목)?\s*목표|강의\s*목표|학습\s*목표|수업\s*목표|course goals|learning objectives|goals',
    'mainTextbooks': r'주\s*교재|주\s*교과서|main textbooks?',
    'supplementaryTextbooks': r'부\s*교재|참고\s*교재|참고\s*문헌|supplementary textbooks?',
}
WEEK_SECTION = r'(?:주차별|주별)\s*(?:계획|주제|수업계획)?|수업\s*계획|강의\s*일정|weekly\s*(?:plan|topics|schedule)'
COLUMN_NAMES = {
    'weekNumber': {'주순','주차','주','주차번호','week','weeknumber'},
    'topic': {'학습주제','주제','강의주제','topic'},
    'content': {'학습내용','주차별내용','강의내용','내용','content'},
    'objectives': {'학습목표','수업목표','목표','objectives','learningobjectives'},
}


def clean(value):
    return str(value or '').replace('\x00','').replace('**','').strip()


def number(value):
    match=re.fullmatch(r'(?:week\s*)?(\d{1,2})\s*(?:주차|주)?',clean(value),re.I)
    return int(match[1]) if match and 1<=int(match[1])<=52 else None


def columns(row):
    result={}
    for i,cell in enumerate(row):
        name=re.sub(r'\s+','',clean(cell)).lower()
        for field,names in COLUMN_NAMES.items():
            if name in names:result[field]=i
    return result if 'weekNumber' in result and 'topic' in result else None


def table_weeks(rows):
    """PDF cells, Markdown cells and tab-separated cells share column mapping."""
    mapping=None;weeks=[]
    for row in rows:
        header=columns(row)
        if header:mapping=header;continue
        if mapping is None:continue
        values={field:clean(row[i]) if i<len(row) else '' for field,i in mapping.items()}
        n=number(values.get('weekNumber'))
        if n and values.get('topic'):
            weeks.append({'weekNumber':n,'topic':values['topic'],
                          'content':values.get('content',''),'objectives':values.get('objectives','')})
        elif not clean(values.get('weekNumber')) and weeks:
            # Continued PDF table row; do not invent a new week.
            for field in ('topic','content','objectives'):
                if values.get(field):weeks[-1][field]+='\n'+values[field]
    return weeks


def parse_syllabus(text,tables=None):
    fields={key:'' for key in FIELDS};weeks=[];current=None;section=None;weekly=False;target='content'
    extracted=[w for rows in tables or [] for w in table_weeks(rows)]
    rows=[]
    def flush():
        nonlocal rows
        parsed=table_weeks(rows)
        if not parsed and weekly:
            # Backward-compatible headerless table, only in an explicit weekly section.
            for row in rows:
                if len(row)>=2 and number(row[0]) and clean(row[1]):
                    parsed.append({'weekNumber':number(row[0]),'topic':clean(row[1]),'content':clean(row[2]) if len(row)>2 else '', 'objectives':''})
        weeks.extend(parsed);rows=[]
    for raw in text.replace('\x00','').splitlines():
        line=re.sub(r'^\s*#{1,6}\s*','',clean(raw))
        if not line:continue
        if line.lower().startswith('powered by tcpdf'):continue
        # Delimiters carry column boundaries; whitespace inside prose never does.
        cells=None
        if '|' in line:cells=re.split(r'(?<!\\)\|',line.strip('|'))
        elif '\t' in raw:cells=raw.strip(' \r\n').split('\t')
        elif re.search(r'\s{2,}',raw.strip()):cells=re.split(r'\s{2,}',raw.strip())
        if cells and (rows or columns(cells) or weekly and number(cells[0])):
            rows.append(cells);continue
        if rows:flush();current=None
        heading=re.sub(r'^\d+[.)]\s*','',line)
        if re.fullmatch(WEEK_SECTION,heading,re.I):
            weekly=True;section=None;current=None;continue
        matched=False
        for field,pattern in FIELDS.items():
            m=re.fullmatch(r'(?:'+pattern+r')\s*(?:[:：]\s*(.*))?',heading,re.I)
            if m:
                if current and field=='goals':
                    target='objectives'
                    if m[1]:current[target]+= ('\n' if current[target] else '')+m[1]
                else:
                    current=None;section=field;weekly=False
                    if m[1]:fields[field]+= ('\n' if fields[field] else '')+m[1]
                matched=True;break
        if matched:continue
        m=re.match(r'^(?:학습\s*내용|주차별\s*내용|내용|content)\s*[:：]\s*(.*)$',line,re.I)
        if current and m:
            target='content';current[target]+= ('\n' if current[target] else '')+m[1];continue
        # Explicit weeks are safe anywhere; bare numbered items are never weeks
        # outside a weekly section. This prevents section numbers and objectives
        # from becoming bogus week records.
        m=re.match(r'^(?:(\d{1,2})\s*(?:주차|주)|week\s*(\d{1,2}))\s*[:：.\-]?\s+(.+)$',line,re.I)
        if not m:
            m=re.match(r'^(\d{1,2})\s*(?:주차|주)\s*[:：]\s*(.+)$',line)
            if m:m=(m[1],None,m[2])
        else:m=(m[1],m[2],m[3])
        if not m and weekly:
            bare=re.match(r'^(\d{1,2})[.)]\s+(.+)$',line)
            if bare:m=(bare[1],None,bare[2])
        if m:
            n=int(m[0] or m[1]);topic=m[2]
            if 1<=n<=52:
                if extracted:current=None;section=None;continue
                current={'weekNumber':n,'topic':topic,'content':'','objectives':''}
                weeks.append(current);section=None;target='content';continue
        # Numbered document sections and unrelated labelled metadata end a field.
        if re.match(r'^\d+\.\s+\D',line) or re.match(r'^(?:참고영상|수업방법|성적평가|과제물|공지사항)\s*[:：]?',heading):
            current=None;section=None;weekly=False;continue
        if current:
            current[target]+= ('\n' if current[target] else '')+line
        elif section:
            fields[section]+= ('\n' if fields[section] else '')+line
    if rows:flush()
    result={}
    for w in extracted or weeks:
        # A repeated header/page must not replace a previously parsed week.
        if w['weekNumber'] not in result:
            result[w['weekNumber']]={**w,'topic':w['topic'][:200],'content':w['content'][:10000],'objectives':w['objectives'][:3000]}
    return {**{k:v[:10000] for k,v in fields.items()},'weeks':[result[n] for n in sorted(result)]}


def render_syllabus(plan,weeks):
    parts=['# 강의계획서','## 강의 목표',plan['goals'],'## 주교재',plan['mainTextbooks'],'## 부교재',plan['supplementaryTextbooks'],'## 주차별 계획']
    for w in weeks:
        parts.extend([f"### {w['weekNumber']}주차: {w['topic']}",f"학습 목표: {w['objectives']}",f"학습 내용: {w['content']}"])
    return '\n\n'.join(parts)
