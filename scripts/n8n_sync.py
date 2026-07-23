#!/usr/bin/env python3
"""n8n → git 同步 + 線上現況體檢

收工前跑這支就好：

    python scripts/n8n_sync.py            # 同步 + 產現況表
    python scripts/n8n_sync.py --check    # 只看差異，不寫檔（想先確認再說）

它做三件事：
1. 把 n8n 上全部 workflow 拉回 workflows/，git 從此等於 n8n（不用再手動匯出）
2. 產 docs/n8n-live.md：誰 active、最近執行時間、Notion 每個欄位被哪支 workflow 寫
3. 對出「n8n 有但 git 沒有」「git 有但 n8n 已刪」「Notion 有欄位但沒人寫」三種分岔

金鑰讀 .env 的 N8N_URL / N8N_API_KEY，Notion 欄位那段讀 scripts/keis/.env 的
KEIS_NOTION_TOKEN（沒有就跳過那段，不會壞）。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx

# Windows 主控台是 cp950，印到 ⚠ 這種字會整支炸掉。印不出來的字換成 ? 就好
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

ROOT = Path(__file__).resolve().parent.parent
WF_DIR = ROOT / "workflows"
MAP_FILE = WF_DIR / "_map.json"
REPORT = ROOT / "docs" / "n8n-live.md"
AD_DB_ID = "07ee845168b64f8a9b5682e5069c733b"
TPE = timezone(timedelta(hours=8))

# 這些欄位本來就不是 n8n 在寫，別報成問題
NOT_N8N = {
    "建立日期": "Notion 自動（created_time）",
    "廣告貼文紀錄": "桌面 /yc-ad skill append",
    "已撤除確認": "手動勾選",
}

# workflow JSON 只保留這幾個 key：其餘（id/versionId/updatedAt…）每次都會變，
# 留著會讓 git diff 全是雜訊，看不出真正改了什麼
KEEP = ("name", "nodes", "connections", "settings")
# n8n Public API 不吃 settings 裡的這些欄位，寫回去會 400
SETTINGS_OK = {
    "executionOrder", "saveDataErrorExecution", "saveDataSuccessExecution",
    "saveManualExecutions", "saveExecutionProgress", "timezone",
    "errorWorkflow", "executionTimeout",
}


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def slugify(name: str) -> str:
    """中文 workflow 名 → 檔名。中文留著沒關係，去掉檔名不能用的字元就好。"""
    s = re.sub(r"[\\/:*?\"<>|（）()\[\]]+", "", name).strip()
    s = re.sub(r"\s+", "-", s)
    return (s or "workflow") + ".json"


class N8n:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.h = {"X-N8N-API-KEY": key, "Content-Type": "application/json"}

    def get(self, path: str, **params):
        r = httpx.get(f"{self.url}/api/v1/{path}", headers=self.h, params=params, timeout=120)
        r.raise_for_status()
        return r.json()

    def workflows(self) -> list[dict]:
        return self.get("workflows", limit=250).get("data", [])

    def workflow(self, wid: str) -> dict:
        return self.get(f"workflows/{wid}")

    def executions(self, pages: int = 8) -> dict[str, list[tuple[str, str]]]:
        """回 {workflowId: [(startedAt, status), ...]}。n8n 有保留期限，撈得到多少算多少。"""
        out: dict[str, list[tuple[str, str]]] = defaultdict(list)
        cursor = None
        for _ in range(pages):
            params = {"limit": 250}
            if cursor:
                params["cursor"] = cursor
            data = self.get("executions", **params)
            for e in data.get("data", []):
                out[e["workflowId"]].append(((e.get("startedAt") or "?")[:16], e.get("status") or "?"))
            cursor = data.get("nextCursor")
            if not cursor:
                break
        return out


def notion_ad_fields(token: str) -> list[str]:
    """撈廣告 DB 現有欄位名。拿不到就回空 list，報告裡那段自動跳過。"""
    if not token:
        return []
    try:
        r = httpx.get(
            f"https://api.notion.com/v1/databases/{AD_DB_ID}",
            headers={"Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28"},
            timeout=60,
        )
        r.raise_for_status()
        return sorted(r.json().get("properties", {}).keys())
    except Exception as exc:  # 報告是輔助，不該因為 Notion 掛掉就整支失敗
        print(f"  ⚠ Notion 欄位撈取失敗，報告會少那一段：{exc}")
        return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比對不寫檔")
    args = ap.parse_args()

    env = load_env(ROOT / ".env")
    url, key = env.get("N8N_URL", ""), env.get("N8N_API_KEY", "")
    if not (url and key):
        print("✗ .env 缺 N8N_URL 或 N8N_API_KEY")
        return 1

    n8n = N8n(url, key)
    print("撈 n8n workflow 清單…")
    lst = n8n.workflows()
    print(f"  {len(lst)} 支")

    name_map: dict[str, str] = json.loads(MAP_FILE.read_text(encoding="utf-8")) if MAP_FILE.exists() else {}
    changed, added, unchanged = [], [], []

    for w in lst:
        wid = w["id"]
        full = n8n.workflow(wid)
        body = {k: full[k] for k in KEEP if k in full}
        fname = name_map.get(wid) or slugify(full["name"])
        if wid not in name_map:
            name_map[wid] = fname
            added.append(f"{full['name']} → {fname}")
        path = WF_DIR / fname
        new = json.dumps(body, ensure_ascii=False, indent=2)
        old = path.read_text(encoding="utf-8") if path.exists() else None
        if old is None or old.strip() != new.strip():
            changed.append(f"{fname}（{full['name']}）")
            if not args.check:
                path.write_text(new, encoding="utf-8")
        else:
            unchanged.append(fname)

    live_files = {name_map[w["id"]] for w in lst}
    orphans = sorted(
        p.name for p in WF_DIR.glob("*.json")
        if p.name != MAP_FILE.name and p.name not in live_files
    )

    if not args.check:
        MAP_FILE.write_text(json.dumps(name_map, ensure_ascii=False, indent=2), encoding="utf-8")

    print("撈執行紀錄…")
    execs = n8n.executions()
    fields = notion_ad_fields(load_env(ROOT / "scripts" / "keis" / ".env").get("KEIS_NOTION_TOKEN", ""))

    # 哪些 workflow 會寫哪個 Notion 欄位（靠欄位名出現在 workflow JSON 裡判斷）
    writers: dict[str, list[str]] = {f: [] for f in fields}
    if fields:
        for w in lst:
            s = json.dumps(n8n.workflow(w["id"]), ensure_ascii=False)
            for f in fields:
                if f"'{f}'" in s or f'"{f}"' in s:
                    writers[f].append(("" if w["active"] else "（停用）") + w["name"])

    now = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")
    L = [
        f"# n8n 線上現況（{now} 自動產生）",
        "",
        "> 這份是 `python scripts/n8n_sync.py` 產的，**不要手改**。",
        "> 它反映的是 n8n 上真正在跑的東西，跟 STATUS.md 的說法對不上時，以這份為準。",
        "",
        "## Workflow",
        "",
        "| 狀態 | 名稱 | 檔案 | 節點 | 最近執行 |",
        "|---|---|---|---|---|",
    ]
    for w in sorted(lst, key=lambda x: (not x["active"], x["name"])):
        ex = sorted(execs.get(w["id"], []), reverse=True)
        last = f"{ex[0][0]} {ex[0][1]}" if ex else "—"
        nodes = len(n8n.workflow(w["id"]).get("nodes", []))
        L.append(f"| {'🟢' if w['active'] else '⚪'} | {w['name']} | `{name_map[w['id']]}` | {nodes} | {last} |")

    if fields:
        L += ["", "## 廣告 DB 欄位｜誰在寫", "", "| 欄位 | workflow |", "|---|---|"]
        for f in fields:
            if writers[f]:
                who = "、".join(writers[f])
            elif f in NOT_N8N:
                who = f"—（{NOT_N8N[f]}）"
            else:
                who = "⚠️ 沒有任何 workflow"
            L.append(f"| {f} | {who} |")

    L += ["", "## 分岔檢查", ""]
    orphan_note = (
        [f"- ⚠️ **git 有但 n8n 沒有**（n8n 上被刪了？）：{'、'.join(orphans)}"] if orphans else []
    )
    L += orphan_note or ["- git 與 n8n 檔案一致"]
    if fields:
        dead = [f for f in fields if not writers[f] and f not in NOT_N8N]
        if dead:
            L.append(
                f"- ⚠️ **沒人寫的 Notion 欄位**（可能該刪，或有 n8n 以外的東西在寫）：{'、'.join(dead)}"
            )
        else:
            L.append("- Notion 欄位都有對應的寫入來源")
    L.append("")

    if not args.check:
        REPORT.write_text("\n".join(L), encoding="utf-8")

    print()
    print(f"{'【只檢查，沒寫檔】' if args.check else '完成'}")
    print(f"  有變更：{len(changed)} 支" + (f"  → {'、'.join(changed)}" if changed else ""))
    print(f"  沒變動：{len(unchanged)} 支")
    if added:
        print(f"  新認識的 workflow：{'、'.join(added)}")
    if orphans:
        print(f"  ⚠ git 有但 n8n 沒有：{'、'.join(orphans)}（確認是不是該刪掉）")
    if not args.check:
        print(f"  現況表 → {REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
