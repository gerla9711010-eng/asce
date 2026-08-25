# -*- coding: utf-8 -*-
"""FB 發文系統／搶公買系統 補回主動推播，改推 Telegram（不動原本寫系統日誌的節點）。

背景：2026-08-14 為了省 LINE 200 則配額，把這幾支流程「發文失敗／刪文失敗／KEIS故障／
API體檢告警／跳過摘要／守門員告警／系統錯誤／搶單成功」的主動推播全拔了，改成只寫
Notion 系統日誌，要靠「工作回報」關鍵字回覆才看得到。現在 Telegram 沒有則數上限
（見 scripts/n8n_line_to_telegram.py），使用者要求這幾個事件改回主動推。

做法：在原本「組訊息 → 寫系統日誌」的地方，從同一個來源節點多接一條 Telegram push
節點出去（並聯，不影響系統日誌那支）。

用法：
    python scripts/n8n_add_telegram_push.py            # 實際寫回 n8n
    python scripts/n8n_add_telegram_push.py --dry-run  # 只印出會改什麼
"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

CRED = {"id": "yBF20qXez1b7FLFI", "name": "Telegram 業務助理 Bot"}
CHAT_ID = "1890720012"
DRY = "--dry-run" in sys.argv

env = {}
for line in open(".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v.strip()
BASE = env["N8N_URL"].rstrip("/")
HEADERS = {"X-N8N-API-KEY": env["N8N_API_KEY"], "Content-Type": "application/json"}

# 每個目標：workflow 檔名、來源節點名、要接的 branch index、telegram 節點名、text 表達式
JOBS = [
    ("keis-grab-notify.json", "組 LINE 訊息", 0, "Telegram 搶單通知",
     "={{ $json.text }}"),
    ("yc-v3-scan-publish.json", "組發文失敗訊息", 0, "Telegram 發文失敗",
     "={{ $json.text }}"),
    ("yc-v3-scan-publish.json", "欄位還在?", 1, "Telegram 體檢告警",
     "={{ 'KEIS 列表少了欄位 ' + ($json._missing || []).join('、') + '（撈到 ' + $json._count + ' 筆）。這輪沒發，要修程式。' }}"),
    ("yc-v3-scan-publish.json", "本班收尾", 0, "Telegram 跳過摘要",
     "={{ $json.text }}"),
    ("yc-v3-removal.json", "組刪文失敗通知", 0, "Telegram 刪文失敗",
     "={{ $json.summaryText }}"),
    ("yc-v3-removal.json", "組 KEIS 故障通知", 0, "Telegram KEIS故障",
     "={{ $json.summaryText }}"),
    ("yc-v3-repost.json", "數字都有出處?", 1, "Telegram 守門員告警",
     "={{ $json._guardMsg }}"),
    ("系統錯誤-LINE-告警.json", "組錯誤訊息", 0, "Telegram 系統錯誤",
     "={{ $json.text }}"),
]


def req(path, data=None, method=None):
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=HEADERS,
        method=method,
    )
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return {"ERR": e.code, "body": e.read().decode()[:400]}


def make_telegram_node(name, position, text_expr):
    return {
        "parameters": {
            "chatId": CHAT_ID,
            "text": text_expr,
            "additionalFields": {"appendAttribution": False},
        },
        "type": "n8n-nodes-base.telegram",
        "typeVersion": 1.2,
        "position": position,
        "name": name,
        "credentials": {"telegramApi": CRED},
    }


def main():
    all_wf = req("/api/v1/workflows?limit=250")["data"]
    by_name = {w["name"]: w for w in all_wf}

    jobs_by_file = {}
    for fname, src, branch, tg_name, text_expr in JOBS:
        jobs_by_file.setdefault(fname, []).append((src, branch, tg_name, text_expr))

    touched_wf_ids = []

    for fname, jobs in jobs_by_file.items():
        local = json.load(open("workflows/" + fname, encoding="utf-8"))
        wf_name = local["name"]
        remote = by_name.get(wf_name)
        if not remote:
            print("找不到對應的 n8n workflow：", wf_name)
            continue
        wf = req("/api/v1/workflows/" + remote["id"])
        node_by_name = {n["name"]: n for n in wf["nodes"]}
        changed = False
        for src, branch, tg_name, text_expr in jobs:
            if tg_name in node_by_name:
                print(f"  {wf_name}：{tg_name} 已存在，跳過")
                continue
            src_node = node_by_name.get(src)
            if not src_node:
                print(f"  [找不到來源節點] {wf_name}：{src}")
                continue
            pos = [src_node["position"][0], src_node["position"][1] + 200]
            tg_node = make_telegram_node(tg_name, pos, text_expr)
            wf["nodes"].append(tg_node)
            node_by_name[tg_name] = tg_node
            conns = wf["connections"].setdefault(src, {}).setdefault("main", [])
            while len(conns) <= branch:
                conns.append([])
            conns[branch].append({"node": tg_name, "type": "main", "index": 0})
            changed = True
            print(f"  {wf_name}：{src} --(branch {branch})--> 新增 {tg_name}")
        if not changed:
            continue
        if DRY:
            print("  → --dry-run，沒有寫回")
            continue
        settings = dict(wf.get("settings", {}))
        # PUT schema 比 GET 回傳的嚴格，這兩個欄位會被拒絕（400: must NOT have additional properties）
        settings.pop("binaryMode", None)
        settings.pop("availableInMCP", None)
        res = req(
            "/api/v1/workflows/" + remote["id"],
            {
                "name": wf["name"],
                "nodes": wf["nodes"],
                "connections": wf["connections"],
                "settings": settings,
            },
            "PUT",
        )
        print("  → 寫回", "成功" if "ERR" not in res else res)
        if "ERR" not in res:
            touched_wf_ids.append((remote["id"], wf_name, remote.get("active")))

    if DRY or not touched_wf_ids:
        return

    print("\n改完的 active workflow 重新 deactivate+activate：")
    for wid, name, was_active in touched_wf_ids:
        if not was_active:
            print(f"  {name}：本來就沒 active，跳過")
            continue
        r1 = req(f"/api/v1/workflows/{wid}/deactivate", method="POST")
        r2 = req(f"/api/v1/workflows/{wid}/activate", method="POST")
        ok = "ERR" not in r1 and "ERR" not in r2
        print(f"  {name}：{'成功' if ok else (r1, r2)}")


if __name__ == "__main__":
    main()
