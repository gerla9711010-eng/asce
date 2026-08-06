# -*- coding: utf-8 -*-
"""廣告文案交叉審核 —— 誤擋測試（上線前必跑）。

擋錯一篇＝整整一班廣告沒發出去，所以「會不會誤擋」比「抓不抓得到」更關鍵。
做法：拿 Notion 上真的已發布過的文案（＝當初通過所有檢查、實際發到粉專的），
餵給審核員看它會不會擋。全部應該要 OK；擋下來的每一篇都要人工看過理由合不合理。

事實清單完全比照正式線：規格從 Notion 撈、**賣點原文從 KEIS 詳情 API 撈**
（賣點是文案的素材來源，少了它審核員會把每一句都判成編造——2026-08-04 踩過，
14 篇擋 12 篇）。

⚠️ Gemini 免費方案是「每個模型每天 20 次」，所以一天最多測 ~18 篇，而且會跟
正式線搶額度。測之前先確認不是在 09/11/13/15/17/19 整點前後。
（2026-08-04 就是因為連打 50 發把配額吃光，害 11:00 那班廣告在「產文案」失敗。）

2026-08-04 第一版 14 篇擋 12 篇，三個成因都修在 copy_review_nodes.json 的 prompt 裡：
  ① 事實清單漏了「賣點」——文案就是從賣點改寫的，審核員看不到當然每句都判編造
  ② 它會抱怨「漏寫車位/屋齡」——漏寫不是寫錯，廣告本來就不必寫滿，已列進「一律放行」
  ③ 缺資料的欄位被寫成「無」——「系統沒撈到」被當成「官方否認」。
     現在缺資料一律標「（官方沒有這筆資料，不代表沒有）」
  另外補了「車庫≠車位」：官方的車位欄位指有產權的登記車位（大樓那種），
  透天的車庫是空間、不會登記成車位，兩者不算矛盾。
修完後同一批前 4 篇從 0/4 變 3/4 通過。上線門檻＝零誤擋，或每個誤擋理由都站得住腳。

用法：
    python scripts/pending/verify_copy_review.py 14
"""
import json, os, re, sys, time, httpx
sys.stdout.reconfigure(encoding='utf-8')
ROOT = r'C:\Users\user\asce'
N = int(sys.argv[1]) if len(sys.argv) > 1 else 4


def le(p):
    d = {}
    for l in open(p, encoding='utf-8'):
        l = l.strip()
        if l and not l.startswith('#') and '=' in l:
            k, v = l.split('=', 1); d[k.strip()] = v.strip()
    return d


env = le(os.path.join(ROOT, '.env')); kenv = le(os.path.join(ROOT, 'scripts/keis/.env'))
B = env['N8N_URL'].rstrip('/')
H = {'X-N8N-API-KEY': env['N8N_API_KEY'], 'content-type': 'application/json'}
NH = {'Authorization': f"Bearer {kenv['KEIS_NOTION_TOKEN']}", 'Notion-Version': '2022-06-28',
      'content-type': 'application/json'}
DB = '07ee845168b64f8a9b5682e5069c733b'
API = 'https://keis.kshouse.com.tw/api/v1'
c = httpx.Client(timeout=150)

# --- KEIS 登入 ---
r = c.post(f'{API}/auth/login', params={'device_type': 'desktop'},
           data={'username': kenv['KEIS_USERNAME'], 'password': kenv['KEIS_PASSWORD']},
           headers={'content-type': 'application/x-www-form-urlencoded',
                    'referer': 'https://keis.kshouse.com.tw/login'})
r.raise_for_status()
KH = {'Authorization': f"Bearer {r.json()['access_token']}"}
print('KEIS 登入 OK')


def txt(p):
    if not p: return ''
    t = p.get('type')
    if t in ('rich_text', 'title'): return ''.join(x['plain_text'] for x in p[t])
    if t == 'number': return p['number'] if p['number'] is not None else ''
    if t == 'select': return (p['select'] or {}).get('name', '')
    return ''


d = c.post(f'https://api.notion.com/v1/databases/{DB}/query', headers=NH,
           json={'filter': {'property': '狀態', 'select': {'equals': '已發布'}},
                 'page_size': N + 10}).json()

