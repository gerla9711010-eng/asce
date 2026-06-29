#!/usr/bin/env python3
"""
KEIS 公買搶單自動化腳本

掃「查詢公買 → 買屋需求列表」，把還能申請(status=Available)且符合條件的最新名單
自動按下「申請私買」，搶到後拿到沒遮罩的真實姓名＋電話，推一筆到 LINE。

用法:
    python grab.py --login            # 第一次：開瀏覽器手動登入一次，session 存進 profile/
    python grab.py                    # 單次 dry-run：只列出「這次會搶誰」，不真的送出
    python grab.py --apply            # 單次實搶
    python grab.py --watch            # 常駐監控(dry-run)：早上時段高頻掃，只印不搶
    python grab.py --watch --apply    # 常駐監控 + 實搶（正式用這個）
    python grab.py --watch --apply --headed   # debug：顯示瀏覽器

登入方式跟 publish.py 共用同一個 profile/ — 登入一次兩支腳本都能用。
KEIS 是 session cookie 驗證，不存帳密；session 過期會推 LINE 提醒並停下，重跑 --login。

API（從 HAR 逆出來的，無 body）:
    GET  /api/v1/call-purchase/query?inquiry_type=1&page=1&page_size=20&...
         → {"data":[{summary_id,status,display_name,target_city,property_category,
                     budget_start,budget_end,start_time,app_time,...}],
            "new_case_quota_remaining": 6, ...}
         status: "Available"=可申請 / "CoolingDown"=已被申請(7天)
    POST /api/v1/call-purchase/apply/{summary_id}
         → {"success":true,"data":{"display_name":"賴先生","phone_number":"2852068"}}

觀察到的節奏：名單每天早上批次釋出，~08:19 起全店集中搶，前 10 分鐘掃掉大半，一小時收尾。
所以 watch 模式預設只在早上時段火力全開（見 WATCH_WINDOWS）。

環境變數（.env，可選）:
    KEIS_NOTIFY_WEBHOOK   n8n webhook URL；設了才會推 LINE（payload 見 README）
"""

import argparse
import csv
import os
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

load_dotenv()

# ====== 設定：直接改這裡 ======
INQUIRY_TYPE = 1              # 1=買屋, 2=租屋
CITIES = ["高雄市"]           # 只搶這些縣市；空 list [] = 不限縣市
PROPERTY_TYPES: list[str] = []  # 物件類型(中文)白名單，例 ["透天", "大樓"]；空 = 全收
MIN_BUDGET = None            # 預算下限(萬)，None=不限。只比對有填預算的(budget_start>0)
MAX_BUDGET = None            # 預算上限(萬)，None=不限
MAX_APPLY_PER_RUN = None     # 單次執行最多搶幾筆；None = 搶到當日配額用完為止
DRY_RUN = True               # True=只列出不送出；--apply 會把它關掉

# --- watch 常駐監控模式設定（本機時間，假設 Asia/Taipei）---
WATCH_WINDOWS = [("07:50", "09:30")]  # 只在這些時段高頻掃；(開始, 結束) 24h 制，可放多段
POLL_INTERVAL_SEC = 20       # 時段內每幾秒掃一次
POLL_JITTER_SEC = 5          # 每次再隨機 ±這個秒數，別像節拍器
OFF_WINDOW_RECHECK_SEC = 600 # 時段外最久睡多久就醒來重算(睡到下個窗口，但每 10 分鐘確認一次)
# ==============================

KEIS_BASE = "https://keis.kshouse.com.tw"
KEIS_LOGIN_URL = f"{KEIS_BASE}/"
KEIS_PUBLIC_PURCHASE_URL = f"{KEIS_BASE}/public-purchase"
API = f"{KEIS_BASE}/api/v1"

PROFILE_DIR = Path(__file__).parent / "profile"   # 跟 publish.py 共用同一個登入 session
GRABBED_CSV = Path(__file__).parent / "grabbed.csv"

NOTIFY_WEBHOOK = os.environ.get("KEIS_NOTIFY_WEBHOOK", "").strip()

API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "referer": KEIS_PUBLIC_PURCHASE_URL,
    "origin": KEIS_BASE,
}


class SessionExpired(Exception):
    """KEIS 登入 session 失效"""


def build_query_url() -> str:
    year = datetime.now().year
    params = {
        "page": 1,
        "page_size": 20,
        "inquiry_type": INQUIRY_TYPE,
        "only_my_applications": "false",
        "start_date": f"{year}-01-01 00:00:00",
        "end_date": f"{year}-12-31 23:59:59",
        "target_area": "",
        "property_category": "",
    }
    return f"{API}/call-purchase/query?{urlencode(params)}"


def matches(rec: dict) -> bool:
    if rec.get("status") != "Available":
        return False
    if CITIES and rec.get("target_city") not in CITIES:
        return False
    if PROPERTY_TYPES and rec.get("property_category") not in PROPERTY_TYPES:
        return False
    budget = rec.get("budget_start") or 0
    if budget > 0:  # 0 = 未填預算，不拿來篩
        if MIN_BUDGET is not None and budget < MIN_BUDGET:
            return False
        if MAX_BUDGET is not None and budget > MAX_BUDGET:
            return False
    return True


