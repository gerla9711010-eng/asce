#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把所有 Telegram 告警節點改成 HTML 模式，訊息在程式端先轉義。

背景（2026-09-23 事故，完整經過見 docs/incidents.md）：
n8n Telegram 節點沒設 parse_mode 時預設走 Markdown，客戶姓名出現「*小姐」這種字就會
400 `can't parse entities`，整包推不出去。訊息本來就沒在用粗體斜體，所以一律改 HTML，
並在上游 code 節點多產一個 `_tg` 欄位（= 轉義過的訊息），Telegram 節點只讀 `_tg`。
用新欄位而不是覆蓋原本的 text/summaryText，是為了不影響同一份資料的其他去處
（LINE 回覆、寫 Notion）。

用法：
  python scripts/n8n_telegram_html.py            # 只檢查，有問題回 exit 1
  python scripts/n8n_telegram_html.py --dry-run  # 印出會怎麼改，不寫回
  python scripts/n8n_telegram_html.py --fix      # 寫回 n8n（active 的會 deactivate+activate）
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# n8n Public API 的 PUT schema 比 GET 嚴格，這些以外的 settings 欄位送回去會 400
SETTINGS_OK = {
    "executionOrder", "saveDataErrorExecution", "saveDataSuccessExecution",
    "saveManualExecutions", "saveExecutionProgress", "timezone",
    "errorWorkflow", "executionTimeout",
}

ESC_JS = (
    "const esc = s => String(s ?? '').replace(/&/g, '&amp;')"
    ".replace(/</g, '&lt;').replace(/>/g, '&gt;'); "
    "// Telegram HTML 轉義，見 incidents.md 2026-09-23\n"
)

# workflow 名 → [(code 節點, 訊息變數, 對應的 Telegram 節點)]
# 訊息變數就是該 code 節點裡組好的字串，會多存一份轉義過的到 `_tg`
PATCHES = {
    "KEIS 搶單 LINE 通知": [("組 LINE 訊息", "text", ["Telegram 搶單通知"])],
    "KEIS 情資週報": [("分流：快取或告警", "text || '⚠️ 市場情資告警（無內容）'", ["Telegram 告警"])],
    "廣告v3 下架偵測線": [
        ("組刪文失敗通知", "text", ["Telegram 刪文失敗"]),
        ("組 KEIS 故障通知", "text", ["Telegram KEIS故障"]),
    ],
    "廣告v3 重發輪替線": [
        ("數字守門員", "msg", ["Telegram 守門員告警"]),
        ("組重發通知", "text", ["Telegram 重發通知"]),
        ("組價格未同步告警", "text", ["Telegram 價格未同步"]),
    ],
    "廣告v3 掃描發文線": [
        ("組預告", "text", ["Telegram 預告"]),
        ("組發文失敗訊息", "text", ["Telegram 發文失敗"]),
        ("本班收尾", "text", ["Telegram 跳過摘要"]),
        ("組發布通知", "text", ["Telegram 發布通知"]),
    ],
    "系統錯誤 LINE 告警": [("組錯誤訊息", "text", ["Telegram 系統錯誤"])],
    "靜默失敗巡邏": [("組訊息", "text", ["Telegram 告警"])],
}

# 這些 Telegram 節點的內容不經過 code 節點，但內容不可能含 & < >：
# 只改 parse_mode 就夠（Markdown 底下會炸是因為 KEIS 欄位名有底線，HTML 沒這問題）
PARSE_MODE_ONLY = {
    ("廣告v3 掃描發文線", "Telegram 體檢告警"),
    ("廣告v3 掃描發文線", "Telegram 詳情欄位告警"),
    # 09-23 已單獨修好、等 09-24 09:00 驗收，轉義寫在 code 節點裡，別再動
    ("KEIS 待聯絡提醒", "Telegram 告警"),
}

RET_RE = re.compile(r"^([ \t]*)return \[\{ json: \{ (.+) \} \}\];[ \t]*$", re.M)


def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


class N8n:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.h = {"X-N8N-API-KEY": key, "Content-Type": "application/json"}

    def call(self, path: str, data=None, method=None):
        r = urllib.request.Request(
            self.url + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers=self.h,
            method=method,
        )
        return json.load(urllib.request.urlopen(r, timeout=120))

    def workflows(self):
        return self.call("/api/v1/workflows?limit=250")["data"]

    def workflow(self, wid):
        return self.call(f"/api/v1/workflows/{wid}")

    def put(self, wid, wf):
        return self.call(
            f"/api/v1/workflows/{wid}",
            {
                "name": wf["name"],
                "nodes": wf["nodes"],
                "connections": wf["connections"],
                "settings": {k: v for k, v in wf.get("settings", {}).items() if k in SETTINGS_OK},
            },
            "PUT",
        )


def patch_code(js: str, expr: str, where: str) -> str:
    """在 code 節點的 item return 裡補上 `_tg`（= 轉義過的訊息）。已經有就不動。"""
    if "_tg:" in js:
        return js
    hits = [m for m in RET_RE.finditer(js) if expr in m.group(2)]
    if len(hits) != 1:
        raise SystemExit(f"✗ {where}：找不到唯一一個帶 `{expr}` 的 item return（找到 {len(hits)} 個），沒改")
    m = hits[0]
    new_ret = f"{m.group(1)}return [{{ json: {{ {m.group(2)}, _tg: esc({expr}) }} }}];"
    return ESC_JS + js[: m.start()] + new_ret + js[m.end():]


