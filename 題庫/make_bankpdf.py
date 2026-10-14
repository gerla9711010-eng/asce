"""題庫＋答案＋解說 → bank_print.html（再用 Chrome headless 印成 PDF）
題目/選項/答案直接取 data/bank.json，解說取 expl/*.json（跟模擬題網頁同一份資料），不改任何字。"""
import json, glob, re, html
bank = json.load(open('data/bank.json', encoding='utf-8'))
expl = {}
for f in glob.glob('expl/*.json'):
    expl.update(json.load(open(f, encoding='utf-8')))
E = html.escape
L = 'ABCD'
out = []
cur_c = cur_s = None
for q in bank['qs']:
    c, s = str(q['c']), f"{q['c']}-{q['s']}"
    if c != cur_c:
        cur_c = c
        out.append(f'<h1>第 {c} 章　{E(bank["chaps"][c])}</h1>')
    if s != cur_s:
        cur_s = s
        out.append(f'<h2>{s}　{E(bank["secs"].get(s, ""))}</h2>')
    x = expl.get(q['id'], {})
    a = q['a']
    opts = ''.join(
        f'<li class="{"ok" if i == a else ""}"><b>{L[i]}</b> {E(o)}{" ✔" if i == a else ""}'
        + (f'<span class="why">→ {E(x["opts"][i])}</span>' if i != a and x.get('opts') and x['opts'][i] else '')
        + '</li>' for i, o in enumerate(q['o']))
    src = '、'.join(dict.fromkeys(re.findall(r'【([^】]+)】', x.get('law', ''))))
    out.append(
        f'<div class="q"><div class="qt"><span class="id">{q["id"]}</span>{E(q["q"])}</div>'
        f'<ol>{opts}</ol>'
        f'<div class="ans">答案：{L[a]}　{E(x.get("note", ""))}</div>'
        + (f'<div class="flag">⚠️ {E(x["flag"])}</div>' if x.get('flag') else '')
        + (f'<div class="src">出處：{E(src)}</div>' if src else '')
        + '</div>')

css = '''@page{size:A4;margin:9mm}
body{font-family:"Microsoft JhengHei","Noto Sans TC",sans-serif;color:#1d1d1f;margin:0;font-size:11px;line-height:1.5}
h1{font-size:17px;background:#1f4e79;color:#fff;padding:5px 9px;margin:0 0 6px;break-before:page}
h1:first-of-type{break-before:auto}
h2{font-size:13px;color:#1f4e79;border-bottom:1.5px solid #1f4e79;margin:8px 0 4px;padding-bottom:1px}
.q{border:1px solid #d0d7de;border-radius:5px;padding:5px 8px;margin:0 0 5px;break-inside:avoid}
.qt{font-weight:bold}.id{display:inline-block;background:#eef2f6;color:#555;font-weight:normal;font-size:10px;padding:0 4px;border-radius:3px;margin-right:5px}
ol{list-style:none;margin:2px 0;padding:0}li{margin:1px 0}
li.ok{color:#0a6b2a;font-weight:bold}
.why{color:#777;font-size:10px;margin-left:6px}
.ans{background:#eaf6ee;padding:2px 6px;border-radius:3px;margin-top:2px}
.flag{background:#fff4e0;padding:2px 6px;border-radius:3px;margin-top:2px;font-size:10.5px}
.src{color:#888;font-size:9.5px;margin-top:1px}
.cover{text-align:center;padding-top:80px;break-after:page}.cover h1{background:none;color:#1f4e79;font-size:26px;break-before:auto}'''
cover = (f'<div class="cover"><h1>租賃住宅管理人員　題庫＋答案＋解說</h1>'
         f'<p>共 {len(bank["qs"])} 題｜題目、選項、答案逐字取自模擬題（與原始題庫 PDF 相同）</p>'
         '<p>綠色 ✔＝正解｜灰字→＝該錯誤選項為什麼錯｜⚠️＝題庫答案和現行條文不同，考試照題庫</p>'
         '<p>2026-10-12 版</p></div>')
doc = f'<!doctype html><html><head><meta charset="utf-8"><title>題庫解說</title><style>{css}</style></head><body>{cover}{"".join(out)}</body></html>'
open('bank_print.html', 'w', encoding='utf-8').write(doc)
print('題數', len(bank['qs']), '有解說', sum(1 for q in bank['qs'] if q['id'] in expl))
