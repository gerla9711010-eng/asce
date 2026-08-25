# -*- coding: utf-8 -*-
"""換一組新的 CODEX_COPY_TOKEN，並改成用 n8n credential 帶，不再 inline 寫進 workflow。

為什麼要做：舊做法是 server.py 每次開機把 token 當成 header 明碼塞進「Gemini 產文案」節點，
`n8n_sync.py` 一拉就把它同步進 **public** repo（08-19 起就在 git 歷史裡了）。
換 token 只解決一次，改成 credential 才是根治——credential 的值 n8n Public API 讀不出來，
workflow JSON 裡只留 credential id 跟名字。

這支做三件事（token 值全程只在本機，不印出來）：
  1. 產生一組新的隨機 token，寫回 repo 根目錄的 `.env`（gitignore 中）
  2. 在 n8n 建立／更新 credential「Codex 文案通道 Token」（type httpHeaderAuth）
  3. 把「Gemini 產文案」節點裡殘留的 inline `X-Codex-Token` header 清掉

做完要重啟 codex-copy 服務（server.py 開機時才會重讀 .env）。

用法：
    python scripts/codex-copy/rotate_token.py
    python scripts/codex-copy/rotate_token.py --dry-run
"""
import json
import re
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent.parent
ENV = Path(__file__).resolve().parent / ".env"   # token 住這裡（server.py load_dotenv 的那份）
REPO_ENV = ROOT / ".env"                          # n8n 金鑰住這裡
CRED_NAME = "Codex 文案通道 Token"
HEADER_NAME = "X-Codex-Token"
SCAN_WF = "ooctMtxcaHtGThuV"
DRY = "--dry-run" in sys.argv

env_text = ENV.read_text(encoding="utf-8")
repo_env_text = REPO_ENV.read_text(encoding="utf-8")
BASE = re.search(r"N8N_URL=(.+)", repo_env_text).group(1).strip().rstrip("/")
KEY = re.search(r"N8N_API_KEY=(.+)", repo_env_text).group(1).strip()
HEADERS = {"X-N8N-API-KEY": KEY, "Content-Type": "application/json"}

_WF_SETTINGS_OK = {"executionOrder", "errorWorkflow", "saveDataSuccessExecution",
                   "saveDataErrorExecution", "saveManualExecutions",
                   "saveExecutionProgress", "timezone", "executionTimeout",
                   "callerPolicy"}


def req(path, data=None, method=None):
    r = urllib.request.Request(
        BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers=HEADERS, method=method)
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return {"ERR": e.code, "body": e.read().decode()[:400]}


def main():
    new_token = secrets.token_urlsafe(32)

    if DRY:
        print("--dry-run：會產生新 token、寫回 .env、建 credential、清 inline header")
        return

    # 1. 寫回 .env（只換這一行，其他原封不動）
    if re.search(r"^CODEX_COPY_TOKEN=.*$", env_text, re.M):
        new_env = re.sub(r"^CODEX_COPY_TOKEN=.*$",
                         "CODEX_COPY_TOKEN=" + new_token, env_text, count=1, flags=re.M)
    else:
        new_env = env_text.rstrip("\n") + "\nCODEX_COPY_TOKEN=" + new_token + "\n"
    ENV.write_text(new_env, encoding="utf-8")
    print("1/3 scripts/codex-copy/.env 的 CODEX_COPY_TOKEN 已換新（值不印出來）")

    # 2. 建 credential。Public API 沒有「依名字查」的端點，重複建會多一筆同名的，
    #    所以把 id 記在 .env 裡，第二次執行就走更新。
    cred_id = (re.search(r"^CODEX_N8N_CRED_ID=(.+)$", new_env, re.M) or [None, None])[1]
    payload = {"name": CRED_NAME, "type": "httpHeaderAuth",
               "data": {"name": HEADER_NAME, "value": new_token}}
    if cred_id:
        cred_id = cred_id.strip()
        res = req("/api/v1/credentials/" + cred_id, payload, "PUT")
        if "ERR" in res:
            print("   更新舊 credential 失敗，改建一筆新的：", res)
            cred_id = None
    if not cred_id:
        res = req("/api/v1/credentials", payload)
        if "ERR" in res:
            print("2/3 建 credential 失敗：", res)
            return
        cred_id = res["id"]
        txt = ENV.read_text(encoding="utf-8").rstrip("\n")
        txt += "\n# n8n credential「%s」的 id（值本身讀不出來，這裡只記 id）\nCODEX_N8N_CRED_ID=%s\n" % (CRED_NAME, cred_id)
        ENV.write_text(txt, encoding="utf-8")
    print("2/3 n8n credential「%s」就緒，id=%s" % (CRED_NAME, cred_id))

    # 3. 清掉節點裡殘留的 inline header（credential 由 server.py 開通道時掛上）
    w = req("/api/v1/workflows/" + SCAN_WF)
    hit = False
    for n in w["nodes"]:
        if n["name"] != "Gemini 產文案":
            continue
        hdrs = ((n["parameters"].get("headerParameters") or {}).get("parameters") or [])
        before = len(hdrs)
        n["parameters"].setdefault("headerParameters", {})["parameters"] = [
            x for x in hdrs if x.get("name") != HEADER_NAME]
        hit = before != len(n["parameters"]["headerParameters"]["parameters"])
        break
    if not hit:
        print("3/3 節點裡沒有 inline X-Codex-Token，不用清")
        return
    payload = {"name": w["name"], "nodes": w["nodes"], "connections": w["connections"],
               "settings": {k: v for k, v in (w.get("settings") or {}).items()
                            if k in _WF_SETTINGS_OK}}
    res = req("/api/v1/workflows/" + SCAN_WF, payload, "PUT")
    if "ERR" in res:
        print("3/3 清 inline header 失敗：", res)
        return
    for act in ("deactivate", "activate"):
        req("/api/v1/workflows/%s/%s" % (SCAN_WF, act), method="POST")
    now = req("/api/v1/workflows/" + SCAN_WF)
    print("3/3 inline X-Codex-Token 已清掉，流程重開 active=%s" % now.get("active"))
    print("\n⚠️ 還要重啟 codex-copy 服務（server.py 開機時才重讀 .env）")


if __name__ == "__main__":
    main()
