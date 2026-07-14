#!/usr/bin/env python3
"""
KEIS 公買搶單自動化（輕量無瀏覽器版）

掃「查詢公買 → 買屋需求列表」，把還能申請(status=Available)且符合條件的最新名單
自動申請私買，搶到後拿到沒遮罩的真實姓名＋電話，推一筆到 LINE。

⚠️ 這個功能 KEIS「僅限門市內使用」——伺服器會擋 IP，只有門市網路能用。
   所以本腳本要跑在「店裡、連門市網路、且一直開著」的電腦上（例如公司電腦不關機）。

無人看管長期跑：watch 模式會一直循環，時段外閒置、時段內高頻掃；遇到暫時性錯誤
（斷網、逾時）不會死，會自己重試。搭配 run.bat 開機自動啟動 + 掛掉自動重開。

用法:
    python grab.py                 # 單次 dry-run：列出「這次會搶誰」，不送出
    python grab.py --apply         # 單次實搶
    python grab.py --watch         # 常駐監控(dry-run)：早上時段高頻掃，只印不搶
    python grab.py --watch --apply # 常駐監控 + 實搶（正式；開機自動跑就是這個）

環境變數（.env）:
    KEIS_USERNAME         KEIS 主帳號（必填）
    KEIS_PASSWORD         主帳號密碼（必填）
    KEIS_USERNAME2/3…     副帳號（可選）；每多一個帳號 = 多 7 筆配額，會自動分工不撞單
    KEIS_PASSWORD2/3…     對應副帳號密碼
    KEIS_NOTIFY_WEBHOOK   n8n webhook URL；設了才會推 LINE（可選）
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

# 避免在 Windows cmd（cp950）印 emoji 時整個當掉
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

# ====== 設定：直接改這裡 ======
INQUIRY_TYPE = 1              # 1=買屋, 2=租屋
CITIES = ["高雄市"]           # 只搶這些縣市；空 list [] = 不限縣市
PROPERTY_TYPES: list[str] = []  # 物件類型(中文)白名單，例 ["透天", "大樓"]；空 = 全收
MIN_BUDGET = None            # 預算下限(萬)，None=不限。只比對有填預算的(budget_start>0)
MAX_BUDGET = None            # 預算上限(萬)，None=不限
MAX_APPLY_PER_RUN = None     # 單次執行最多搶幾筆；None = 搶到當日配額用完為止
DRY_RUN = True               # True=只列出不送出；--apply 會把它關掉

# --- watch 常駐監控模式設定（本機時間，店裡電腦請設成 Asia/Taipei）---
WATCH_WINDOWS = [("06:00", "09:30")]  # 只在這些時段高頻掃；(開始, 結束) 24h 制，可放多段。起點拉到06:00：讓上架偵測基準在釋出前就建好，量得到真實釋出時刻，也不錯過早於07:30的釋出（純觀測不吃配額）
POLL_INTERVAL_SEC = 5       # 時段內每幾秒掃一次
POLL_JITTER_SEC = 3          # 每次再隨機 ±這個秒數，別像節拍器（越大越不規律）
OFF_WINDOW_RECHECK_SEC = 600 # 時段外最久睡多久就醒來重算
OBSERVE_INTERVAL_SEC = 30    # 配額用完後改「純觀測上架時間」，每幾秒掃一次（不搶、不吃配額）

# --- 低調 / 抗尖峰設定 ---
HTTP_TIMEOUT_SEC = 30        # 單次請求逾時；開盤塞車時多等一下再放棄
ERROR_RETRY_MIN = 3          # 時段內遇暫時性錯誤(逾時等)後，最短幾秒重試
ERROR_RETRY_MAX = 8          # ...最長幾秒（隨機取，別死等 30s 錯過開盤）
# 註：抓到多筆時是「一次全搶」(秒搶)，中間不留間隔——刻意保留最高搶單成功率
# ==============================

KEIS_BASE = "https://keis.kshouse.com.tw"
API = f"{KEIS_BASE}/api/v1"

NOTIFY_WEBHOOK = os.environ.get("KEIS_NOTIFY_WEBHOOK", "").strip()

# Notion 同步（可選）：設了 token + 資料庫 id 才會把搶到的名單寫進 Notion
# token 可沿用其他工具的 NOTION_TOKEN（同一把 integration 分享這個資料庫即可）
NOTION_TOKEN = (os.environ.get("KEIS_NOTION_TOKEN") or os.environ.get("NOTION_TOKEN", "")).strip()
NOTION_DB_ID = os.environ.get("KEIS_NOTION_DB_ID", "").strip()


def load_accounts() -> list[tuple]:
    """從 .env 讀多帳號。每個帳號有自己的 7 配額，會分工搶不同名單。
    支援 KEIS_USERNAME/PASSWORD（主帳號）+ KEIS_USERNAME2/PASSWORD2、3…（副帳號）。"""
    accts = []
    u, p = os.environ.get("KEIS_USERNAME", ""), os.environ.get("KEIS_PASSWORD", "")
    if u and p:
        accts.append((u, p))
    i = 2
    while True:
        u, p = os.environ.get(f"KEIS_USERNAME{i}", ""), os.environ.get(f"KEIS_PASSWORD{i}", "")
        if not (u and p):
            break
        accts.append((u, p))
        i += 1
    return accts

GRABBED_CSV = Path(__file__).parent / "grabbed.csv"
LOG_FILE = Path(__file__).parent / "watch.log"
APPEAR_CSV = Path(__file__).parent / "appearances.csv"   # 上架偵測：新名單第一次出現的時刻
APPEAR_STATE = Path(__file__).parent / "appear_state.txt"  # 記住今天觀測基準（撐過重啟）


def log(msg: str) -> None:
    """印出來 + 存進 watch.log（無人看管時才查得到發生什麼事）"""
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8-sig") as f:
            f.write(line + "\n")
    except Exception:
        pass


class IPBlocked(Exception):
    """不在門市網路，被 IP 鎖擋下"""


class Keis:
    """KEIS API client：自動登入 + 帶 bearer token，token 過期自動重登。
    每個實例綁一個帳號（多帳號各自一份 client / token / 配額）。"""

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.label = username           # grabbed.csv / LINE 用來標「誰搶的」
        self.c = httpx.Client(
            timeout=HTTP_TIMEOUT_SEC,
            headers={
                "accept": "application/json, text/plain, */*",
                "accept-language": "zh-TW,zh;q=0.9",
                "origin": KEIS_BASE,
                "referer": f"{KEIS_BASE}/public-purchase",
                # 一般 Chrome UA，別在存取紀錄裡自曝是腳本
                "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/126.0.0.0 Safari/537.36"),
            },
        )
        self._token = None
        self._exp = 0.0

    def _login(self):
        r = self.c.post(
            f"{API}/auth/login",
            params={"device_type": "desktop"},
            data={"username": self.username, "password": self.password},
            headers={"content-type": "application/x-www-form-urlencoded",
                     "referer": f"{KEIS_BASE}/login"},
        )
        if r.status_code != 200:
            raise RuntimeError(f"[{self.label}] 登入失敗 HTTP {r.status_code}: {r.text[:200]}")
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

    def my_applications(self) -> list:
        """查這個帳號『我的申請』清單（含未遮罩姓名/電話）。給收盤回查對帳用。
        是滾動 7 天窗口——只看得到最近申請的，所以回查要每個時段跑、別事後才補。"""
        year = datetime.now().year
        params = {
            "page": 1, "page_size": 100, "inquiry_type": INQUIRY_TYPE,
            "only_my_applications": "true",
            "start_date": f"{year}-01-01 00:00:00", "end_date": f"{year}-12-31 23:59:59",
            "target_area": "", "property_category": "",
        }
        return self._get(f"/call-purchase/query?{urlencode(params)}").get("data", [])


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


def norm_phone(p: str) -> str:
    """市話補上高雄區碼 07。手機(09…)、已含區碼(0 開頭，如 07/08)、空值都不動。
    依使用者慣例：07 直接接本地號碼、不加橫線，例：7924059 → 077924059。"""
    p = (p or "").strip().replace("-", "").replace(" ", "")
    if not p:
        return p
    if p.startswith("09"):                    # 手機
        return p
    if len(p) == 9 and p.startswith("9"):     # 手機掉了開頭的 0（0912… 被存成 912…）
        return "0" + p
    if p.startswith("0"):                      # 已含區碼（07/08/02…）
        return p
    return "07" + p                            # 其餘視為高雄本地市話 → 補 07


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
            "account": keis.label,          # 哪個帳號搶的
            "summary_id": r["summary_id"],
            "name": d.get("display_name", ""),
            "phone": norm_phone(d.get("phone_number", "")),
            "city": r["target_city"],
            "category": r["property_category"],
            "budget": fmt_budget(r),
            "start_time": r["start_time"][:16],
        }
    log(f"   ❌ [{keis.label}] [{r['summary_id']}] 沒搶到（可能配額用完/被秒搶）：{data.get('message')}")
    return None


def append_csv(grabbed: list[dict]) -> None:
    new = not GRABBED_CSV.exists()
    with GRABBED_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["搶到時間", "帳號", "summary_id", "姓名", "電話", "縣市", "類型", "預算", "建檔時間"])
        for g in grabbed:
            w.writerow([g["grabbed_at"], g.get("account", ""), g["summary_id"], g["name"], g["phone"],
                        g["city"], g["category"], g["budget"], g["start_time"]])


# ---------- 上架偵測（唯讀觀測，不搶不吃配額）----------
# 邏輯：每天以「當下池子最大 summary_id」為基準，之後只要冒出更大號的名單，
# 就是後台剛推上架的新貨 → 記錄它第一次被我們看到的時刻。跑幾天就能看出後台放單規律。

def _load_appear_state():
    try:
        d, m = APPEAR_STATE.read_text(encoding="utf-8").strip().split(",")
        return d, int(m)
    except Exception:
        return None, 0


def _save_appear_state(day: str, max_id: int) -> None:
    try:
        APPEAR_STATE.write_text(f"{day},{max_id}", encoding="utf-8")
    except Exception:
        pass


def _append_appearance(rows: list[dict]) -> None:
    new = not APPEAR_CSV.exists()
    with APPEAR_CSV.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["首次出現時間", "summary_id", "建檔時間", "縣市", "區域", "類型", "狀態"])
        for r in rows:
            w.writerow([r["seen"], r["id"], r["start"], r["city"], r["area"], r["cat"], r["status"]])


def observe_appearances(records: list, ap_day, ap_max):
    """回傳更新後的 (ap_day, ap_max)。新的一天先建基準不記錄；之後記錄冒出的新單號。"""
    today = datetime.now().date().isoformat()
    ids = [r.get("summary_id", 0) for r in records if r.get("summary_id") is not None]
    if not ids:
        return ap_day, ap_max
    cur_max = max(ids)
    if ap_day != today:                       # 跨日/首次：以現有池子當基準，不記錄
        log(f"🔭 上架觀測基準建立（{today}）：目前最大單號 {cur_max}")
        _save_appear_state(today, cur_max)
        return today, cur_max
    new = [r for r in records if (r.get("summary_id") or 0) > ap_max]
    if new:
        rows = []
        for r in sorted(new, key=lambda x: x.get("summary_id", 0)):
            seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows.append({"seen": seen, "id": r.get("summary_id"),
                         "start": r.get("start_time"),
                         "city": r.get("target_city") or "",
                         "area": "".join(r.get("target_areas") or []),
                         "cat": r.get("property_category") or "",
                         "status": r.get("status")})
            log(f"🆕 上架偵測 id{r.get('summary_id')} 首次出現"
                f"（建檔 {str(r.get('start_time'))[:16]}）"
                f"{r.get('target_city') or ''}{r.get('property_category') or ''}")
        _append_appearance(rows)
        ap_max = max(ap_max, cur_max)
        _save_appear_state(today, ap_max)
    return today, ap_max


def notify(payload: dict) -> None:
    if not NOTIFY_WEBHOOK:
        return
    try:
        httpx.post(NOTIFY_WEBHOOK, json=payload, timeout=15)
    except Exception as e:
        print(f"⚠ LINE 通知失敗: {e}")


def notify_grabbed(grabbed: list[dict], quota_left: int,
                   new_today: int | None = None, grabbed_today: int | None = None) -> None:
    payload = {"event": "grabbed", "grabbed": grabbed, "quota_left": quota_left}
    if new_today is not None:                # 開盤搶單才帶今日累計；補漏回查不帶（退回本批數）
        payload["new_today"] = new_today
        payload["grabbed_today"] = grabbed_today
    notify(payload)
    extra = f"（今日新名單 {new_today}／搶到 {grabbed_today}）" if new_today is not None else ""
    log(f"📲 已推 {len(grabbed)} 筆到 LINE{extra}")


def notify_daily_summary(new_today: int, grabbed_today: int, recovered: int = 0) -> None:
    """收盤保底通知：不管有沒有搶到，時段結束都推一則今日戰果，讓手機一眼看出
    「今天沒貨」vs「系統掛了」vs「搶輸」。這是掛 0 保底——0 搶到那天也一定有訊息。"""
    notify({"event": "daily_summary", "new_today": new_today,
            "grabbed_today": grabbed_today, "recovered": recovered,
            "date": datetime.now().strftime("%Y-%m-%d")})
    log(f"📲 已推收盤戰果到 LINE（今日新名單 {new_today}／搶到 {grabbed_today}"
        f"{f'／補回 {recovered}' if recovered else ''}）")


def _notion_dt(s: str) -> str:
    """把 grab.py 的時間字串轉成 Notion 吃的 ISO（補台灣時區）。
    "2026-07-10 08:00:02" → "2026-07-10T08:00:02+08:00"；已含 T 的建檔時間也一併補時區。"""
    s = (s or "").strip().replace(" ", "T")
    return s + "+08:00" if s and "+" not in s else s


def push_notion(g: dict) -> None:
    """把搶到的一筆寫進 Notion 資料庫（沒設 token 就跳過；失敗只記 log，絕不影響搶單）。"""
    if not (NOTION_TOKEN and NOTION_DB_ID):
        return
    props = {
        "姓名": {"title": [{"text": {"content": g["name"] or "(未提供)"}}]},
        "summary_id": {"rich_text": [{"text": {"content": str(g["summary_id"])}}]},
        "預算": {"rich_text": [{"text": {"content": g["budget"] or "-"}}]},
        "縣市": {"select": {"name": g["city"] or "-"}},
        "類型": {"select": {"name": g["category"] or "-"}},
        "搶到時間": {"date": {"start": _notion_dt(g["grabbed_at"])}},
        "建檔時間": {"date": {"start": _notion_dt(g["start_time"])}},
        "聯絡狀態": {"select": {"name": "未聯絡"}},
    }
    if g.get("phone"):
        props["電話"] = {"phone_number": g["phone"]}
    if g.get("account"):
        props["帳號"] = {"select": {"name": g["account"]}}
    try:
        r = httpx.post(
            "https://api.notion.com/v1/pages",
            headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                     "Notion-Version": "2022-06-28",
                     "Content-Type": "application/json"},
            json={"parent": {"database_id": NOTION_DB_ID}, "properties": props},
            timeout=15,
        )
        if r.status_code >= 300:
            log(f"   ⚠ Notion 寫入失敗 HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        log(f"   ⚠ Notion 寫入例外（不影響搶單）：{type(e).__name__}")


def load_recorded_sids() -> set:
    """讀 grabbed.csv 現有的 summary_id（字串），給回查對帳判斷哪些已落地。"""
    sids: set = set()
    if not GRABBED_CSV.exists():
        return sids
    try:
        with GRABBED_CSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("搶到時間"):
                    continue
                sid = row[2] if len(row) >= 9 else (row[1] if len(row) >= 2 else "")
                if sid:
                    sids.add(str(sid).strip())
    except Exception as e:
        log(f"⚠ 讀 grabbed.csv 失敗（回查略過）：{type(e).__name__}")
    return sids


def record_from_application(app: dict, label: str) -> dict:
    """用『我的申請』回傳的未遮罩資料組出一筆搶到紀錄（欄位同 grab_record）。
    搶到時間優先用伺服器的 app_time（較準），拿不到才用現在時間。"""
    t = str(app.get("app_time") or "").replace("T", " ").strip()
    grabbed_at = t[:19] if (len(t) >= 16 and t[:4].isdigit() and "-" in t[:10]) \
        else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
        "grabbed_at": grabbed_at,
        "account": label,
        "summary_id": app.get("summary_id"),
        "name": app.get("display_name", ""),
        "phone": norm_phone(app.get("phone_number", "")),
        "city": app.get("target_city", ""),
        "category": app.get("property_category", ""),
        "budget": fmt_budget(app),
        "start_time": str(app.get("start_time", ""))[:16],
    }


def reconcile_applications(clients: list, dry_run: bool) -> list:
    """回查各帳號『我的申請』，補回有申請成功卻沒落地的漏記名單（如開盤回應逾時的幽靈搶單）。
    只增不減、以 summary_id 去重；回傳這次補回的清單。全程 best-effort，出錯只記 log 不影響搶單。
    在『不搶單的閒時』跑（啟動時、每個時段收盤時），所以不會拖慢搶單。"""
    if dry_run:
        return []
    recorded = load_recorded_sids()
    recovered: list[dict] = []
    for cl in clients:
        try:
            apps = cl.my_applications()
        except Exception as e:
            log(f"   ⚠ [{cl.label}] 回查申請失敗，略過：{type(e).__name__}")
            continue
        for app in apps:
            sid = app.get("summary_id")
            if sid is None or str(sid) in recorded:
                continue                       # 已落地過 → 跳過（不會重複補）
            rec = record_from_application(app, cl.label)
            try:
                append_csv([rec])
                push_notion(rec)
            except Exception as e:
                log(f"   ⚠ 補回寫入失敗 {sid}：{type(e).__name__}")
                continue
            recorded.add(str(sid))
            recovered.append(rec)
            log(f"   ↩ [{cl.label}] 補回漏記名單 {rec['name']} / {rec['phone']}｜{sid} {rec['city']} {rec['category']}")
    return recovered


def grab_across_accounts(clients: list, fresh: list, dry_run: bool,
                         seen: set | None = None, persist: bool = False):
    """把 fresh 名單依各帳號剩餘配額「分工」搶，不同帳號拿不同名單、不撞單。
    回傳 (grabbed, done_labels, quota_left)：done_labels=本輪確認配額已用完的帳號。

    抗開盤壅塞（重要）：每搶到一筆就「立刻」寫 CSV + 標記 seen（persist / seen 有給時）。
    這樣就算搶到一半伺服器逾時，已搶到的不會弄丟；而還沒搶成的不會被標 seen，
    下一輪 watch 會自動回頭補搶——不像舊版一逾時就整批放棄、白白浪費剩餘配額。"""
    grabbed: list[dict] = []
    done: set = set()
    quota_left = 0
    idx = 0
    for cl in clients:
        if idx >= len(fresh):
            quota_left += 7  # 這帳號還沒被叫到、配額大概還在（僅供 LINE 顯示概估）
            continue
        try:
            _, q = pick_candidates(cl.query())   # 讀該帳號自己的剩餘配額
        except Exception as e:
            log(f"   ⚠ [{cl.label}] 查配額失敗，本輪跳過：{type(e).__name__}")
            continue
        if q <= 0:
            done.add(cl.label)
            continue
        take = fresh[idx: idx + q]
        idx += len(take)
        succ = 0
        for r in take:
            if dry_run:
                log(f"   🟡 [dry][{cl.label}] 會搶：{desc(r)}")
                continue
            try:
                g = grab_record(cl, r)
            except Exception as e:
                # 逾時等暫時性錯誤：這筆沒搶成、不標 seen，收工本批交給下一輪補搶
                log(f"   ⚠ [{cl.label}] 搶單中斷（剩下的下一輪自動補搶）：{type(e).__name__}")
                return grabbed, done, quota_left
            if g:
                grabbed.append(g)
                succ += 1
                if persist:
                    append_csv([g])            # 逐筆落地，別等整批（逾時也不弄丟）
                    push_notion(g)             # 同步寫進 Notion（沒設 token 就跳過）
                if seen is not None:
                    seen.add(r["summary_id"])  # 只有真的搶到才標 seen，中斷的會被補搶
                log(f"   ✅ [{cl.label}] 搶到 {g['name']} / {g['phone']}｜{g['city']} {g['category']} {g['budget']}")
            elif seen is not None:
                seen.add(r["summary_id"])       # apply 明確回「沒搶到」→ 標 seen 免得一直重試同一筆
        remain = q - succ
        quota_left += max(remain, 0)
        if not dry_run and remain <= 0:
            done.add(cl.label)      # 這帳號配額用完了
    return grabbed, done, quota_left


# ---------- 單次模式 ----------

def run_once(clients: list, dry_run: bool) -> int:
    info = clients[0].check_ip()
    if not info.get("allowed"):
        print(f"⛔ 這台機器 IP {info.get('ip')} 不在門市網路，KEIS 公買功能被擋。請放到店裡、連門市網路的電腦上跑。")
        return 1
    print(f"✅ IP {info.get('ip')} 在門市網路，可用")

    cands, _ = pick_candidates(clients[0].query())
    tot_quota = 0
    for cl in clients:
        _, q = pick_candidates(cl.query())
        print(f"   帳號 {cl.label}：剩餘配額 {q}")
        tot_quota += q
    print(f"📋 符合條件可申請 {len(cands)} 筆，{len(clients)} 帳號合計剩餘配額 {tot_quota} 筆")
    if not cands:
        print("😴 沒有符合條件且可申請的名單，這次不動作")
        return 0

    take = cands if MAX_APPLY_PER_RUN is None else cands[:MAX_APPLY_PER_RUN]
    print(f"🎯 這次會依各帳號配額分工搶（最多 {len(take)} 筆）")

    grabbed, _, qleft = grab_across_accounts(clients, take, dry_run)
    if dry_run:
        print("\n🟡 dry-run：以上只是預覽，沒有真的送出。確認沒問題後加 --apply 才會搶。")
        return 0
    if grabbed:
        append_csv(grabbed)
        for g in grabbed:
            push_notion(g)
        notify_grabbed(grabbed, qleft)
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
        delta = (sh * 60 + sm - cur) % (24 * 60)
        delta = delta or 24 * 60
        best = delta if best is None else min(best, delta)
    return min((best or 1) * 60, OFF_WINDOW_RECHECK_SEC)


def run_watch(clients: list, dry_run: bool) -> int:
    mode = "dry-run（只印不搶）" if dry_run else "實搶"
    labels = "、".join(c.label for c in clients)
    log(f"👁 watch 啟動（{mode}），帳號：{labels}（共 {len(clients)} 個，各 7 配額）")
    log(f"   監控時段 {WATCH_WINDOWS}，每 ~{POLL_INTERVAL_SEC}s 掃一次。Ctrl+C 結束。")
    try:
        info = clients[0].check_ip()
        if info.get("allowed"):
            log(f"✅ IP {info.get('ip')} 在門市網路，開始監控")
        else:
            log(f"⛔ IP {info.get('ip')} 不在門市網路，會持續重試（把它放到店裡的電腦）")
            notify({"event": "alert", "text": f"⚠ KEIS 搶單：這台 IP {info.get('ip')} 不在門市網路"})
    except Exception as e:
        log(f"⚠ 初次連線失敗（會自動重試）：{type(e).__name__}: {e}")

    # 啟動先回查一次：補回上個時段／上次執行時漏記的幽靈搶單（7 天窗口內都救得到）
    try:
        rec = reconcile_applications(clients, dry_run)
        if rec:
            log(f"↩ 啟動回查補回 {len(rec)} 筆漏記名單")
            notify_grabbed(rec, 0)
    except Exception as e:
        log(f"⚠ 啟動回查失敗（略過）：{type(e).__name__}")

    seen: set[int] = set()
    seen_day = None
    done_accounts: set = set()       # 今日已用完配額的帳號 label
    done_day = None
    all_done_logged_day = None
    was_in_window = False            # 用來偵測「剛收盤」的瞬間，收盤時回查對帳一次
    last_alert = 0.0
    # 今日戰果累計（跨日歸零）。counted_today 專門給「新名單計數」用，跟搶單的 seen 分開——
    # seen 只在真的搶到/明確被拒才標，才能讓逾時中斷的單留給下一輪補搶；日累計不能干擾它。
    day_new = 0                      # 今日符合條件的新名單累計（不管搶到沒）
    day_grabbed = 0                  # 今日實際搶到累計
    counted_today: set = set()       # 今日已計數過的 summary_id（避免重複算 day_new）
    counter_day = None
    appear_day, appear_max = _load_appear_state()   # 上架偵測狀態（撐過重啟）

    while True:
        try:
            now = datetime.now()
            if seen_day != now.date():       # 跨日重置
                seen.clear()
                seen_day = now.date()
            if done_day != now.date():
                done_accounts.clear()
                done_day = now.date()
            if counter_day != now.date():    # 跨日把今日戰果歸零
                day_new = 0
                day_grabbed = 0
                counted_today.clear()
                counter_day = now.date()

            inw = in_window(now)
            if was_in_window and not inw:
                # 剛收盤（離開時段的瞬間）：此刻沒在搶單，回查各帳號申請、補回漏記的幽靈搶單
                rec = reconcile_applications(clients, dry_run)
                if rec:
                    log(f"↩ 收盤回查補回 {len(rec)} 筆漏記名單")
                    notify_grabbed(rec, 0)
                # 收盤保底通知：不管今天有沒有搶到都推一則今日戰果（掛 0 那天也一定有訊息）
                notify_daily_summary(day_new, day_grabbed + len(rec), recovered=len(rec))
            was_in_window = inw
            if not inw:
                time.sleep(seconds_to_next_window(now))
                continue

            body = clients[0].query()
            cands, _ = pick_candidates(body)
            appear_day, appear_max = observe_appearances(
                body.get("data", []), appear_day, appear_max)  # 記錄新名單上架時刻

            # 先算今日新名單累計——就算配額用完、還沒搶，也要算得到，這樣收盤/搶到時 LINE
            # 才能顯示「新名單 N 筆卻只搶到 M 筆」，一眼分辨貨少 vs 搶輸/配額滿。用獨立的
            # counted_today，不動搶單的 seen。
            for r in cands:
                if r["summary_id"] not in counted_today:
                    counted_today.add(r["summary_id"])
                    day_new += 1

            active = [c for c in clients if c.label not in done_accounts]
            if not active:                    # 所有帳號配額都用完
                if all_done_logged_day != now.date():
                    log("🈵 所有帳號配額用完，改為純觀測上架時間（不搶），直到時段結束")
                    all_done_logged_day = now.date()
                time.sleep(OBSERVE_INTERVAL_SEC)   # 留在時段內繼續觀測，不離開
                continue

            fresh = [r for r in cands if r["summary_id"] not in seen]
            if fresh:
                log(f"🔔 發現 {len(fresh)} 筆新名單（可搶帳號：{'、'.join(c.label for c in active)}）")
                # 逐筆搶：搶到就馬上寫 CSV + 標 seen；中途逾時不弄丟、剩下的下一輪自動補搶
                grabbed, newly_done, qleft = grab_across_accounts(
                    active, fresh, dry_run, seen=seen, persist=True)
                done_accounts |= newly_done
                day_grabbed += len(grabbed)
                if grabbed:
                    notify_grabbed(grabbed, qleft, day_new, day_grabbed)

            time.sleep(POLL_INTERVAL_SEC + random.uniform(-POLL_JITTER_SEC, POLL_JITTER_SEC))

        except KeyboardInterrupt:
            log("👋 手動停止監控")
            return 0
        except IPBlocked:
            if time.time() - last_alert > 1800:
                notify({"event": "alert", "text": "⚠ KEIS 搶單：IP 被擋（離開門市網路了？）"})
                last_alert = time.time()
            log("⛔ IP 被擋，60s 後重試")
            time.sleep(60)
        except Exception as e:
            # 開盤尖峰逾時是常態；別死等，短間隔隨機重試，才不會錯過剛放出的名單
            retry = random.uniform(ERROR_RETRY_MIN, ERROR_RETRY_MAX)
            log(f"⚠ 暫時性錯誤，{retry:.1f}s 後重試：{type(e).__name__}: {e}")
            time.sleep(retry)


def main() -> int:
    parser = argparse.ArgumentParser(description="KEIS 公買搶單（無瀏覽器版）")
    parser.add_argument("--apply", action="store_true", help="實際送出申請（不加只 dry-run）")
    parser.add_argument("--watch", action="store_true", help="常駐監控模式（早上時段高頻掃）")
    args = parser.parse_args()

    accts = load_accounts()
    if not accts:
        raise SystemExit("❌ 沒設 KEIS_USERNAME / KEIS_PASSWORD（填在 .env）")

    dry_run = DRY_RUN and not args.apply
    clients = [Keis(u, p) for u, p in accts]
    print(f"👤 登入 KEIS：{'、'.join(c.label for c in clients)}（{len(clients)} 帳號）")
    if args.watch:
        return run_watch(clients, dry_run)
    return run_once(clients, dry_run)


if __name__ == "__main__":
    sys.exit(main())
