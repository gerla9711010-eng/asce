#!/usr/bin/env python3
"""
KEIS 公買搶單自動化（輕量無瀏覽器版）

掃「查詢公買 → 買屋需求列表」，把還能申請(status=Available)且符合條件的最新名單
自動申請私買，搶到後拿到沒遮罩的真實姓名＋電話，推一筆到 LINE。

⚠️ 這個功能 KEIS「僅限門市內使用」——伺服器會擋 IP，只有門市網路能用。
   所以本腳本要跑在「店裡、連門市網路、且一直開著」的電腦上（例如公司電腦不關機）。
   啟動時會先打 check-ip 確認；不在門市網路會直接告訴你、不會空跑。

純 HTTP（httpx），不需要瀏覽器/Playwright，店裡任何常開機器都能跑。

用法:
    python grab.py                 # 單次 dry-run：列出「這次會搶誰」，不送出
    python grab.py --apply         # 單次實搶
    python grab.py --watch         # 常駐監控(dry-run)：早上時段高頻掃，只印不搶
    python grab.py --watch --apply # 常駐監控 + 實搶（正式用這個）

認證（從 HAR 逆出來）:
    POST /api/v1/auth/login?device_type=desktop  (form: username, password)
         → {"access_token":"<JWT>", "token_type":"bearer", "expires_in":28800}  # 8h
    後續帶 Authorization: Bearer <access_token>
    GET  /api/v1/call-purchase/check-ip   → {"allowed":true/false, "ip":"..."}
    GET  /api/v1/call-purchase/query?inquiry_type=1&...   → data[] + new_case_quota_remaining
    POST /api/v1/call-purchase/apply/{summary_id}         → {"success":true,"data":{display_name,phone_number}}

環境變數（.env）:
    KEIS_USERNAME         KEIS 帳號（必填）
    KEIS_PASSWORD         KEIS 密碼（必填）
    KEIS_NOTIFY_WEBHOOK   n8n webhook URL；設了才會推 LINE（payload 見 README）
"""

import argparse
import csv
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

load_dotenv()

# ====== 設定：直接改這裡 ======
INQUIRY_TYPE = 1              # 1=買屋, 2=租屋
CITIES = ["高雄市"]           # 只搶這些縣市；空 list [] = 不限縣市
PROPERTY_TYPES: list[str] = []  # 物件類型(中文)白名單，例 ["透天", "大樓"]；空 = 全收
MIN_BUDGET = None            # 預算下限(萬)，None=不限。只比對有填預算的(budget_start>0)
MAX_BUDGET = None            # 預算上限(萬)，None=不限
MAX_APPLY_PER_RUN = None     # 單次執行最多搶幾筆；None = 搶到當日配額用完為止
DRY_RUN = True               # True=只列出不送出；--apply 會把它關掉

# --- watch 常駐監控模式設定（本機時間，店裡電腦請設成 Asia/Taipei）---
WATCH_WINDOWS = [("07:50", "09:30")]  # 只在這些時段高頻掃；(開始, 結束) 24h 制，可放多段
POLL_INTERVAL_SEC = 20       # 時段內每幾秒掃一次
POLL_JITTER_SEC = 5          # 每次再隨機 ±這個秒數，別像節拍器
OFF_WINDOW_RECHECK_SEC = 600 # 時段外最久睡多久就醒來重算
# ==============================

KEIS_BASE = "https://keis.kshouse.com.tw"
API = f"{KEIS_BASE}/api/v1"

USERNAME = os.environ.get("KEIS_USERNAME", "")
PASSWORD = os.environ.get("KEIS_PASSWORD", "")
NOTIFY_WEBHOOK = os.environ.get("KEIS_NOTIFY_WEBHOOK", "").strip()

GRABBED_CSV = Path(__file__).parent / "grabbed.csv"


class IPBlocked(Exception):
    """不在門市網路，被 IP 鎖擋下"""