def patch_workflow(wf: dict, jobs) -> list:
    """回傳這支 workflow 改了哪些東西（空 list = 本來就合規）。"""
    log = []
    nodes = {n["name"]: n for n in wf["nodes"]}
    for code_name, expr, tg_names in jobs:
        node = nodes.get(code_name)
        if node is None:
            raise SystemExit(f"✗ {wf['name']}：找不到 code 節點「{code_name}」")
        js = node["parameters"]["jsCode"]
        new_js = patch_code(js, expr, f"{wf['name']} / {code_name}")
        if new_js != js:
            node["parameters"]["jsCode"] = new_js
            log.append(f"{code_name}：訊息多存一份轉義過的 _tg")
        for tg in tg_names:
            t = nodes.get(tg)
            if t is None:
                raise SystemExit(f"✗ {wf['name']}：找不到 Telegram 節點「{tg}」")
            if t["parameters"].get("text") != "={{ $json._tg }}":
                t["parameters"]["text"] = "={{ $json._tg }}"
                log.append(f"{tg}：text → $json._tg")
    for n in wf["nodes"]:
        if n["type"].endswith(".telegram"):
            af = n["parameters"].setdefault("additionalFields", {})
            if af.get("parse_mode") != "HTML":
                af["parse_mode"] = "HTML"
                log.append(f"{n['name']}：parse_mode → HTML")
    return log


def check(wf: dict) -> list:
    """回傳這支 workflow 不合規的地方。"""
    bad = []
    # 有沒有人在產 _tg。少了這個檢查，code 節點被手改掉 `_tg` 會變成 Telegram 收到空字串
    # （400 message text is empty），而且是在「負責報告其他故障」的那條線上無聲死掉
    has_producer = any(
        n["type"].endswith(".code") and "_tg:" in n["parameters"].get("jsCode", "")
        for n in wf["nodes"]
    )
    for n in wf["nodes"]:
        if not n["type"].endswith(".telegram"):
            continue
        p = n["parameters"]
        if p.get("additionalFields", {}).get("parse_mode") != "HTML":
            bad.append(f"{wf['name']} / {n['name']}：parse_mode 不是 HTML（預設 Markdown 會被 * _ [ 炸掉）")
            continue
        if (wf["name"], n["name"]) in PARSE_MODE_ONLY:
            continue
        if p.get("text") != "={{ $json._tg }}":
            bad.append(f"{wf['name']} / {n['name']}：text 沒讀轉義過的 $json._tg（現在是 {p.get('text')!r}）")
        elif not has_producer:
            bad.append(f"{wf['name']} / {n['name']}：讀 $json._tg 但整支 workflow 沒有 code 節點在產 _tg（會推出空訊息）")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="寫回 n8n")
    ap.add_argument("--dry-run", action="store_true", help="印出會怎麼改，不寫回")
    args = ap.parse_args()

    env = load_env(ROOT / ".env")
    if not (env.get("N8N_URL") and env.get("N8N_API_KEY")):
        print("✗ .env 缺 N8N_URL 或 N8N_API_KEY")
        return 1
    n8n = N8n(env["N8N_URL"], env["N8N_API_KEY"])
    lst = n8n.workflows()

    if not (args.fix or args.dry_run):
        bad = []
        for w in lst:
            bad += check(n8n.workflow(w["id"]))
        if bad:
            print("⚠️ Telegram 節點不合規（Markdown 模式遲早會被客戶姓名炸掉）：")
            for b in bad:
                print("  ·", b)
            print("  → 修：python scripts/n8n_telegram_html.py --fix")
            return 1
        print("✅ 所有 Telegram 節點都是 HTML 模式且訊息有轉義")
        return 0

    touched = []
    for w in lst:
        wf = n8n.workflow(w["id"])
        jobs = PATCHES.get(w["name"], [])
        if not jobs and not any(n["type"].endswith(".telegram") for n in wf["nodes"]):
            continue
        log = patch_workflow(wf, jobs)
        if not log:
            print(f"— {w['name']}：本來就合規")
            continue
        print(f"▶ {w['name']}（{'active' if w['active'] else '停用'}）")
        for line in log:
            print("   ·", line)
        if args.dry_run:
            continue
        n8n.put(w["id"], wf)
        touched.append((w["id"], w["name"], w["active"]))

    if args.dry_run or not touched:
        return 0

    print("\n改過的 active workflow 重新 deactivate+activate（排程才會吃到新版）：")
    for wid, name, was_active in touched:
        if not was_active:
            print(f"  {name}：本來就沒 active，跳過")
            continue
        try:
            n8n.call(f"/api/v1/workflows/{wid}/deactivate", method="POST")
            n8n.call(f"/api/v1/workflows/{wid}/activate", method="POST")
            print(f"  {name}：OK")
        except urllib.error.HTTPError as e:
            print(f"  {name}：✗ {e.code} {e.read().decode()[:200]}")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
