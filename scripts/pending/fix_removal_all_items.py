import json,urllib.request,sys
sys.stdout.reconfigure(encoding='utf-8')
env=dict(l.strip().split('=',1) for l in open('.env',encoding='utf-8') if '=' in l and not l.startswith('#'))
U=env['N8N_URL'].rstrip('/');K=env['N8N_API_KEY']
def req(m,p,b=None):
    r=urllib.request.Request(U+p,method=m,headers={'X-N8N-API-KEY':K,'Content-Type':'application/json'},data=json.dumps(b).encode() if b is not None else None)
    return json.load(urllib.request.urlopen(r,timeout=60))
wid='VgBAXwPWJ3EDyq1t'
w=req('GET',f'/api/v1/workflows/{wid}')
OK={"executionOrder","saveDataErrorExecution","saveDataSuccessExecution","saveManualExecutions","saveExecutionProgress","timezone","errorWorkflow","executionTimeout"}
for n in w['nodes']:
    if n['name']=='備妥刪文':
        c=n['parameters']['jsCode']
        a=c.index("const j = $json;")
        head=c[:a]
        body=c[a:]
        body=body.replace("const j = $json;","// ⚠️ 一定要 .all()：用 $json 只拿得到第一筆，2026-10-01 發現一班判 7 筆下架只刪 1 筆\nreturn $input.all().map(it => {\nconst j = it.json;",1)
        body=body.replace("return [{ json: { ...j, fbPostId: id, hasFbPost: !!id, hasFbUrl: !!url } }];","return { json: { ...j, fbPostId: id, hasFbPost: !!id, hasFbUrl: !!url } };\n});")
        n['parameters']['jsCode']=head+body
        print(n['parameters']['jsCode'])
    if n['name']=='判定刪除結果':
        n['parameters']['mode']='runOnceForEachItem'
        c=n['parameters']['jsCode']
        c=c.replace("return [{ json: { ...prep, fbDeleted: prep.hasFbPost && ok, fbDeleteFailed: failed, fbDeleteError: failed ? (errMsg || 'unknown') : '', markRemoved: ok } }];","return { json: { ...prep, fbDeleted: prep.hasFbPost && ok, fbDeleteFailed: failed, fbDeleteError: failed ? (errMsg || 'unknown') : '', markRemoved: ok } };")
        assert "return {" in c and "return [{" not in c
        n['parameters']['jsCode']=c
body={'name':w['name'],'nodes':w['nodes'],'connections':w['connections'],'settings':{k:v for k,v in w['settings'].items() if k in OK}}
if '--go' in sys.argv:
    req('PUT',f'/api/v1/workflows/{wid}',body)
    req('POST',f'/api/v1/workflows/{wid}/deactivate')
    print(req('POST',f'/api/v1/workflows/{wid}/activate').get('active'))