class Keis:
    """KEIS API client：自動登入 + 帶 bearer token，token 過期自動重登"""

    def __init__(self):
        self.c = httpx.Client(
            timeout=20,
            headers={
                "accept": "application/json, text/plain, */*",
                "origin": KEIS_BASE,
                "referer": f"{KEIS_BASE}/public-purchase",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) keis-grab",
            },
        )
        self._token = None
        self._exp = 0.0

    def _login(self):
        if not USERNAME or not PASSWORD:
            raise SystemExit("❌ 沒設 KEIS_USERNAME / KEIS_PASSWORD（填在 .env）")
        r = self.c.post(
            f"{API}/auth/login",
            params={"device_type": "desktop"},
            data={"username": USERNAME, "password": PASSWORD},
            headers={"content-type": "application/x-www-form-urlencoded",
                     "referer": f"{KEIS_BASE}/login"},
        )
        if r.status_code != 200:
            raise SystemExit(f"❌ 登入失敗 HTTP {r.status_code}: {r.text[:200]}")
        j = r.json()
        self._token = j["access_token"]
        self._exp = time.time() + j.get("expires_in", 28800)

    def _auth(self) -> dict:
        if not self._token or time.time() > self._exp - 60:
            self._login()
        return {"authorization": f"Bearer {self._token}"}

    def _get(self, path: str):
        r = self.c.get(f"{API}{path}", headers=self._auth())
        if r.status_code == 401:           # token 失效 → 重登重試一次
            self._login()
            r = self.c.get(f"{API}{path}", headers=self._auth())
        if r.status_code == 403:
            raise IPBlocked()
        r.raise_for_status()
        return r.json()

    def check_ip(self) -> dict:
        return self._get("/call-purchase/check-ip")

    def query(self) -> dict:
        year = datetime.now().year
        params = {
            "page": 1, "page_size": 20, "inquiry_type": INQUIRY_TYPE,
            "only_my_applications": "false",
            "start_date": f"{year}-01-01 00:00:00", "end_date": f"{year}-12-31 23:59:59",
            "target_area": "", "property_category": "",
        }
        return self._get(f"/call-purchase/query?{urlencode(params)}")

    def apply(self, summary_id: int) -> dict:
        r = self.c.post(f"{API}/call-purchase/apply/{summary_id}", headers=self._auth())
        if r.status_code == 403:
            raise IPBlocked()
        return r.json() if r.headers.get("content-type", "").startswith("application/json") else {}


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


def pick_candidates(body: dict):
    records = body.get("data", [])
    quota = body.get("new_case_quota_remaining")
    quota = quota if quota is not None else 0
    cands = [r for r in records if matches(r)]
    cands.sort(key=lambda r: r.get("start_time", ""), reverse=True)
    return cands, quota


def grab_record(keis: Keis, r: dict):
    data = keis.apply(r["summary_id"])
    if data.get("success"):
        d = data.get("data") or {}
        return {
            "grabbed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "summary_id": r["summary_id"],
            "name": d.get("display_name", ""),
            "phone": d.get("phone_number", ""),
            "city": r["target_city"],
            "category": r["property_category"],
            "budget": fmt_budget(r),
            "start_time": r["start_time"][:16],
        }
    print(f"   ❌ [{r['summary_id']}] 沒搶到（可能配額用完/被秒搶）：{data.get('message')}")
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


def ensure_in_store_network(keis: Keis) -> bool:
    """確認跑這支的機器在門市網路（IP 被允許）"""
    info = keis.check_ip()
    if info.get("allowed"):
        print(f"✅ IP {info.get('ip')} 在門市網路，可用")
        return True
    msg = f"⛔ 這台機器 IP {info.get('ip')} 不在門市網路，KEIS 公買功能被擋。請把腳本放到店裡、連門市網路的電腦上跑。"
    print(msg)
    notify({"event": "alert", "text": "⚠ KEIS 搶單：" + msg})
    return False


# ---------- 單次模式 ----------

def run_once(keis: Keis, dry_run: bool) -> int:
    if not ensure_in_store_network(keis):
        return 1
    cands, quota = pick_candidates(keis.query())
    print(f"📋 符合條件可申請 {len(cands)} 筆，今日剩餘配額 {quota} 筆")
    if not cands:
        print("😴 沒有符合條件且可申請的名單，這次不動作")
        return 0

    limit = quota
    if MAX_APPLY_PER_RUN is not None:
        limit = min(limit, MAX_APPLY_PER_RUN)
    targets = cands[:limit]

    print(f"🎯 這次預計搶 {len(targets)} 筆：")
    for r in targets:
        print(f"   • {desc(r)}")

    if dry_run:
        print("\n🟡 dry-run：以上只是預覽，沒有真的送出。確認沒問題後加 --apply 才會搶。")
        return 0

    grabbed = []
    for r in targets:
        g = grab_record(keis, r)
        if g:
            grabbed.append(g)
            print(f"   ✅ 搶到 [{g['summary_id']}] {g['name']} / {g['phone']}")
        else:
            break
    if grabbed:
        append_csv(grabbed)
        notify_grabbed(grabbed, quota - len(grabbed))
        print(f"\n✅ 這次搶到 {len(grabbed)} 筆，已記錄到 {GRABBED_CSV.name}")
    else:
        print("\n😕 這次一筆都沒搶到")
    return 0


