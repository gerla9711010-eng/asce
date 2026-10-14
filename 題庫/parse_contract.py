"""把契約 PDF 文字（law/pdf/*.txt）切成「第N條」(＝第N點) 格式，供 make_expl.cite 使用"""
import re,sys
CN='一二三四五六七八九十'
def cn(s):
    n=0
    if s=='十': return 10
    if s.startswith('十'): return 10+CN.index(s[1])+1
    if s.endswith('十'): return (CN.index(s[0])+1)*10
    if '十' in s: a,b=s.split('十'); return (CN.index(a)+1)*10+CN.index(b)+1
    return CN.index(s)+1
MARK=re.compile(r'^(（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|\d+[\.、]|□|[一二三四五六七八九十]+、)')
def clean(t):
    t=re.sub(r'=====P\d+\n','',t)
    t=re.sub(r'行政院公報[^\n]*\n','',t)
    t=re.sub(r'\n- \d+ -(?=\n|$)','',t)
    t=re.sub(r'\n\d+\n(?======|$)','\n',t)
    return t
def split_points(text):
    pts={};cur=None;n=1
    for ln in clean(text).split('\n'):
        ln=ln.strip()
        if not ln: continue
        m=re.match(r'^([一二三四五六七八九十]+)、(.*)$',ln)
        if m and cn(m.group(1))>=n:
            cur=cn(m.group(1)); pts[cur]=[m.group(2).strip()] if m.group(2).strip() else []; n=cur+1; continue
        if cur: pts[cur].append(ln)
    out={}
    for k,ls in pts.items():
        paras=[]
        for ln in ls:
            if paras and not MARK.match(ln) and not re.search(r'[。：；]$',paras[-1]):
                paras[-1]+=ln
            else: paras.append(ln)
        out[k]=paras
    return out
def parse(text,start=None,end=None):
    t=clean(text)
    if start: t=t[t.index(start)+len(start):]
    if end: t=t[:t.index(end)]
    return split_points(t)
def override(name,pts):
    cur={}
    for blk in open(f'law/{name}.txt',encoding='utf-8').read().split(chr(10)*2):
        ls=blk.split(chr(10)); cur[int(ls[0][1:-1])]=ls[1:]
    cur.update(pts)
    open(f'law/{name}.txt','w',encoding='utf-8').write((chr(10)*2).join(f'第{k}條'+chr(10)+chr(10).join(v) for k,v in sorted(cur.items())))
def write(name,text,start=None,end=None):
    t=clean(text)
    if start: t=t[t.index(start)+len(start):]
    if end: t=t[:t.index(end)]
    pts=split_points(t)
    open(f'law/{name}.txt','w',encoding='utf-8').write('\n\n'.join(f'第{k}條\n'+'\n'.join(v) for k,v in pts.items()))
    return len(pts)
if __name__=='__main__':
    R=lambda f:open(f'law/pdf/{f}.txt',encoding='utf-8').read()
    print('租賃應記載',write('租賃應記載',R('d1'),'壹、應記載事項','貳、不得記載事項'))
    print('租賃不得',write('租賃不得記載',R('d1'),'貳、不得記載事項'))
    print('包租應約定',write('包租應約定',R('包租'),None,'貳、不得約定事項'))
    print('包租不得',write('包租不得約定',R('包租'),'貳、不得約定事項','附件一'))
    print('轉租應記載',write('轉租應記載',R('轉租'),'壹、應記載事項','貳、不得記載事項'))
    print('轉租不得',write('轉租不得記載',R('轉租'),'貳、不得記載事項','附件一'))
    print('委託應記載',write('委託應記載',R('委託'),'壹、應記載事項','貳、不得記載事項'))
    print('委託不得',write('委託不得記載',R('委託'),'貳、不得記載事項','附件'))

    # 113 年修正：租賃 6、11（d4）；轉租 6、11、18、不得記載新增第10點（d3）
    override('租賃應記載',parse(R('d4'),'壹、應記載事項'))
    d3=R('d3'); i=d3.index('貳貳、、不不得得記記載載事事項項')
    override('轉租應記載',parse(d3[:i],'壹壹、、應應記記載載事事項項'))
    override('轉租不得記載',parse(d3[i:],'貳貳、、不不得得記記載載事事項項','附件一'))