def fmt_budget(rec: dict) -> str:
    s, e = rec.get("budget_start") or 0, rec.get("budget_end") or 0
    if not s and not e:
        return "-"
    if e and e != s:
        return f"{s:.0f}-{e:.0f}萬"
    return f"{s:.0f}萬{'以上' if not e else ''}"


def desc(r: dict) -> str:
    return (f"[{r['summary_id']}] {r['display_name']} {r['target_city']}"
            f"{''.join(r.get('target_areas') or [])} {r['property_category']} "
            f"{fmt_budget(r)}（建檔 {r['start_time'][:16]}）")


def fetch_records(req):
    """回傳 (符合條件且可申請的名單[新→舊], 今日剩餘配額)"""
    me = req.get(f"{API}/auth/me", headers=API_HEADERS)
    if not me.ok or "username" not in me.text():
        raise SessionExpired()
    resp = req.get(build_query_url(), headers=API_HEADERS)
    if not resp.ok:
        raise SystemExit(f"❌ 撈清單失敗 HTTP {resp.status}: {resp.text()[:200]}")
    body = resp.json()
    records = body.get("data", [])
    quota = body.get("new_case_quota_remaining")
    quota = quota if quota is not None else 0
    candidates = [r for r in records if matches(r)]
    candidates.sort(key=lambda r: r.get("start_time", ""), reverse=True)
    return candidates, quota


def apply_one(req, r: dict):
    """搶一筆。成功回 grabbed dict，失敗回 None。"""
    sid = r["summary_id"]
    ar = req.post(f"{API}/call-purchase/apply/{sid}", headers=API_HEADERS)
    data = ar.json() if ar.ok else {}
    if ar.ok and data.get("success"):
        d = data.get("data") or {}
        return {
            "grabbed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary_id": sid,
            "name": d.get("display_name", ""),
            "phone": d.get("phone_number", ""),
            "city": r["target_city"],
            "category": r["property_category"],
            "budget": fmt_budget(r),
            "start_time": r["start_time"][:16],
        }
    msg = (data.get("message") if isinstance(data, dict) else None) or ar.text()[:120]
    print(f"   ❌ [{sid}] 沒搶到（可能配額用完/被秒搶）：{msg}")
    return None


def append_csv(grabbed: list[dict]) -> None:
    new = not GRABBED_CSV.exists()
    with GRABBED_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["搶到時間", "summary_id", "姓名", "電話", "縣市", "類型", "預算", "建檔時間"])
        for g in grabbed:
            w.writerow([g["grabbed_at"], g["summary_id"], g["name"], g["phone"],
                        g["city"], g["category"], g["budget"], g["start_time"]])


def notify(payload: dict) -> None:
    if not NOTIFY_WEBHOOK:
        return
    try:
        httpx.post(NOTIFY_WEBHOOK, json=payload, timeout=15)
    except Exception as e:
        print(f"⚠ LINE 通知失敗: {e}")


def notify_grabbed(grabbed: list[dict], quota_left: int) -> None:
    notify({"event": "grabbed", "grabbed": grabbed, "quota_left": quota_left})
    print(f"📲 已推 {len(grabbed)} 筆到 LINE")


def run_login_flow() -> None:
    print("🔑 開 KEIS 讓你手動登入。登入完成後關掉瀏覽器，session 會自動存起來。")
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(user_data_dir=str(PROFILE_DIR), headless=False)
        page = context.new_page()
        page.goto(KEIS_LOGIN_URL)
        print("⏳ 等你登入完關掉瀏覽器...")
        page.wait_for_event("close", timeout=0)
        context.close()
    print("✅ session 存好了。之後跑 python grab.py 就會自動帶登入狀態。")


# ---------- 單次模式 ----------

def run_once(req, dry_run: bool) -> int:
    candidates, quota = fetch_records(req)
    print(f"📋 符合條件可申請 {len(candidates)} 筆，今日剩餘配額 {quota} 筆")
    if not candidates:
        print("😴 沒有符合條件且可申請的名單，這次不動作")
        return 0

    limit = quota
    if MAX_APPLY_PER_RUN is not None:
        limit = min(limit, MAX_APPLY_PER_RUN)
    targets = candidates[:limit]

    print(f"🎯 這次預計搶 {len(targets)} 筆：")
    for r in targets:
        print(f"   • {desc(r)}")

    if dry_run:
        print("\n🟡 dry-run：以上只是預覽，沒有真的送出。確認沒問題後加 --apply 才會搶。")
        return 0

    grabbed = []
    for r in targets:
        g = apply_one(req, r)
        if g:
            grabbed.append(g)
            print(f"   ✅ 搶到 [{g['summary_id']}] {g['name']} / {g['phone']}")
        else:
            break  # 配額用完/失敗就停手
    if grabbed:
        append_csv(grabbed)
        notify_grabbed(grabbed, quota - len(grabbed))
        print(f"\n✅ 這次搶到 {len(grabbed)} 筆，已記錄到 {GRABBED_CSV.name}")
    else:
        print("\n😕 這次一筆都沒搶到")
    return 0


