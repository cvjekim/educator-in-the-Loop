"""Conservative, deterministic import suggestions; the educator confirms before saving."""
import re


def parse_syllabus(text):
    fields={'goals':'','mainTextbooks':'','supplementaryTextbooks':''}
    weeks=[];current=None;section=None
    headings={'goals':r'교과\s*목표|강의\s*목표|학습\s*목표|수업\s*목표|course goals|learning objectives|goals',
              'mainTextbooks':r'주교재|주\s*교재|주\s*교과서|main textbooks?',
              'supplementaryTextbooks':r'부교재|부\s*교재|참고\s*교재|참고\s*문헌|supplementary textbooks?'}
    for raw in text.replace('\x00','').splitlines():
        line=re.sub(r'^\s*#{1,6}\s*','',raw).strip().replace('**','')
        if not line:continue
        heading=re.sub(r'^\d+[.)]\s*','',line)
        found=False
        for field,pattern in headings.items():
            match=re.match(r'^(?:'+pattern+r')\s*(?:[:：]\s*(.*))?$',heading,re.I)
            if match:
                if current and field=='goals':
                    current['objectives']=match[1] or ''
                else:
                    section=field;current=None
                    if match[1]:fields[field]+=('\n' if fields[field] else '')+match[1]
                found=True;break
        if found:continue
        # Markdown tables and explicit week headings are accepted. Numbered
        # lists are treated as weeks only outside recognized section bodies.
        match=re.match(r'^\|?\s*(?:Week\s*)?(\d{1,2})\s*(?:주차|주|[.)]|:(?=\s)|(?=\|))\s*[:：|\-]?\s*(.+)',line,re.I)
        if match and (section is None or re.search(r'주차|\bWeek\b|^\|',line,re.I)):
            n=int(match[1]);parts=[v.strip() for v in match[2].strip('|').split('|')]
            if 1<=n<=52 and not any(w['weekNumber']==n for w in weeks):
                current={'weekNumber':n,'topic':parts[0][:200],'content':' | '.join(parts[1:])[:10000],'objectives':''}
                weeks.append(current);section=None;continue
        if re.search(r'주차별|주별\s*(계획|주제)|weekly\s*(plan|topics)',heading,re.I):section=None;current=None;continue
        if current:
            key='objectives' if line.startswith(('학습 목표:', '학습목표:')) else 'content'
            current[key]+= ('\n' if current[key] else '')+line
        elif section:
            fields[section]+= ('\n' if fields[section] else '')+line
    return {**{k:v[:10000] for k,v in fields.items()},'weeks':[{**w,'content':w['content'][:10000],'objectives':w['objectives'][:3000]} for w in weeks]}


def render_syllabus(plan,weeks):
    parts=['# 강의계획서','## 강의 목표',plan['goals'],'## 주교재',plan['mainTextbooks'],'## 부교재',plan['supplementaryTextbooks'],'## 주차별 계획']
    for w in weeks:
        parts.extend([f"### {w['weekNumber']}주차: {w['topic']}",f"학습 목표: {w['objectives']}",w['content']])
    return '\n\n'.join(parts)
