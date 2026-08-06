# -*- coding: utf-8 -*-
"""把「廣告文案交叉審核」接進廣告v3 掃描發文線。

⚠️ 這是**還沒上線**的東西，2026-08-04 做好但誤擋率還沒測夠（見 docs/STATUS.md）。
    要先跑 verify_copy_review.py 確認誤擋率可接受，再用 --deploy 真的推上 n8n。

它做什麼
    解析文案+footer → [文案交叉審核] → [審核判定] → 數字守門員
    審核員用 gemini-2.5-flash（跟產文案的 flash-lite 是不同模型），
    看不到生成過程，只拿到「官方事實 + 賣點原文 + 寫好的文案」，回 OK / NG。
    NG 會被數字守門員的第 (4) 項接住，走現成的「建 Notion 草稿列 → LINE 告警 → 換下一件」，
    不會炸掉整班。

用法
    python scripts/pending/apply_copy_review.py            # 只改本機 workflows/*.json
    python scripts/pending/apply_copy_review.py --deploy   # 改完直接推上 n8n 並重啟該 workflow
"""
import json, os, sys, time

sys.stdout.reconfigure(encoding='utf-8')  # Windows 主控台是 cp950，不轉會被 emoji 噎到

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WF = os.path.join(ROOT, 'workflows', 'yc-v3-scan-publish.json')
NODES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'copy_review_nodes.json')

GUARD_OLD = "const ok = badNums.length === 0 && banned.length === 0 && 殘骸.length === 0;"
GUARD_NEW = """// (4) 交叉審核（2026-08-04 加）：第二個模型當路人看過一遍，抓語意層的問題
// （混到別間物件、前後矛盾、不像人寫的）。SKIP＝審核員自己壞掉，一律放行。
const 審核 = [];
if (j['_reviewVerdict'] === 'NG') 審核.push(String(j['_reviewReason'] || '審核員未說明原因'));

const ok = badNums.length === 0 && banned.length === 0 && 殘骸.length === 0 && 審核.length === 0;"""
MSG_OLD = "  (殘骸.length ? `・文案本身壞掉：${殘骸.join('、')}\\n` : '') +"
MSG_NEW = MSG_OLD + "\n  (審核.length ? `・交叉審核擋下：${審核.join('、')}\\n` : '') +"
RET_OLD = "_guardJunk: 殘骸, _guardMsg: msg }"
RET_NEW = "_guardJunk: 殘骸, _guardReview: 審核, _guardMsg: msg }"


def apply_to(wf):
    names = {n['name'] for n in wf['nodes']}
    if '文案交叉審核' in names:
        print('⚠️ 已經有審核節點了，不重複加')
        return False
    pend = json.load(open(NODES, encoding='utf-8'))
    wf['nodes'].append(pend['審核節點'])
    wf['nodes'].append(pend['判定節點'])

    c = wf['connections']
    tgt = c['解析文案+footer']['main'][0][0]['node']
    assert tgt == '數字守門員', f'解析文案+footer 現在接的是 {tgt}，接線變了，先確認再套用'
    c['解析文案+footer'] = {"main": [[{"node": "文案交叉審核", "type": "main", "index": 0}]]}
    c['文案交叉審核'] = {"main": [[{"node": "審核判定", "type": "main", "index": 0}]]}
    c['審核判定'] = {"main": [[{"node": "數字守門員", "type": "main", "index": 0}]]}

    g = [n for n in wf['nodes'] if n['name'] == '數字守門員'][0]
    code = g['parameters']['jsCode']
    for old, new in ((GUARD_OLD, GUARD_NEW), (MSG_OLD, MSG_NEW), (RET_OLD, RET_NEW)):
        assert old in code, f'數字守門員的程式碼變了，對不到：{old[:40]}'
        code = code.replace(old, new)
    g['parameters']['jsCode'] = code
    return True


def main():
    deploy = '--deploy' in sys.argv
    wf = json.load(open(WF, encoding='utf-8'))
    if not apply_to(wf):
        return
    json.dump(wf, open(WF, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f'✅ 已套用到 {WF}（節點數 {len(wf["nodes"])}）')

    if not deploy:
        print('（沒有 --deploy，只改了本機檔案，n8n 上還是舊版）')
        return

    import httpx
    env = {}
    for line in open(os.path.join(ROOT, '.env'), encoding='utf-8'):
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1); env[k.strip()] = v.strip()
    B = env['N8N_URL'].rstrip('/')
    H = {'X-N8N-API-KEY': env['N8N_API_KEY'], 'content-type': 'application/json'}
    c = httpx.Client(timeout=120)
    live = c.get(f'{B}/api/v1/workflows', headers=H, params={'limit': 250}).json()['data']
    target = [x for x in live if x['name'] == '廣告v3 掃描發文線']
    assert len(target) == 1, f'在 n8n 上找到 {len(target)} 支同名 workflow，先確認哪一支在跑'
    wid = target[0]['id']
    # n8n Public API 不吃 settings 裡的 binaryMode／availableInMCP，整包丟回去會 400
    # （2026-08-06 踩到；白名單跟 scripts/n8n_sync.py 的 SETTINGS_OK 一致）
    SETTINGS_OK = {'executionOrder', 'saveDataErrorExecution', 'saveDataSuccessExecution',
                   'saveManualExecutions', 'saveExecutionProgress', 'timezone',
                   'errorWorkflow', 'executionTimeout'}
    body = {'name': wf['name'], 'nodes': wf['nodes'], 'connections': wf['connections'],
            'settings': {k: v for k, v in wf.get('settings', {}).items() if k in SETTINGS_OK}}
    c.put(f'{B}/api/v1/workflows/{wid}', headers=H, json=body).raise_for_status()
    print('已更新 n8n workflow', wid)
    # 🔴 CLAUDE.md 規則：改已啟用的 workflow 後一定要 deactivate + activate，否則排程還在跑舊版
    c.post(f'{B}/api/v1/workflows/{wid}/deactivate', headers=H).raise_for_status()
    time.sleep(2)
    c.post(f'{B}/api/v1/workflows/{wid}/activate', headers=H).raise_for_status()
    print('已 deactivate + activate（排程觸發器已吃到新版）')
    print('\n接下來：跑 python scripts/n8n_sync.py 讓 git 跟 n8n 對齊')


if __name__ == '__main__':
    main()