cases = []
for p in d['results']:
    if len(cases) >= N: break
    pr = p['properties']
    fb = txt(pr.get('粉專文案'))
    kid = txt(pr.get('KEIS物件ID'))
    if not fb.strip() or not kid:
        continue
    try:
        dd = c.get(f'{API}/property-management/{int(kid)}', headers=KH).json()
    except Exception as e:
        print('  詳情撈不到', kid, e); continue
    o = dd.get('data') or dd
    賣點 = [str(o.get(f'feature_{i}') or '').strip() for i in range(1, 6)]
    賣點 = [x for x in 賣點 if x]
    if not 賣點:
        # 有些欄位名不同，掃一遍找像賣點的
        賣點 = [str(v).strip() for k, v in o.items()
                if re.match(r'(feature|selling|sell_point)', str(k)) and str(v).strip()
                and str(v).strip().lower() not in ('none', 'null')]
    cases.append({
        'contract_no': txt(pr.get('案件編號')), '案名': txt(pr.get('案名')),
        '地址': txt(pr.get('地址')),
        '總價萬': str(txt(pr.get('總價'))).replace('萬', '').strip(),
        '建物類型': txt(pr.get('建物類型')), '格局': txt(pr.get('格局')),
        '樓層': txt(pr.get('樓層')), '建物坪': txt(pr.get('建物坪數')),
        '主建坪': txt(pr.get('主建物坪數')), '屋齡': txt(pr.get('屋齡')),
        '車位': str(o.get('parking_type') or o.get('parking') or
                    ('有' if o.get('parking_space') else '') or ''),
        '學區': str(o.get('school_info') or ''),
        '賣點': 賣點,
        '機能': {'商圈': str(o.get('business_area') or ''), '捷運': str(o.get('mrt') or ''),
                 '公園': str(o.get('park') or '')},
        '粉專文案': fb, '社團文案': txt(pr.get('社團文案')),
    })
print(f'準備好 {len(cases)} 篇（賣點筆數：{[len(x["賣點"]) for x in cases]}）\n')
if not cases:
    sys.exit('沒有可測的資料')

pend = json.load(open(os.path.join(ROOT, 'scripts/pending/copy_review_nodes.json'), encoding='utf-8'))
rv = json.loads(json.dumps(pend['審核節點'])); vd = json.loads(json.dumps(pend['判定節點']))
rv['retryOnFail'] = False; rv.pop('maxTries', None)
vd['parameters']['jsCode'] = vd['parameters']['jsCode'].replace(
    "$('解析文案+footer')", "$('組測試資料')")
rv['position'] = [420, 0]; vd['position'] = [640, 0]; rv.pop('id', None); vd.pop('id', None)
P = 'tmp-review-fp6-20260804'
tmp = {"name": "TMP 交叉審核誤擋測試6（用完即刪）", "nodes": [
    {"id": "t0", "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
     "position": [0, 0],
     "parameters": {"httpMethod": "POST", "path": P, "responseMode": "lastNode", "options": {}}},
    {"id": "t1", "name": "組測試資料", "type": "n8n-nodes-base.code", "typeVersion": 2,
     "position": [200, 0],
     "parameters": {"jsCode": "return [{ json: $input.first().json.body }];"}}, rv, vd],
    "connections": {"Webhook": {"main": [[{"node": "組測試資料", "type": "main", "index": 0}]]},
                    "組測試資料": {"main": [[{"node": "文案交叉審核", "type": "main", "index": 0}]]},
                    "文案交叉審核": {"main": [[{"node": "審核判定", "type": "main", "index": 0}]]}},
    "settings": {"executionOrder": "v1"}}
r = c.post(f'{B}/api/v1/workflows', headers=H, json=tmp); r.raise_for_status()
wid = r.json()['id']
try:
    c.post(f'{B}/api/v1/workflows/{wid}/activate', headers=H).raise_for_status()
    time.sleep(3)
    url = f'{B}/webhook/{P}'; stat = {}
    for i, cs in enumerate(cases, 1):
        if i > 1: time.sleep(10)
        try:
            j = c.post(url, json=cs, timeout=120).json()
            if isinstance(j, list): j = j[0]
            v = j.get('_reviewVerdict') or 'ERR'; rsn = j.get('_reviewReason') or ''
        except Exception as ex:
            v, rsn = 'ERR', repr(ex)[:90]
        stat[v] = stat.get(v, 0) + 1
        print(f'[{i:>2}/{len(cases)}] {v:<5} {cs["contract_no"]} {cs["案名"][:20]}', flush=True)
        if v != 'OK' and rsn:
            print(f'          -> {rsn[:200]}', flush=True)
    print('\n=== 統計：', stat, f'（{len(cases)} 篇真實已發布文案，事實清單比照正式線）===')
finally:
    c.delete(f'{B}/api/v1/workflows/{wid}', headers=H)
    print('臨時 workflow 已刪除', wid)
