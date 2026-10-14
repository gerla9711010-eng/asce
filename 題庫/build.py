import json,glob
bank=json.load(open('data/bank.json',encoding='utf-8'))
expl={}
for f in sorted(glob.glob('expl/*.json')):
    expl.update(json.load(open(f,encoding='utf-8')))
ids={q['id'] for q in bank['qs']}
extra=set(expl)-ids
assert not extra,f'解說有不存在的題目: {sorted(extra)[:5]}'
t=open('template.html',encoding='utf-8').read()
t=t.replace('/*BANK*/null',json.dumps(bank,ensure_ascii=False)).replace('/*EXPL*/null',json.dumps(expl,ensure_ascii=False))
open('index.html','w',encoding='utf-8').write(t)
print(f'題 {len(ids)}｜解說 {len(expl)}｜缺 {len(ids-set(expl))}')
