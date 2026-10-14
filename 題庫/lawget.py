import re,sys,html,subprocess,urllib.parse
def fetch(u): return subprocess.run(['curl','-sL',u],capture_output=True).stdout.decode('utf-8','replace')
def search(kw):
    u='https://law.moj.gov.tw/Law/LawSearchResult.aspx?ty=ONEBAR&kw='+urllib.parse.quote(kw)
    s=fetch(u)
    return re.findall(r'LawAll\.aspx\?pcode=(\w+)[^>]*>([^<]+)<',s)
def get(pcode,out):
    s=fetch('https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode='+pcode)
    blocks=re.split(r'<div class="row"><div class="col-no">',s)[1:]
    txt=[];n=0
    for b in blocks:
        m=re.search(r'<a[^>]*>([^<]+)</a>',b[:600])
        if not m: continue
        no=re.sub(r'\s','',m.group(1))
        i=b.find('law-article')
        if i<0: continue
        body=b[i:]
        # 截到下一個 col-no 之前（已被 split 切開）
        lines=[html.unescape(re.sub(r'<[^>]+>','',l)).strip() for l in re.findall(r'<div class="line-\d+[^>]*>(.*?)</div>',body,re.S)]
        lines=[l for l in lines if l]
        if not lines: continue
        txt.append(no+chr(10)+chr(10).join(lines)); n+=1
    open(out,'w',encoding='utf-8').write((chr(10)*2).join(txt)); return n
if __name__=='__main__':
    if sys.argv[1]=='s':
        for kw in sys.argv[2:]: print(kw,search(kw)[:6])
    else: print(get(sys.argv[1],sys.argv[2]))
