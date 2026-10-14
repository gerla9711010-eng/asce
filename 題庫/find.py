import sys,re
sys.path.insert(0,'.')
import make_expl as m
code=sys.argv[1]; pat=re.compile(sys.argv[2]); w=int(sys.argv[3]) if len(sys.argv)>3 else 130
for k,v in m.arts(code).items():
    for i,l in enumerate(v,1):
        if pat.search(l): print(f'{k}#{i}: {l[:w]}')
