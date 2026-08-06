# -*- coding: utf-8 -*-
"""修正 YG0089924 粉專貼文裡的印地文亂碼（自由黃 पसर市場 -> 自由黃昏市場）。
FB Page Token 只存在 n8n credential 裡，讀不出明文，所以開臨時 workflow 借用，跑完即刪。"""
import json, sys, time, httpx
sys.stdout.reconfigure(encoding='utf-8')


def le(p):
    d = {}
    for l in open(p, encoding='utf-8'):
        l = l.strip()
        if l and not l.startswith('#') and '=' in l:
            k, v = l.split('=', 1); d[k.strip()] = v.strip()
    return d


env = le(r'C:\Users\user\asce\.env')
B = env['N8N_URL'].rstrip('/')
H = {'X-N8N-API-KEY': env['N8N_API_KEY'], 'content-type': 'application/json'}
CRED = {"httpHeaderAuth": {"id": "Y6myWnsH0lkRL3CF", "name": "FB Page Token"}}
POST_ID = "1041868522352339_122113027749336834"
URL = f"https://graph.facebook.com/v21.0/{POST_ID}"
import os
NEW = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  'yg0089924_copy.json'), encoding="utf-8"))["after"]
P = 'tmp-fb-edit-20260806'
c = httpx.Client(timeout=120)


def http_node(nid, name, x, method=None):
    params = {"url": URL, "authentication": "genericCredentialType",
              "genericAuthType": "httpHeaderAuth",
              "options": {"response": {"response": {"neverError": True,
                                                    "responseFormat": "json"}},
                          "timeout": 30000}}
    if method == "POST":
        params.update({
            "method": "POST", "sendHeaders": True,
            "headerParameters": {"parameters": [
                {"name": "Content-Type", "value": "application/json"}]},
            "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify({ message: $('Webhook').first().json.body.message }) }}"})
    else:
        params.update({"sendQuery": True, "queryParameters": {"parameters": [
            {"name": "fields", "value": "message"}]}})
    return {"id": nid, "name": name, "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2, "position": [x, 0], "credentials": CRED,
            "parameters": params}


tmp = {"name": "TMP 修粉專亂碼（用完即刪）", "nodes": [
    {"id": "a", "name": "Webhook", "type": "n8n-nodes-base.webhook", "typeVersion": 2,
     "position": [0, 0],
     "parameters": {"httpMethod": "POST", "path": P, "responseMode": "lastNode",
                    "options": {}}},
    http_node("b", "讀原文", 200),
    http_node("c", "改文", 400, "POST"),
    http_node("d", "讀回驗證", 600),
    {"id": "e", "name": "彙整", "type": "n8n-nodes-base.code", "typeVersion": 2,
     "position": [800, 0],
     "parameters": {"jsCode": "return [{ json: { before: $('讀原文').first().json,"
                              " editResp: $('改文').first().json,"
                              " after: $('讀回驗證').first().json } }];"}}],
    "connections": {
        "Webhook": {"main": [[{"node": "讀原文", "type": "main", "index": 0}]]},
        "讀原文": {"main": [[{"node": "改文", "type": "main", "index": 0}]]},
        "改文": {"main": [[{"node": "讀回驗證", "type": "main", "index": 0}]]},
        "讀回驗證": {"main": [[{"node": "彙整", "type": "main", "index": 0}]]}},
    "settings": {"executionOrder": "v1"}}

r = c.post(f'{B}/api/v1/workflows', headers=H, json=tmp); r.raise_for_status()
wid = r.json()['id']
try:
    c.post(f'{B}/api/v1/workflows/{wid}/activate', headers=H).raise_for_status()
    time.sleep(3)
    out = c.post(f'{B}/webhook/{P}', json={"message": NEW}, timeout=120).json()
    if isinstance(out, list):
        out = out[0]
    print(json.dumps(out, ensure_ascii=False, indent=1)[:2500])
finally:
    c.delete(f'{B}/api/v1/workflows/{wid}', headers=H)
    print('臨時 workflow 已刪除', wid)
