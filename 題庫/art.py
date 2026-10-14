import sys,re
sys.path.insert(0,'.')
import make_expl as m
code=sys.argv[1]
for n in sys.argv[2:]:
    ls=m.arts(code).get(f'第{n}條')
    print(f'## {code} {n}')
    if not ls: print('  (無)'); continue
    for i,l in enumerate(ls,1): print(f'{i}. {l}')
