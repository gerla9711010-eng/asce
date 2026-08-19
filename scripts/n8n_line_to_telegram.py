# -*- coding: utf-8 -*-
"""把 n8n 裡「主動推播 LINE」的節點換成 Telegram 節點。

背景：LINE 官方帳號免費方案一個月只有 200 則主動推播，而且要留給客戶群發，
所以系統的告警／提醒一律改走 Telegram（無則數上限）。
只動 `message/push` 的節點，`message/reply`（關鍵字回覆，免費）完全不碰。

用法：
    python scripts/n8n_line_to_telegram.py            # 實際寫回 n8n
    python scripts/n8n_line_to_telegram.py --dry-run  # 只印出會改什麼

前置：n8n 裡要先有一組 telegramApi credential，把 id/name 填在下面 CRED。
Chat ID 是收訊人的 Telegram 使用者 ID（跟機器人講過話才拿得到）。
"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")

CRED = {"id": "yBF20qXez1b7FLFI", "name": "Telegram 業務助理 Bot"}
CHAT_ID = "1890720012"
TARGETS = ["KEIS 心跳檢查", "KEIS 待聯絡提醒", "靜默失敗巡邏", "KEIS 情資週報"]

DRY = "--dry-run" in sys.argv

env = {}
for line in open(".env", encoding="utf-8"):
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env[k] = v.strip()
BASE = env["N8N_URL"].rstrip("/")
HEADERS = {"X-N8N-API-KEY": env["N8N_API_KEY"], "Content-Type": "application/json"}


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


def rename_in_connections(conns, old, new):
    """n8n 的 connections 是用節點「名稱」當 key，改名字要連著改。"""
    out = {}
    for src, val in conns.items():
        nv = {}
        for typ, branches in val.items():
            nv[typ] = [
                [dict(c, node=(new if c["node"] == old else c["node"])) for c in (br or [])]
                for br in branches
            ]
        out[new if src == old else src] = nv
    return out


def main():
    for w in req("/api/v1/workflows?limit=250")["data"]:
        if w["name"] not in TARGETS:
            continue
        wf = req("/api/v1/workflows/" + w["id"])
        changed = False
        for n in wf["nodes"]:
            if "message/push" not in str(n.get("parameters", {}).get("url", "")):
                continue
            old_name = n["name"]
            new_name = "Telegram 告警"
            n["type"] = "n8n-nodes-base.telegram"
            n["typeVersion"] = 1.2
            n["name"] = new_name
            n["parameters"] = {
                "chatId": CHAT_ID,
                "text": "={{ $json.text }}",
                "additionalFields": {"appendAttribution": False},
            }
            n["credentials"] = {"telegramApi": CRED}
            # 情資週報的推播節點原本是停用的，換成 Telegram 後一併打開
            n.pop("disabled", None)
            wf["connections"] = rename_in_connections(wf["connections"], old_name, new_name)
            changed = True
            print("  %s：%s → %s" % (w["name"], old_name, new_name))
        if not changed:
            print("  %s：沒有 LINE Push 節點，跳過" % w["name"])
            continue
        if DRY:
            print("  → --dry-run，沒有寫回")
            continue
        res = req(
            "/api/v1/workflows/" + w["id"],
            {
                "name": wf["name"],
                "nodes": wf["nodes"],
                "connections": wf["connections"],
                "settings": wf.get("settings", {}),
            },
            "PUT",
        )
        print("  → 寫回 %s" % ("成功" if "ERR" not in res else res))


if __name__ == "__main__":
    main()