# ---------- 常駐監控模式 ----------

def _parse_hhmm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


def in_window(now: datetime) -> bool:
    cur = now.hour * 60 + now.minute
    for start, end in WATCH_WINDOWS:
        sh, sm = _parse_hhmm(start)
        eh, em = _parse_hhmm(end)
        if sh * 60 + sm <= cur <= eh * 60 + em:
            return True
    return False


def seconds_to_next_window(now: datetime) -> int:
    """距離下一個窗口開始還有幾秒（找不到就回 OFF_WINDOW_RECHECK_SEC）"""
    best = None
    for start, _ in WATCH_WINDOWS:
        sh, sm = _parse_hhmm(start)
        for day in (0, 1):  # 今天 / 明天
            t = (now + timedelta(days=day)).replace(hour=sh, minute=sm, second=0, microsecond=0)
            if t > now:
                delta = int((t - now).total_seconds())
                best = delta if best is None else min(best, delta)
    if best is None:
        return OFF_WINDOW_RECHECK_SEC
    return min(best, OFF_WINDOW_RECHECK_SEC)


def run_watch(req, dry_run: bool) -> int:
    mode = "dry-run（只印不搶）" if dry_run else "實搶"
    print(f"👁  watch 模式啟動（{mode}），監控時段 {WATCH_WINDOWS}，每 ~{POLL_INTERVAL_SEC}s 掃一次。Ctrl+C 結束。")
    seen: set[int] = set()          # 這次跑已處理過的 id，避免重複
    quota_exhausted_day = None      # 已通知過配額用完的日期，避免重複睡醒又喊

    while True:
        now = datetime.now()
        if not in_window(now):
            sleep_s = seconds_to_next_window(now)
            print(f"💤 {now:%H:%M} 非監控時段，睡 {sleep_s}s")
            time.sleep(sleep_s)
            continue

        try:
            candidates, quota = fetch_records(req)
        except SessionExpired:
            print("❌ KEIS session 過期，停止監控。請跑 `python grab.py --login` 重登後再啟動。")
            notify({"event": "alert", "text": "⚠ KEIS 公買搶單監控停止：登入 session 過期，請重新登入並重啟。"})
            return 1

        # 配額用完：只想要新名單 → 當天收工，睡到下個窗口
        if quota <= 0:
            if quota_exhausted_day != now.date():
                print(f"🈵 {now:%H:%M} 今日配額用完，停止搶單，睡到下個監控時段")
                quota_exhausted_day = now.date()
            time.sleep(seconds_to_next_window(now))
            continue

        new_targets = [r for r in candidates if r["summary_id"] not in seen]
        if new_targets:
            print(f"🔔 {now:%H:%M:%S} 發現 {len(new_targets)} 筆新名單（剩餘配額 {quota}）")
            grabbed = []
            for r in new_targets:
                seen.add(r["summary_id"])
                if dry_run:
                    print(f"   🟡 [dry] 會搶：{desc(r)}")
                    continue
                if quota - len(grabbed) <= 0:
                    print("   🈵 配額用完，剩下的不搶了")
                    break
                g = apply_one(req, r)
                if g:
                    grabbed.append(g)
                    print(f"   ✅ 搶到 [{g['summary_id']}] {g['name']} / {g['phone']}")
            if grabbed:
                append_csv(grabbed)
                notify_grabbed(grabbed, quota - len(grabbed))

        time.sleep(POLL_INTERVAL_SEC + random.uniform(-POLL_JITTER_SEC, POLL_JITTER_SEC))


def main() -> int:
    parser = argparse.ArgumentParser(description="KEIS 公買搶單自動化")
    parser.add_argument("--login", action="store_true", help="互動登入模式（第一次跑用、或 session 過期）")
    parser.add_argument("--apply", action="store_true", help="實際送出申請（不加只 dry-run）")
    parser.add_argument("--watch", action="store_true", help="常駐監控模式（早上時段高頻掃）")
    parser.add_argument("--headed", action="store_true", help="顯示瀏覽器（debug 用）")
    args = parser.parse_args()

    if args.login:
        run_login_flow()
        return 0

    dry_run = DRY_RUN and not args.apply

    if not PROFILE_DIR.exists():
        raise SystemExit("❌ 沒有 KEIS session profile。先跑 `python grab.py --login` 登入一次")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(user_data_dir=str(PROFILE_DIR), headless=not args.headed)
        try:
            # 開頭確認一次登入身分（順便讓 session 暖起來）
            me = context.request.get(f"{API}/auth/me", headers=API_HEADERS)
            if not me.ok or "username" not in me.text():
                raise SystemExit("❌ KEIS session 過期。跑 `python grab.py --login` 重新登入")
            print(f"👤 登入身分：{me.json().get('username')}")

            if args.watch:
                return run_watch(context.request, dry_run)
            return run_once(context.request, dry_run)
        finally:
            context.close()


if __name__ == "__main__":
    sys.exit(main())
