import pdfplumber, re, json
H=re.compile(r'^([壹貳參肆伍陸柒捌玖拾])、(.+)$')
S=re.compile(r'^([一二三四五六七八九十]+)、(.+)$')
chap=sec=None
qs=[]; bad=[]
with pdfplumber.open('bank.pdf') as p:
    for pi in range(3,len(p.pages)):
        pg=p.pages[pi]
        items=[]
        for ln in pg.extract_text_lines():
            t=ln['text'].strip()
            m=H.match(t)
            if m and '題' not in t[-3:] or (m and len(t)<40): items.append((ln['top'],'H',t)); continue
            if S.match(t): items.append((ln['top'],'S',t))
        for tb in pg.find_tables():
            for r in tb.rows:
                row=pg.within_bbox(tuple(max(0,min(v,b)) for v,b in zip(r.bbox,(pg.width,pg.height,pg.width,pg.height)))).extract_text() if False else None
            data=tb.extract()
            for r,d in zip(tb.rows,data):
                items.append((r.bbox[1],'Q',d))
        items.sort(key=lambda x:x[0])
        for top,k,v in items:
            if k=='H': chap=v; sec=None
            elif k=='S': sec=v
            else:
                if v[0] and re.fullmatch(r'\d+',v[0].strip()) and v[2] and re.search(r'[A-D]',v[2]):
                    body=v[1].replace('\n','')
                    parts=re.split(r'\(([A-D])\)',v[1].replace('\n','\u0001'))
                    stem=parts[0].replace('\u0001','')
                    opts={}
                    for i in range(1,len(parts),2): opts[parts[i]]=parts[i+1].replace('\u0001','').strip()
                    ans=re.search(r'[A-D]',v[2]).group()
                    q=dict(chap=chap,sec=sec,no=v[0].strip(),page=pi+1,q=stem.strip(),opts=opts,ans=ans)
                    if len(opts)!=4 or ans not in opts: bad.append(q)
                    qs.append(q)
                elif v[1] and not v[0] and not v[2] and qs and v[1] not in ('題目','選項'):
                    pr=qs[-1]; last=None
                    for ln in v[1].split(chr(10)):
                        mm=re.match(r'\(([A-D])\)(.*)',ln.strip())
                        if mm: last=mm.group(1); pr['opts'][last]=mm.group(2).strip()
                        elif last: pr['opts'][last]+=ln.strip()
                        elif pr['opts']: k=list(pr['opts'])[-1]; pr['opts'][k]+=ln.strip(); last=k
                        else: pr['q']+=ln.strip()
                    if len(pr['opts'])==4: bad=[b for b in bad if not (b.get('no')==pr['no'] and b.get('page')==pr['page'] and b.get('q')==pr['q'])]
                elif any(v) and v[1] not in ('題目','選項') and v[0]!='題號': bad.append(dict(page=pi+1,raw=v))
json.dump(qs,open('qs_raw.json','w',encoding='utf-8'),ensure_ascii=False,indent=0)
print(len(qs),len(bad))
json.dump(bad,open('bad.json','w',encoding='utf-8'),ensure_ascii=False,indent=0)
from collections import Counter
c=Counter((q['chap'],q['sec']) for q in qs)
for k,v in c.items(): print(v,k)
