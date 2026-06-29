#!/usr/bin/env python3
"""
KEIS 公買搶單自動化腳本

掃「查詢公買 → 買屋需求列表」，把還能申請(status=Available)且符合條件的最新名單
自動按下「申請私買」，搶到後拿到沒遮罩的真實姓名＋電話，推一筆到 LINE。

用法:
    python grab.py --login          # 第一次：開瀏覽器手動登入一次，session 存進 profile/
    python grab.py                  # dry-run：只列出「這次會搶誰」，不真的送出
    python grab.py --apply          # 實際送出申請（搶單）
    python grab.py --apply --headed # 同上但顯示瀏覽器（debug 用）

登入方式跟 publish.py 共用同一個 profile/ — 登入一次兩支腳本都能用。
KEIS 是 session cookie 驗證，不存帳密；session 過期會提示重跑 --login。

API（從 HAR 逆出來的，無 body）:
    GET  /api/v1/call-purchase/query?inquiry_type=1&page=1&page_size=20&...
         → {"data":[{summary_id,status,display_name,target_city,property_category,
                     budget_start,budget_end,start_time,...}],
            "new_case_quota_remaining": 6, ...}
         status: "Available"=可申請 / "CoolingDown"=已被申請(7天)
    POST /api/v1/call-purchase/apply/{summary_id}
         → {"success":true,"data":{"display_name":"賴先生","phone_number":"2852068"}}

環境變數（.env，可選）:
    KEIS_NOTIFY_WEBHOOK   n8n webhook URL；設了才會推 LINE（payload 見 README）
"""

import argparse
import csv
import os
import sys
from datetime import datetime
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
MAX_APPLY_PER_RUN = None     # 每次執行最多搶幾筆；None = 搶到當日配額用完為止
DRY_RUN = True               # True=只列出不送出；--apply 會把它關掉
# ==============================

KEIS_BASE = "https://keis.kshouse.com.tw"
KEIS_LOGIN_URL = f"{KEIS_BASE}/"
KEIS_PUBLIC_PURCHASE_URL = f"{KEIS_BASE}/public-purchase"
API = f"{KEIS_BASE}/api/v1"

PROFILE_DIR = Path(__file__).parent / "profile"   # 跟 publish.py 共用同一個登入 session
GRABBED_CSV = Path(__file__).parent / "grabbed.csv"

NOTIFY_WEBHOOK = os.environ.get("KEIS_NOTIFY_WEBHOOK", "").strip()

# API 需要的同源標頭
API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "referer": KEIS_PUBLIC_PURCHASE_URL,
    "origin": KEIS_BASE,
}


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
    """這筆符不符合搶單條件"""
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


def notify_line(grabbed: list[dict], quota_left) -> None:
    if not NOTIFY_WEBHOOK:
        return
    try:
        httpx.post(NOTIFY_WEBHOOK, json={"grabbed": grabbed, "quota_left": quota_left}, timeout=15)
        print(f"📲 已推 {len(grabbed)} 筆到 LINE webhook")
    except Exception as e:  # 通知失敗不該讓搶單流程整個 fail
        print(f"⚠ LINE 通知失敗（搶單已完成，名單見 {GRABBED_CSV.name}）: {e}")


def append_csv(grabbed: list[dict]) -> None:
    new = not GRABBED_CSV.exists()
    with GRABBED_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["搶到時間", "summary_id", "姓名", "電話", "縣市", "類型", "預算", "建檔時間"])
        for g in grabbed:
            w.writerow([g["grabbed_at"], g["summary_id"], g["name"], g["phone"],
                        g["city"], g["category"], g["budget"], g["start_time"]])


def main() -> int:
    parser = argparse.ArgumentParser(description="KEIS 公買搶單自動化")
    parser.add_argument("--login", action="store_true", help="互動登入模式（第一次跑用、或 session 過期）")
    parser.add_argument("--apply", action="store_true", help="實際送出申請（不加這個只 dry-run 列出）")
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
        req = context.request
        try:
            # 1) 確認登入狀態
            me = req.get(f"{API}/auth/me", headers=API_HEADERS)
            if not me.ok or "username" not in me.text():
                raise SystemExit("❌ KEIS session 過期。跑 `python grab.py --login` 重新登入")
            print(f"👤 登入身分：{me.json().get('username')}")

            # 2) 撈買屋清單
            resp = req.get(build_query_url(), headers=API_HEADERS)
            if not resp.ok:
                raise SystemExit(f"❌ 撈清單失敗 HTTP {resp.status}: {resp.text()[:200]}")
            body = resp.json()
            records = body.get("data", [])
            quota = body.get("new_case_quota_remaining")
            quota = quota if quota is not None else 0
            print(f"📋 撈到 {len(records)} 筆，今日剩餘配額 {quota} 筆")

            # 3) 篩選 + 由新到舊排序
            candidates = [r for r in records if matches(r)]
            candidates.sort(key=lambda r: r.get("start_time", ""), reverse=True)

            # 4) 算這次要搶幾筆（受配額 + 每次上限夾擊）
            limit = quota
            if MAX_APPLY_PER_RUN is not None:
                limit = min(limit, MAX_APPLY_PER_RUN)
            targets = candidates[:limit]

            if not candidates:
                print("😴 沒有符合條件且可申請的名單，這次不動作")
                return 0

            print(f"🎯 符合條件可申請 {len(candidates)} 筆，這次預計搶 {len(targets)} 筆：")
            for r in targets:
                print(f"   • [{r['summary_id']}] {r['display_name']} {r['target_city']}"
                      f"{''.join(r.get('target_areas') or [])} {r['property_category']} "
                      f"{fmt_budget(r)} （建檔 {r['start_time'][:16]}）")

            if dry_run:
                print("\n🟡 dry-run：以上只是預覽，沒有真的送出。確認沒問題後加 --apply 才會搶。")
                return 0

            # 5) 實際搶單
            grabbed = []
            for r in targets:
                sid = r["summary_id"]
                ar = req.post(f"{API}/call-purchase/apply/{sid}", headers=API_HEADERS)
                data = ar.json() if ar.ok else {}
                if ar.ok and data.get("success"):
                    d = data.get("data") or {}
                    grabbed.append({
                        "grabbed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "summary_id": sid,
                        "name": d.get("display_name", ""),
                        "phone": d.get("phone_number", ""),
                        "city": r["target_city"],
                        "category": r["property_category"],
                        "budget": fmt_budget(r),
                        "start_time": r["start_time"][:16],
                    })
                    print(f"   ✅ 搶到 [{sid}] {d.get('display_name')} / {d.get('phone_number')}")
                else:
                    msg = (data.get("message") if isinstance(data, dict) else None) or ar.text()[:120]
                    print(f"   ❌ [{sid}] 沒搶到（可能配額用完/被秒搶）：{msg}")
                    break  # 配額用完就沒必要再打，停手

            if grabbed:
                append_csv(grabbed)
                notify_line(grabbed, quota - len(grabbed))
                print(f"\n✅ 這次搶到 {len(grabbed)} 筆，已記錄到 {GRABBED_CSV.name}")
            else:
                print("\n😕 這次一筆都沒搶到")
            return 0
        finally:
            context.close()


if __name__ == "__main__":
    sys.exit(main())
