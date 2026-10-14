import json, re, html
from cards import C
b = json.load(open('data/bank.json', encoding='utf-8'))
CH = b['chaps']; QS = b['qs']
COL = ['#e4572e','#f18f01','#2e9e6b','#1b8fb5','#5b5bd6','#a23bb5','#d6336c','#4c6b22','#0b7285','#8a5a00']
def stars(n): return 3 if n>=15 else 2 if n>=8 else 1 if n>=4 else 0
tot = len(QS); per = {c: sum(1 for q in QS if q['c']==c) for c in range(1,11)}
# 100題最大餘數分配
raw = {c: per[c]*100/tot for c in per}; alloc = {c:int(raw[c]) for c in raw}
for c in sorted(raw, key=lambda c: raw[c]-alloc[c], reverse=True)[:100-sum(alloc.values())]: alloc[c]+=1
def fmt(s):
    s = html.escape(s)
    return re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', s)
data = {}
for c in range(1,11):
    qs = [q for q in QS if q['c']==c]; lst = []
    for t,l,k in C[c]:
        r = re.compile(k); n = sum(1 for q in qs if r.search(q['q']+q['o'][q['a']]))
        lst.append((stars(n), n, t, l))
    lst.sort(key=lambda x: (-x[0], -x[1])); data[c] = lst
css = '''
@page{size:A4;margin:9mm}
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif;color:#1d1d1f;margin:0;font-size:11.5px;line-height:1.55}
.cover{page-break-after:always}
h1{font-size:30px;margin:0 0 4px}
.sub{color:#555;margin-bottom:12px}
.how{display:flex;gap:8px;margin:10px 0}
.how div{flex:1;border:2px solid #222;border-radius:10px;padding:8px 10px;font-size:12px}
table.al{border-collapse:collapse;width:100%;margin:8px 0}
table.al td,table.al th{border:1px solid #bbb;padding:4px 6px;text-align:left;font-size:12px}
table.al th{background:#f2f2f2}
.top h2{font-size:15px;margin:10px 0 4px}
.chip{display:inline-block;background:#fff3b0;border-radius:6px;padding:1px 7px;margin:2px 3px 2px 0;font-weight:700}
.chap{page-break-before:always}
.chap h2{margin:0 0 8px;color:#fff;padding:8px 12px;border-radius:10px;font-size:19px;display:flex;justify-content:space-between;align-items:center}
.chap h2 small{font-size:12px;font-weight:400}
.grid{column-count:2;column-gap:10px}
.card{break-inside:avoid;border:2px solid;border-radius:10px;padding:6px 9px;margin:0 0 8px;background:#fff}
.card .hd{display:flex;justify-content:space-between;align-items:baseline;gap:6px;margin-bottom:3px}
.card .tt{font-weight:800;font-size:13.5px}
.card .st{font-size:14px;white-space:nowrap}
.card ul{margin:0;padding-left:15px}
.card li{margin:1px 0}
.card li.why{list-style:none;margin:0 0 3px -15px;background:#e8f1ff;border-radius:6px;padding:2px 6px;font-weight:600}
.card b{background:#fff3b0;padding:0 2px;border-radius:3px}
.card .n{color:#777;font-size:10px;text-align:right}
.s3{background:#fff8f0}
'''
out = ['<!doctype html><meta charset="utf-8"><title>租賃管理人員 重點整理</title><style>'+css+'</style>']
out.append('<div class="cover"><h1>🏠 租賃住宅管理人員 考前重點</h1><div class="sub">依 966 題題庫逐題對照整理（2026-10-12 補漏＋💡為什麼版）｜每章先看 ⭐⭐⭐ 卡第一行的 💡（為什麼／判斷法），再看細節；接著 ⭐⭐，其他有空再看</div>')
out.append('<div class="how"><div><b>⭐⭐⭐</b><br>題庫裡超常考，<br>必背</div><div><b>⭐⭐</b><br>常考，<br>第二輪背</div><div><b>⭐</b><br>偶爾考</div><div><b>無星</b><br>很少考，<br>最後看</div></div>')
out.append('<div class="sub">已對照條文（法規為 2026-10-05 全國法規資料庫最新版；租賃契約範本含 114/4/18 修正）：租賃條例、民法、稅法、消保法、公寓條例、都計法、非都規則、三種契約範本、調解條例、民訴、室內裝修辦法等；電氣水管常識、公安申報附表、圍籬這類「條文裡沒有」的，卡片上有標（題庫答案）。<br>星數＝題庫中和這張卡相關的題數（關鍵字比對，是估計值，不是精確統計）。<b>黃底</b>＝要背的字。</div>')
out.append('<h2 style="font-size:15px;margin:6px 0">📊 100 題模擬考各章會出幾題</h2><table class="al"><tr><th>章</th><th>主題</th><th>題庫</th><th>約出幾題</th></tr>')
for c in range(1,11): out.append(f'<tr><td>{c}</td><td>{html.escape(CH[str(c)])}</td><td>{per[c]}</td><td><b>{alloc[c]}</b></td></tr>')
out.append('</table><div class="top"><h2>⭐⭐⭐ 必背總覽</h2>')
for c in range(1,11):
    t3 = [t for s,n,t,l in data[c] if s==3]
    if t3: out.append(f'<div><b style="color:{COL[c-1]}">第{c}章</b> '+''.join(f'<span class="chip">{html.escape(t)}</span>' for t in t3)+'</div>')
out.append('</div></div>')
for c in range(1,11):
    col = COL[c-1]
    out.append(f'<div class="chap"><h2 style="background:{col}"><span>第{c}章｜{html.escape(CH[str(c)])}</span><small>題庫{per[c]}題・100題考約{alloc[c]}題</small></h2><div class="grid">')
    for s,n,t,l in data[c]:
        stx = '⭐'*s if s else '☆'
        cls = 's3' if s==3 else ''
        out.append(f'<div class="card {cls}" style="border-color:{col}"><div class="hd"><span class="tt">{html.escape(t)}</span><span class="st">{stx}</span></div><ul>'+''.join((f'<li class="why">{fmt(x)}</li>' if x.startswith('💡') else f'<li>{fmt(x)}</li>') for x in l)+f'</ul><div class="n">約 {n} 題相關</div></div>')
    out.append('</div></div>')
open('summary.html','w',encoding='utf-8').write(''.join(out))
print(alloc)