# ---------- 常駐監控模式 ----------

def _parse_hhmm(s: str):
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
    cur = now.hour * 60 + now.minute
    best = None
    for start, _ in WATCH_WINDOWS:
        sh, sm = _parse_hhmm(start)
        start_min = sh * 60 + sm
        delta = (start_min - cur) % (24 * 60)
        delta = delta or 24 * 60
        best = delta if best is None else min(best, delta)
    return min((best or 1) * 60, OFF_WINDOW_RECHECK_SEC)


def run_watch(keis: Keis, dry_run: bool) -> int:
    mode = "dry-run（只印不搶）" if dry_run else "實搶"
    print(f"👁  watch 模式啟動（{mode}），監控時段 {WATCH_WINDOWS}，每 ~{POLL_INTERVAL_SEC}s 掃一次。Ctrl+C 結束。")
    if not ensure_in_store_network(keis):
        return 1

    seen: set[int] = set()
    seen_day = None
    quota_done_day = None

    while True:
        now = datetime.now()
        if seen_day != now.date():       # 跨日重置
            seen.clear()
            seen_day = now.date()

        if not in_window(now):
            sleep_s = seconds_to_next_window(now)
            print(f"💤 {now:%H:%M} 非監控時段，睡 {sleep_s}s")
            time.sleep(sleep_s)
            continue

        try:
            cands, quota = pick_candidates(keis.query())
        except IPBlocked:
            notify({"event": "alert", "text": "⚠ KEIS 搶單停止：IP 被擋（離開門市網路了？）"})
            print("⛔ IP 被擋，停止監控")
            return 1

        if quota <= 0:
            if quota_done_day != now.date():
                print(f"🈵 {now:%H:%M} 今日配額用完，睡到下個監控時段")
                quota_done_day = now.date()
            time.sleep(seconds_to_next_window(now))
            continue

        fresh = [r for r in cands if r["summary_id"] not in seen]
        if fresh:
            print(f"🔔 {now:%H:%M:%S} 發現 {len(fresh)} 筆新名單（剩餘配額 {quota}）")
            grabbed = []
            for r in fresh:
                seen.add(r["summary_id"])
                if dry_run:
                    print(f"   🟡 [dry] 會搶：{desc(r)}")
                    continue
                if quota - len(grabbed) <= 0:
                    print("   🈵 配額用完，剩下的不搶了")
                    break
                try:
                    g = grab_record(keis, r)
                except IPBlocked:
                    notify({"event": "alert", "text": "⚠ KEIS 搶單停止：IP 被擋"})
                    return 1
                if g:
                    grabbed.append(g)
                    print(f"   ✅ 搶到 [{g['summary_id']}] {g['name']} / {g['phone']}")
            if grabbed:
                append_csv(grabbed)
                notify_grabbed(grabbed, quota - len(grabbed))

        time.sleep(POLL_INTERVAL_SEC + random.uniform(-POLL_JITTER_SEC, POLL_JITTER_SEC))


def main() -> int:
    parser = argparse.ArgumentParser(description="KEIS 公買搶單（無瀏覽器版）")
    parser.add_argument("--apply", action="store_true", help="實際送出申請（不加只 dry-run）")
    parser.add_argument("--watch", action="store_true", help="常駐監控模式（早上時段高頻掃）")
    args = parser.parse_args()

    dry_run = DRY_RUN and not args.apply
    keis = Keis()
    print(f"👤 登入 KEIS：{USERNAME}")
    if args.watch:
        return run_watch(keis, dry_run)
    return run_once(keis, dry_run)


if __name__ == "__main__":
    sys.exit(main())
