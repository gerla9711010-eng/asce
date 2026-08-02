"""廣告發文看門狗——住在 n8n 外面，只問「今天廣告有沒有真的發出去」。

為什麼需要這支
--------------
2026-07 Postgres volume 塞爆、2026-08-01 `EXECUTIONS_DATA_SAVE_ON_SUCCESS` 被設成 none，
兩次都是同一種災難：**流程看起來在跑，但產不出東西，而且所有告警都沉默。**

原因是 n8n 裡那三道監控（errorTrigger 告警、靜默失敗巡邏、心跳檢查）全都在看
「機器有沒有在動」，而且靜默失敗巡邏讀的正是 n8n 自己的執行紀錄——監控跟病人共用同一個
器官，器官壞了兩邊一起躺平。2026-08-01 那次執行紀錄整個不寫，巡邏就判定「這半小時沒有
新執行，一切正常」，五檔廣告卡在「待發」快一天沒人知道。

所以這支刻意做成：
  * **完全不碰 n8n**——不讀執行紀錄、不管流程長怎樣，n8n 整台燒掉它照樣會叫
  * **只看結果**——直接問 Notion 廣告 DB「東西有沒有做出來」
  * **走繞過 n8n 的直推 LINE**（`KEIS_LINE_DIRECT_TOKEN`，跟 grab.py 的最後防線同一條路）

兩個判斷
--------
1. 有「待發」卡超過 30 分鐘 → 告警。這是 Wait 節點失效的精確指紋，也涵蓋「FB 權杖過期
   發不出去」那類。掃描發文線的煞車窗口是 10 分鐘，抓 30 分鐘留足緩衝。
2. 過了 14:00 還沒有任何一筆「今天已發布」→ 告警。保底網，抓所有整條線靜悄悄停擺的狀況，
   不管原因是什麼（09/11/13 三班都跑完了才判，不會冤枉）。

用法
----
    python ad_watchdog.py          # 跑一次就結束，給工作排程器每小時叫一次
    python ad_watchdog.py --dry    # 只印不推 LINE，測試用

需要 .env（跟 grab.py 同一份）：
    KEIS_NOTION_TOKEN        讀 Notion 廣告 DB
    KEIS_LINE_DIRECT_TOKEN   繞過 n8n 直推 LINE
    YC_AD_NOTION_DB_ID       可選，預設就是廣告 DB
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

# ====== 可調參數 ======
STUCK_MINUTES = 30        # 「待發」卡超過幾分鐘算異常（煞車窗口是 10 分鐘，留足緩衝）
NO_PUBLISH_HOUR = 14      # 幾點之後還沒有任何「今天已發布」就告警（09/11/13 三班跑完了）
NO_PUBLISH_UNTIL = 23     # 保底檢查只在這個鐘點前做，深夜不吵
# =====================

TPE = timezone(timedelta(hours=8))
HERE = Path(__file__).parent
STATE_FILE = HERE / "ad_watchdog_state.json"
LOG_FILE = HERE / "logs" / "ad-watchdog.log"
LOG_KEEP_LINES = 3000

NOTION_TOKEN = (os.environ.get("KEIS_NOTION_TOKEN") or os.environ.get("NOTION_TOKEN", "")).strip()
AD_DB_ID = os.environ.get("YC_AD_NOTION_DB_ID", "07ee845168b64f8a9b5682e5069c733b").strip()
LINE_DIRECT_TOKEN = os.environ.get("KEIS_LINE_DIRECT_TOKEN", "").strip()
LINE_PUSH_USERID = os.environ.get("KEIS_LINE_PUSH_USERID",
                                  "Ufab42c56b2eb9b9a9ff18c367b85a6dd").strip()

# Windows 主控台是 cp950，印到 emoji 會整支炸掉
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")


def log(msg: str) -> None:
    line = f"{datetime.now(TPE):%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        LOG_FILE.parent.mkdir(exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8-sig") as f:
            f.write(line + "\n")
        # 單檔滾動：超過就砍掉前面一半，不留一堆日檔
        lines = LOG_FILE.read_text(encoding="utf-8-sig").splitlines()
        if len(lines) > LOG_KEEP_LINES:
            LOG_FILE.write_text("\n".join(lines[-LOG_KEEP_LINES // 2:]) + "\n",
                                encoding="utf-8-sig")
    except Exception:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    except Exception as e:
        log(f"⚠ 狀態檔寫不進去（下次可能重複告警）：{e}")


def push_line(text: str, dry: bool = False) -> bool:
    """繞過 n8n 直接打 LINE Messaging API。這是整支的重點——n8n 死了它還能叫。"""
    if dry:
        print("\n--- [--dry] 這則不會真的送出 ---\n" + text + "\n--------------------------------\n")
        return True
    if not LINE_DIRECT_TOKEN:
        log("🚨 要告警但沒設 KEIS_LINE_DIRECT_TOKEN，只能寫 log")
        return False
    try:
        r = httpx.post(
            "https://api.line.me/v2/bot/message/push",
            headers={"Authorization": f"Bearer {LINE_DIRECT_TOKEN}",
                     "Content-Type": "application/json"},
            json={"to": LINE_PUSH_USERID, "messages": [{"type": "text", "text": text}]},
            timeout=10,
        )
        if r.status_code >= 400:
            log(f"🚨 LINE 推播被拒：{r.status_code} {r.text[:200]}")
            return False
        return True
    except Exception as e:
        log(f"🚨 LINE 推播送不出去（可能斷網）：{e}")
        return False


def notion_query(body: dict) -> dict:
    r = httpx.post(
        f"https://api.notion.com/v1/databases/{AD_DB_ID}/query",
        headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
        json=body, timeout=30,
    )
    r.raise_for_status()
    return r.json()


def plain(prop: dict | None) -> str:
    if not prop:
        return ""
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in (v or []))
    if t == "select":
        return (v or {}).get("name", "")
    return ""


def check_stuck(state: dict, now: datetime, dry: bool) -> bool:
    """判斷一：有「待發」卡超過 STUCK_MINUTES 分鐘。回傳這輪有沒有推出告警。

    每個物件每天最多提醒一次——卡住通常要人工處理，處理期間不該一小時吵一次；
    但隔天還卡著就再提醒一次，免得被忘記。
    """
    j = notion_query({
        "page_size": 25,
        "filter": {"property": "狀態", "select": {"equals": "待發"}},
        "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
    })
    today = now.strftime("%Y-%m-%d")
    alerted = state.setdefault("stuck_alerted", {})   # {page_id: 最後告警日期}
    stuck = []
    for page in j.get("results", []):
        created = datetime.fromisoformat(page["created_time"].replace("Z", "+00:00"))
        age_min = (now - created).total_seconds() / 60
        if age_min < STUCK_MINUTES:
            continue                                   # 還在正常煞車窗口內
        if alerted.get(page["id"]) == today:
            continue                                   # 今天已經提醒過這一筆
        pr = page["properties"]
        stuck.append({
            "id": page["id"],
            "no": plain(pr.get("案件編號")) or "(無編號)",
            "name": plain(pr.get("案名"))[:24] or "(無案名)",
            "since": created.astimezone(TPE).strftime("%m-%d %H:%M"),
            "hours": age_min / 60,
        })

    # 清掉不再是「待發」的舊紀錄，狀態檔才不會越長越大
    live = {p["id"] for p in j.get("results", [])}
    for pid in list(alerted):
        if pid not in live:
            del alerted[pid]

    if not stuck:
        log(f"待發卡關檢查：正常（{len(j.get('results', []))} 筆待發，都還在煞車窗口內）")
        return False

    lines = [f"・{s['no']} {s['name']}\n　{s['since']} 建列，卡了 {s['hours']:.1f} 小時"
             for s in stuck]
    text = (f"🔕 廣告卡在「待發」發不出去（{len(stuck)} 筆）\n\n"
            + "\n\n".join(lines)
            + "\n\n預告已經發了、FB 沒發成。常見原因：\n"
              "・n8n 的 EXECUTIONS_DATA_SAVE_ON_SUCCESS 被改成 none（Wait 節點會整條死掉）\n"
              "・FB 粉專權杖過期\n"
              "・Railway 上 n8n 掛了\n\n"
              "查法：Railway 看 Primary/Worker 有沒有異常重部署，n8n 執行紀錄有沒有斷。")
    if push_line(text, dry):
        for s in stuck:
            alerted[s["id"]] = today
        log(f"🚨 已告警：{len(stuck)} 筆待發卡關（{', '.join(s['no'] for s in stuck)}）")
        return True
    return False


def check_no_publish(state: dict, now: datetime, dry: bool) -> None:
    """判斷二：過了 NO_PUBLISH_HOUR 還沒有任何一筆「今天已發布」。

    這是保底網——就算「待發」那條判斷因為某些原因沒抓到（例如整條線連 Notion 列都沒建），
    這裡照樣會叫。每天最多一次。
    """
    if not (NO_PUBLISH_HOUR <= now.hour < NO_PUBLISH_UNTIL):
        return
    today = now.strftime("%Y-%m-%d")
    if state.get("no_publish_alerted") == today:
        return

    start_utc = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    j = notion_query({
        "page_size": 5,
        "filter": {"and": [
            {"property": "狀態", "select": {"equals": "已發布"}},
            {"timestamp": "created_time", "created_time": {"on_or_after": start_utc.isoformat()}},
        ]},
    })
    n = len(j.get("results", []))
    if n:
        log(f"今日發布檢查：正常（今天已發布 {n} 筆）")
        return

    text = ("🔕 廣告線今天整天沒發出任何一篇\n\n"
            f"到 {now:%H:%M} 為止，Notion 廣告 DB 沒有任何一筆今天的「已發布」。\n"
            "掃描發文線 09:00／11:00／13:00 三班都應該跑完了。\n\n"
            "代表整條線靜悄悄停擺了——注意 n8n 介面上可能完全看不到錯誤。\n"
            "先看 Railway 的 Primary/Worker 狀態與最近部署時間。")
    if push_line(text, dry):
        state["no_publish_alerted"] = today
        log("🚨 已告警：今天整天沒有任何已發布")


def main() -> int:
    ap = argparse.ArgumentParser(description="廣告發文看門狗（不依賴 n8n）")
    ap.add_argument("--dry", action="store_true", help="只印不推 LINE")
    args = ap.parse_args()

    if not NOTION_TOKEN:
        log("✗ 沒設 KEIS_NOTION_TOKEN，查不了 Notion，直接結束")
        return 1

    now = datetime.now(TPE)
    state = load_state()
    try:
        # 卡關告警已經推出去就不再推保底那則——兩則講的是同一件事，一次一則就好
        if not check_stuck(state, now, args.dry):
            check_no_publish(state, now, args.dry)
    except httpx.HTTPError as e:
        # 門市每晚 00:00~約 07:22 固定斷網，那段時間查不到 Notion 是正常的，不告警
        # （而且真的斷網時 LINE 也推不出去，叫了也沒用）
        log(f"連不上 Notion，這輪跳過（斷網時屬正常）：{e}")
        return 0
    if not args.dry:
        save_state(state)   # --dry 不留痕跡，否則測一次就把「今天已提醒」記下去，真的出事反而不叫
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
