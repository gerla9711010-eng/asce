#!/usr/bin/env python3
"""
KEIS 公買搶單自動化（輕量無瀏覽器版）

掃「查詢公買 → 買屋需求列表」，把還能申請(status=Available)且符合條件的最新名單
自動申請私買，搶到後拿到沒遮罩的真實姓名＋電話，推一筆到 LINE。

⚠️ 這個功能 KEIS「僅限門市內使用」——伺服器會擋 IP，只有門市網路能用。
   所以本腳本要跑在「店裡、連門市網路、且一直開著」的電腦上（例如公司電腦不關機）。

無人看管長期跑：watch 模式全天候循環，依 WATCH_TIERS 分時段用不同頻率掃(熱門時段高頻、
一般時段中頻、深夜低頻)；遇到暫時性錯誤（斷網、逾時）不會死，會自己重試(3~8秒)；
連續失敗夠多次(判斷是真的斷網而非開盤塞車)會自動拉長到5分鐘一次並推LINE告知，恢復時也會推。
搭配 run.bat 開機自動啟動 + 掛掉自動重開。

用法:
    python grab.py                 # 單次 dry-run：列出「這次會搶誰」，不送出
    python grab.py --apply         # 單次實搶
    python grab.py --watch         # 常駐監控(dry-run)：全天分層掃，只印不搶
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
import re
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

# ====== 品質控管篩選（2026-07-22 加）======
ONLY_MOBILE = True            # True=只搶號碼是手機的，市話/空號一律不搶
EXCLUDE_TYPES = ["公寓"]      # 這些類型不搶；類型空白 / "-" 不受影響照收
MIN_BUDGET_CEILING = 1000     # 預算「上限」低於這個(萬)不搶；預算空白不受影響照收

# ====== 可視範圍（2026-07-23 加）======
# 舊版只抓 page1 / page_size=20，等於「照單號排序的最新 20 筆」窗口。池子裡卡著大量
# CoolingDown，一旦某天新進池的批次超過 20 筆、或編號夾在中間，就會有成員擠不進窗口。
# 修法：①每輪窗口 20 → 100；②每 DEEP_SWEEP_SEC 做一次全池分頁掃描，深到底都看得到。
PAGE_SIZE = 100               # 每輪查詢的窗口大小（單次請求，成本跟 20 幾乎一樣）
DEEP_SWEEP_SEC = 600          # 每隔幾秒做一次「全池分頁掃描」（目前約 29 頁 2800 筆）
DEEP_SWEEP_MAX_PAGES = 40     # 全池掃描最多翻幾頁（每頁 100 筆），防呆用
DEEP_SWEEP_ROTATE = True      # 每次全池掃描輪流換一個帳號查。原因：帳號看不到自己申請過的
                              # 名單，固定用同一個帳號會有一塊永遠的盲區（實測三帳號視角
                              # 分別看到 2823/2835/2836 筆，聯集 2856 筆）

# ====== 只要真新單、不要二手貨（2026-07-23 加，使用者明確要求）======
# 【KEIS 的殘酷事實，2026-07-23 實測證明】名單被申請後進 CoolingDown 7 天，到期會
# **回到池子重新變 Available，而且 app_time 被清空**——從 API 的單一快照上，二手回鍋貨
# 跟全新名單長得一模一樣（實測：我方 8 天前搶到的 53 筆，現在有 16 筆以 Available/
# app_time=None 躺在池子裡，另 37 筆的 app_time 是「7 天後接手的別人」）。
# 所以池子裡那 1000+ 筆 Available 絕大多數是輪了好幾手的二手貨，不是存貨。
#
# 【判定方法】API 分不出來 → 只能靠自己的紀錄擋：每個 summary_id 第一次進到我們視野時
# 是什麼狀態，永久記在 inventory.csv。只有「第一次看到就是 Available、且從沒被我們看過
# 是 CoolingDown、也不是建立基準當下就已經躺在池子裡」的，才算真新單、才會去搶。
#
# 【「最新名單」的唯一定義，2026-07-23 三帳號交叉觀測後定案，不要再加別的條件】
#     這個 summary_id 從沒出現在我們的完整總帳裡 ＝ 剛進池 ＝ 最新名單。
# 就這一條，不摻建檔日期、不摻編號大小。理由：
#   ① 建檔日期不能用：同樣建檔 07-16 的名單分散在兩個編號帶——77192/77196 是 07-20 18:00
#      才進池（許育禎當天就搶到），74251~74619 卻是 07-16 18:00 就進池、躺了 7 天後被同業
#      在 07-23 早上掃走。用建檔日期判斷會把躺 7 天的舊貨當成新單。
#   ② 編號大小也不能單獨用：同一批進池的編號會橫跨一個區間（74xxx 跟 76xxx 同批），
#      「編號 > 當日最大號」會漏掉批次裡編號較小的成員（舊的 appearances.csv 就是這樣
#      整批漏記 74xxx 的）。
#   ③ 前提成立：還沒釋出的名單根本不在 query 結果裡（實測建檔 07-19~07-21 當天一筆都
#      查不到），所以「第一次在池子裡看到它 ＝ 它剛進池」。
# 為了讓這條定義站得住，掃描必須是**完整全池**（分頁掃到底），否則「沒看過」會被
# 「窗口太小沒掃到」污染——這就是 PAGE_SIZE/DEEP_SWEEP 要放大的真正理由。
ONLY_TRULY_NEW = True         # True=只搶真新單（強烈建議；False 會連二手回鍋貨一起搶）

# --- watch 常駐監控模式設定（本機時間，店裡電腦請設成 Asia/Taipei）---
# 2026-07-15 改成全天分層輪詢，不再有「時段外」完全不看：熱門時段(早上開盤+晚上同業活躍)
# 用高頻、白天一般時段用中頻、深夜幾乎沒人動用低頻。(開始, 結束, 間隔秒數)，24h 制、需連續涵蓋一整天。
# 2026-07-22 調整：早上高頻起跑延到 07:30(釋出實測沒早於此)、晚上高頻提早到 17:30 起、
# 深夜 00:00~07:30 併成一段最低頻安全網(等同「停止」，隔天 07:30 接上高頻)。
WATCH_TIERS = [
    ("07:30", "10:00", 5),     # 熱門：早上開盤 + 觀察到的同業活躍窗口
    ("10:00", "17:30", 60),    # 一般：白天，1 分鐘一次
    ("17:30", "24:00", 5),     # 熱門：晚上同業活躍(實測 19:2x~19:5x 有申請潮)
    ("00:00", "07:30", 1800),  # 深夜：30 分鐘一次，純安全網(等同停止監控)
]
POLL_JITTER_SEC = 3          # 每次再隨機 ±這個秒數，別像節拍器（越大越不規律）

# 已知的每晚斷網時段：門市 IP 半夜到清晨會斷網（2026-07-16 實測 00:00:04→07:22:22
# 整整 7.4 小時連不上，白天則完全沒有空窗）。這段時間連不上是「預期行為」，不是故障：
#   1. 不推斷線/恢復告警——否則每天早上網路一回來就噴一則假警報
#   2. 直接用低頻重試，別每 3~8 秒狂試洗掉整夜的 log
# 注意：斷網時任何 LINE 通知本來就送不出去（推播也要網路），所以這裡的重點是
# 「網路回來後不要倒過來告訴使用者剛剛斷過」，那對每晚必斷的環境沒有資訊量。
EXPECTED_OFFLINE = ("00:00", "08:00")

# 早上開盤搶最兇的窗口：一般暫時性錯誤的重試間隔在這段縮到最短，
# 別讓 3~8 秒的隨機重試錯過剛好卡在這幾分鐘釋出、幾秒被同業秒殺的名單。
# 2026-07-22 跟著 WATCH_TIERS 早上高頻起跑時間同步調整為 07:30。
OPEN_RUSH = ("07:30", "10:00")
OPEN_RUSH_RETRY_MIN = 1


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def in_window(now: "datetime", window: tuple) -> bool:
    """now 是否落在 (start,end) 這個 HH:MM 區間（支援跨午夜）。"""
    minutes = now.hour * 60 + now.minute
    start, end = (_hhmm_to_min(x) for x in window)
    if start <= end:
        return start <= minutes < end
    return minutes >= start or minutes < end


def in_expected_offline(now: "datetime") -> bool:
    """現在是不是落在「已知每晚斷網」時段（支援跨午夜的區間）。"""
    return in_window(now, EXPECTED_OFFLINE)


def current_tier_interval(now: "datetime") -> int:
    """回傳現在這一刻該用的輪詢間隔秒數。WATCH_TIERS 需連續涵蓋 00:00~24:00，沒對到就用保守的60秒。"""
    minutes = now.hour * 60 + now.minute
    for start, end, interval in WATCH_TIERS:
        if _hhmm_to_min(start) <= minutes < _hhmm_to_min(end):
            return interval
    return 60

# --- 低調 / 抗尖峰設定 ---
HTTP_TIMEOUT_SEC = 30        # 單次請求逾時；開盤塞車時多等一下再放棄
ERROR_RETRY_MIN = 3          # 時段內遇暫時性錯誤(逾時等)後，最短幾秒重試
ERROR_RETRY_MAX = 8          # ...最長幾秒（隨機取，別死等 30s 錯過開盤）
ERROR_ESCALATE_AFTER = 10    # 連續失敗這麼多次(約30~80秒)還沒好，判斷是真的斷網而非開盤塞車
ERROR_LONG_RETRY_SEC = 300   # 判斷斷網後改用這個間隔重試，別整夜每幾秒瘋狂重試灌爆log
# 註：抓到多筆時是「一次全搶」(秒搶)，中間不留間隔——刻意保留最高搶單成功率
# ==============================

KEIS_BASE = "https://keis.kshouse.com.tw"
API = f"{KEIS_BASE}/api/v1"

NOTIFY_WEBHOOK = os.environ.get("KEIS_NOTIFY_WEBHOOK", "").strip()

# 心跳：讓 n8n 知道「這個程序還活著」。每 10 分鐘 POST 一次到 n8n webhook（沒設就跳過），
# n8n 端排程檢查超過 2 小時沒心跳才推 LINE 告警——把「系統死了沒人知道」變成主動通知，
# 換掉原本每天固定推的跨日結算。失敗完全靜默（斷網時本來就送不出去，屬正常）。
HEARTBEAT_WEBHOOK = os.environ.get("KEIS_HEARTBEAT_WEBHOOK", "").strip()
HEARTBEAT_INTERVAL_SEC = 600

# 跨日結算改落地到本機 CSV（一天一行），LINE 不再天天推；要查戰果用 LINE 打「戰果」隨時查
DAILY_SUMMARY_CSV = Path(__file__).parent / "daily_summary.csv"

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
NOTION_PENDING = Path(__file__).parent / "notion_pending.txt"  # push_notion 失敗的 summary_id，等下次回查補寫
LOG_DIR = Path(__file__).parent / "logs"           # 每日一份 log，獨立資料夾（舊版 watch.log 停用但保留原檔）

# 高頻觀測檔搬離 OneDrive 同步路徑（2026-07-22）：page1_track / appearances / appear_state
# 每輪或每次新單都在寫，放 OneDrive 會被 Files On-Demand 弄成損毀檔。改放本機 LOCALAPPDATA。
_LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path(__file__).parent) / "keis-grab"
try:
    _LOCAL.mkdir(parents=True, exist_ok=True)
except Exception:
    _LOCAL = Path(__file__).parent      # 萬一建不了就退回原路徑，至少能跑

APPEAR_CSV = _LOCAL / "appearances.csv"      # 上架偵測：新名單第一次出現的時刻
# appear_state.txt（舊版「當日最大單號基準」）2026-07-23 起不再使用：
# 基準改成 inventory.csv 總帳本身，同批較小編號才不會整批漏記。
LOG_RETENTION_DAYS = 50                            # 最多留幾天，超過從最舊的開始刪


def _prune_old_logs() -> None:
    files = sorted(LOG_DIR.glob("*.log"))          # 檔名是 YYYY-MM-DD.log，字串排序=日期排序
    for old in files[:-LOG_RETENTION_DAYS]:
        try:
            old.unlink()
        except Exception:
            pass


def log(msg: str) -> None:
    """印出來 + 存進 logs/YYYY-MM-DD.log（無人看管時才查得到發生什麼事）。
    每天一個檔，超過 50 天自動砍最舊的。"""
    now = datetime.now()
    line = f"{now:%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        LOG_DIR.mkdir(exist_ok=True)
        day_file = LOG_DIR / f"{now:%Y-%m-%d}.log"
        is_new_day = not day_file.exists()
        with day_file.open("a", encoding="utf-8-sig") as f:
            f.write(line + "\n")
        if is_new_day:
            _prune_old_logs()
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
        if r.status_code in (400, 401):    # 401=token失效；400=偶發抽風/token邊界 → 重登再試一次
            self._login()
            r = self.c.get(f"{API}{path}", headers=self._auth())
        if r.status_code == 403:
            raise IPBlocked()
        r.raise_for_status()
        return r.json()

    def check_ip(self) -> dict:
        return self._get("/call-purchase/check-ip")

    def query(self, page: int = 1, page_size: int = PAGE_SIZE) -> dict:
        year = datetime.now().year
        params = {
            "page": page, "page_size": page_size, "inquiry_type": INQUIRY_TYPE,
            "only_my_applications": "false",
            "start_date": f"{year}-01-01 00:00:00", "end_date": f"{year}-12-31 23:59:59",
            "target_area": "", "property_category": "",
        }
        return self._get(f"/call-purchase/query?{urlencode(params)}")

    def query_deep(self, max_pages: int = DEEP_SWEEP_MAX_PAGES) -> dict:
        """全池分頁掃描：把所有頁抓回來併成一個 body（quota 用第一頁的）。
        用途見 CONFIG 的「可視範圍」——單靠 page1 會漏掉名次很深的釋出批次。
        比較貴（十幾個請求），所以只在 DEEP_SWEEP_SEC 間隔 / 收盤補配額時跑。"""
        first = self.query(page=1)
        recs = list(first.get("data") or [])
        page = 2
        while len(first.get("data") or []) == PAGE_SIZE and page <= max_pages:
            d = self.query(page=page).get("data") or []
            recs += d
            if len(d) < PAGE_SIZE:
                break
            page += 1
        body = dict(first)
        body["data"] = recs
        return body

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


def is_mobile(phone: str) -> bool:
    """判斷(通常被遮罩的)號碼是不是手機。query() 回來的號碼被遮成前 3 碼可見，
    例 '095*******'、市話 '716*******'/'055*******'——只看開頭就分得出來。
    台灣手機 = 09 開頭；有些後台把開頭的 0 吃掉存成 9 開頭，也算手機。
    其餘(市話區碼 02~08、存成 7…/3…、空號、開頭 00…)一律不是手機。"""
    d = re.sub(r"\D", "", phone or "")        # 只留數字（去掉遮罩星號/空白/橫線）
    if not d:
        return False
    return d.startswith("09") or d.startswith("9")


def skip_reason(rec: dict) -> str | None:
    """不搶這筆的原因（None = 符合條件可搶）。
    回傳原因字串而不是 bool，是為了寫進 inventory.csv——事後才查得出「這個單號當初
    為什麼沒搶」，不用再靠猜（使用者 2026-07-23 要求：每個編號都要有紀錄）。"""
    if rec.get("status") != "Available":
        return f"狀態={rec.get('status')}"
    if CITIES and rec.get("target_city") not in CITIES:
        return f"縣市={rec.get('target_city')}"

    # ---- 品質控管篩選（2026-07-22 加）----
    # 只要手機：市話 / 空號不搶
    if ONLY_MOBILE and not is_mobile(rec.get("phone_number")):
        return "非手機"
    # 類型公寓不搶；空白 / "-" 放行
    cat = rec.get("property_category")
    if cat and cat != "-" and cat in EXCLUDE_TYPES:
        return f"排除類型={cat}"
    # 預算「上限」低於門檻不搶；空白(0)放行。上限 = budget_end 優先，沒有才用 budget_start
    ceiling = rec.get("budget_end") or rec.get("budget_start") or 0
    if ceiling and ceiling < MIN_BUDGET_CEILING:
        return f"預算上限{ceiling:.0f}萬<{MIN_BUDGET_CEILING}"
    # ---- 品質控管篩選 end ----

    if PROPERTY_TYPES and rec.get("property_category") not in PROPERTY_TYPES:
        return f"非白名單類型={rec.get('property_category')}"
    budget = rec.get("budget_start") or 0
    if budget > 0:  # 0 = 未填預算，不拿來篩
        if MIN_BUDGET is not None and budget < MIN_BUDGET:
            return f"預算{budget:.0f}萬<下限{MIN_BUDGET}"
        if MAX_BUDGET is not None and budget > MAX_BUDGET:
            return f"預算{budget:.0f}萬>上限{MAX_BUDGET}"
    return None


def matches(rec: dict) -> bool:
    return skip_reason(rec) is None


def fmt_budget(rec: dict) -> str:
    s, e = rec.get("budget_start") or 0, rec.get("budget_end") or 0
    if not s and not e:
        return "-"
    if e and e != s:
        return f"{s:.0f}-{e:.0f}萬"
    return f"{s:.0f}萬{'以上' if not e else ''}"


def fmt_district(rec: dict) -> str:
    """需求區域(target_areas 是 list)組成字串，多區用「、」串。沒有就空字串。"""
    return "、".join(a for a in (rec.get("target_areas") or []) if a)


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


def age_days(rec: dict) -> float:
    """這筆名單建檔到現在幾天。解析不出來回傳 0（當成新的，寧可看到也別漏掉）。"""
    t = str(rec.get("start_time") or "")[:19].replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return (datetime.now() - datetime.strptime(t, fmt)).total_seconds() / 86400
        except ValueError:
            continue
    return 0.0


def pick_candidates(body: dict):
    """挑出符合篩選條件、狀態可申請的名單（建檔新→舊）。

    這裡只做「條件符合」的過濾，**不判斷新舊**——新舊一律交給總帳的 is_truly_new()，
    定義只有一條（編號沒在總帳出現過＝剛進池）。不要再在這裡加建檔日期之類的閘門，
    2026-07-23 實測證明用建檔日期會把躺 7 天的舊貨誤判成新單。"""
    records = body.get("data", [])
    quota = body.get("new_case_quota_remaining")
    quota = quota if quota is not None else 0
    cands = [r for r in records if matches(r)]
    cands.sort(key=lambda r: r.get("start_time", ""), reverse=True)
    return cands, quota


def query_any(clients: list, deep: bool = False) -> dict:
    """依序用各帳號查詢，第一個成功的就用。避免主帳號一次逾時/抽風就整輪全盲、
    錯過開盤那幾秒。IP 被擋是全帳號共通(同一台同一 IP)→ 直接往上拋。
    deep=True 走全池分頁掃描（貴，只在固定間隔/收盤補配額用）。"""
    last_exc = None
    for cl in clients:
        try:
            return cl.query_deep() if deep else cl.query()
        except IPBlocked:
            raise
        except Exception as e:
            last_exc = e
            continue
    raise last_exc if last_exc else RuntimeError("query_any: 沒有可用帳號")


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
            "district": fmt_district(r),
            "remarks": (r.get("remarks") or "").strip(),  # query() 就有、沒遮罩，不用再多打一次 API
        }
    log(f"   ❌ [{keis.label}] [{r['summary_id']}] 沒搶到（可能配額用完/被秒搶）：{data.get('message')}")
    return None


def append_csv(grabbed: list[dict]) -> None:
    """落地搶到的名單。2026-07-19：這裡原本完全沒有 try——名單在伺服器上已經搶
    成功，若本機寫檔這時炸掉（例如 OneDrive 又弄壞 CSV），例外會一路往上跑進
    watch 的主迴圈被誤判成「暫時性錯誤」重試，搶單資料卻悄悄沒有落地。
    現在失敗時把每筆內容印進 log（可手動補回）並推 LINE 告警，絕不能默默吞掉。"""
    try:
        new = not GRABBED_CSV.exists()
        with GRABBED_CSV.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["搶到時間", "帳號", "summary_id", "姓名", "電話", "縣市", "類型", "預算", "建檔時間", "行政區"])
            for g in grabbed:
                w.writerow([g["grabbed_at"], g.get("account", ""), g["summary_id"], g["name"], g["phone"],
                            g["city"], g["category"], g["budget"], g["start_time"], g.get("district", "")])
    except Exception as e:
        detail = "；".join(f"{g['summary_id']} {g['name']}/{g['phone']}" for g in grabbed)
        log(f"⚠ 寫 grabbed.csv 失敗！已搶到但本機沒落地，請手動補回：{detail}（{type(e).__name__}: {e}）")
        notify({"event": "alert",
                "text": f"⚠ KEIS 搶單：{len(grabbed)} 筆已搶到但寫檔失敗，請檢查 grabbed.csv：{detail[:200]}"})


# ---------- 上架偵測（唯讀觀測，不搶不吃配額）----------
# 2026-07-23 重做：舊版是「每天以當下池子最大 summary_id 為基準，只記冒出更大號的」，
# 有一個致命盲點——**同一批進池的名單編號會橫跨一個區間**，比基準小的成員整批不會被記到。
# 實例：74251~74619 那批（07-16 18:00 進池）因為當時基準已經是 76xxx，從頭到尾沒被記錄，
# 害我一度把它們誤判成「07-23 早上才釋出的新單」。
# 新版直接改用總帳：**只要這個編號從沒出現在 inventory.csv 裡，就是剛進池**，編號大小不管。
# 這也跟搶單的判定用同一條規則，不會再出現「觀測說是新的、搶單說不是」的分歧。

def _append_appearance(rows: list[dict]) -> None:
    """2026-07-19：原本沒有 try——appearances.csv 若被 OneDrive 弄壞，例外會炸出
    observe_appearances()，而它在主迴圈裡排在搶單邏輯『之前』，等於一個觀測用
    CSV 壞掉就會讓整個搶單被誤判成斷網、停擺。純觀測不該有這種殺傷力，失敗只記
    log，絕不能往外拋。"""
    try:
        new = not APPEAR_CSV.exists()
        with APPEAR_CSV.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["首次出現時間", "summary_id", "建檔時間", "縣市", "區域", "類型", "狀態"])
            for r in rows:
                w.writerow([r["seen"], r["id"], r["start"], r["city"], r["area"], r["cat"], r["status"]])
    except Exception as e:
        log(f"⚠ 寫 appearances.csv 失敗（純觀測，不影響搶單）：{type(e).__name__}")


def observe_appearances(newly: list) -> None:
    """把「總帳判定為剛進池」的名單記進 appearances.csv。
    newly 直接吃 update_inventory() 的回傳值——觀測與搶單共用同一條新舊判定，不會分歧。"""
    if not newly:
        return
    seen = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for r in sorted(newly, key=lambda x: x.get("summary_id", 0)):
        rows.append({"seen": seen, "id": r.get("summary_id"),
                     "start": r.get("start_time"),
                     "city": r.get("target_city") or "",
                     "area": "".join(r.get("target_areas") or []),
                     "cat": r.get("property_category") or "",
                     "status": r.get("status")})
    _append_appearance(rows)


def observe_status_changes(records: list, status_seen: dict) -> dict:
    """觀測既有名單的狀態轉換(CoolingDown/Available 互轉)，抓真正的釋出/被申請時間點。
    跟 observe_appearances 不同：那個只抓「全新單號」，這個抓「已經在看的單號，狀態變了」——
    2026-07-15 發現同業申請的時間點藏在 app_time 欄位、且不限早上，才加這個補上缺口。
    2026-07-15 加強：改記(status, app_time)組合，不只記狀態字串——輪詢間隔拉長後，有可能兩次
    輪詢之間名單整個「解封成Available→被別人申請走」被一次吃掉，前後狀態字串都是CoolingDown、
    表面上看不出變化，但 app_time 換了，代表中間確實新發生過一次申請，用這個訊號抓出「輪詢間隔
    太粗、真的漏接了」的情況，別再只靠建檔日期或能不能申請這種籠統依據判斷。
    只記錄「這輪跟上輪不一樣」的變化；第一次看到的單號只記基準、不記變化(不知道從哪個狀態轉來的)，
    純觀測、不吃配額、不影響搶單邏輯。狀態表只留在記憶體，重啟會清空(可接受，跟其他觀測狀態一致)。"""
    for r in records:
        sid = r.get("summary_id")
        if sid is None:
            continue
        cur_status = r.get("status")
        cur_app = r.get("app_time")
        prev = status_seen.get(sid)
        if prev is not None:
            prev_status, prev_app = prev
            if prev_status != cur_status:
                log(f"🔄 狀態變化 id{sid} {prev_status}→{cur_status}"
                    f"（建檔 {str(r.get('start_time'))[:16]}，app_time={str(cur_app)[:16]}）"
                    f"{r.get('target_city') or ''}{r.get('property_category') or ''}")
            elif cur_app and prev_app != cur_app:
                log(f"⚠ 疑似輪詢間隔漏接 id{sid}：狀態沒變({cur_status})但申請時間換了"
                    f"（{str(prev_app)[:16]} → {str(cur_app)[:16]}，建檔 {str(r.get('start_time'))[:16]}）"
                    f"{r.get('target_city') or ''}{r.get('property_category') or ''}")
        status_seen[sid] = (cur_status, cur_app)
    return status_seen


# 2026-07-19：舊檔 page1_track.csv 被 OneDrive Files On-Demand 把佔位檔弄成損毀的
# reparse point，連 Windows 內建的刪除/改名/robocopy 都拒絕處理，只能放棄搶救、
# 換新檔名重開一份（舊檔留在資料夾裡當廢棄物，不影響運作）。
# 2026-07-22：page1_track2.csv 也中招被弄壞，這次直接搬離 OneDrive 同步路徑(見上方 _LOCAL)根治。
TOPID_CSV = _LOCAL / "page1_track3.csv"  # 每輪記錄page1最新單號，供事後判斷輪詢間隔有沒有漏接


def track_top_id(records: list, also_ids: list[int] | None = None) -> None:
    """每輪都記一筆(不只變化時才記)，累積成連續時間序列——才能事後回答「這個時間點最新到哪個單號」，
    而不是只能盲目看建檔日期或狀態這種籠統依據。純觀測、獨立檔案，不影響其他邏輯。
    2026-07-15 加 also_ids：query() 只用 clients[0] 的帳號查，而該帳號自己申請過的名單會從
    自己的查詢結果裡消失(自己看不到自己搶到的)——如果剛好搶走的是當下最新那筆，算出來的
    max_id 會不合理地變小。也把「這一輪自己剛搶到的id」一起納入計算，避免這種假降。
    2026-07-19：寫入失敗曾被靜默吞掉，導致 OneDrive 弄壞檔案後斷流兩天沒人發現——
    改成連續失敗到一定次數才出聲一次，別每輪洗 log，但也不能再悄悄壞掉。"""
    ids = [r.get("summary_id") or 0 for r in records]
    if also_ids:
        ids.extend(also_ids)
    if not ids:
        return
    max_id = max(ids)
    try:
        is_new = not TOPID_CSV.exists()
        with TOPID_CSV.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if is_new:
                w.writerow(["時間", "page1最大單號", "page1筆數"])
            w.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), max_id, len(records)])
        if track_top_id.fail_count:
            log(f"✅ page1_track2.csv 恢復寫入（先前連續失敗 {track_top_id.fail_count} 次）")
        track_top_id.fail_count = 0
    except Exception as e:
        track_top_id.fail_count += 1
        now = time.time()
        if track_top_id.fail_count == 10 or (
                track_top_id.fail_count > 10 and now - track_top_id.last_alert > 3600):
            log(f"⚠ page1_track2.csv 連續寫入失敗 {track_top_id.fail_count} 次"
                f"（純觀測、不影響搶單）：{type(e).__name__}")
            track_top_id.last_alert = now


track_top_id.fail_count = 0
track_top_id.last_alert = 0.0


# ---------- 全名單編號總帳 inventory.csv（2026-07-23 加）----------
# 使用者要求：「所有的名單編號都要記錄好，我才知道之後是我有沒有漏、還是沒有記錄到、
# 還是我的庫存」。這支檔案就是那本總帳——池子裡出現過的每一個 summary_id 一行，
# 記它第一次被看到的時間/狀態、最後狀態、符不符合篩選（不符寫原因）、我方做了什麼。
#
# 它同時是「二手貨判定」的唯一依據（見 CONFIG 的 ONLY_TRULY_NEW）：
#   來源=新出現 → 第一次看到就是 Available、之前沒看過它 → 真新單，會搶
#   來源=基準快照 → 建立總帳當下就已經躺在池子裡的，來歷不明 → 不搶
#   曾冷卻=Y → 我們看過它是 CoolingDown（別人拿過），之後就算變回 Available 也是二手貨 → 不搶
INVENTORY_CSV = _LOCAL / "inventory.csv"     # 放本機、不進 OneDrive（怕又被同步弄壞）
INVENTORY_SAVE_SEC = 120                     # 最快多久寫一次檔（有新單號一定立刻寫）
INVENTORY_COLS = ["summary_id", "首次看到", "首次狀態", "來源", "曾冷卻", "最後看到", "最後狀態",
                  "建檔時間", "縣市", "行政區", "類型", "預算", "電話", "app_time",
                  "符合篩選", "不符原因", "我方動作", "我方帳號"]


def load_inventory() -> dict:
    """讀回總帳。壞掉/不存在都回空 dict（會被當成第一次建立基準，不會炸掉搶單）。"""
    inv: dict = {}
    if not INVENTORY_CSV.exists():
        return inv
    try:
        with INVENTORY_CSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                sid = (row.get("summary_id") or "").strip()
                if sid.isdigit():
                    inv[int(sid)] = row
    except Exception as e:
        log(f"⚠ 讀 inventory.csv 失敗（當成空的重建，舊資料仍在檔案裡）：{type(e).__name__}")
    return inv


def save_inventory(inv: dict) -> None:
    """全量重寫（先寫暫存檔再取代，避免寫到一半斷電/當機把總帳弄壞）。純紀錄，失敗只記 log。"""
    try:
        tmp = INVENTORY_CSV.with_suffix(".tmp")
        with tmp.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=INVENTORY_COLS, extrasaction="ignore")
            w.writeheader()
            for sid in sorted(inv, reverse=True):
                w.writerow(inv[sid])
        tmp.replace(INVENTORY_CSV)
        save_inventory.fail_count = 0
    except Exception as e:
        save_inventory.fail_count += 1
        if save_inventory.fail_count in (1, 10) or save_inventory.fail_count % 100 == 0:
            log(f"⚠ 寫 inventory.csv 失敗第 {save_inventory.fail_count} 次"
                f"（純紀錄、不影響搶單）：{type(e).__name__}")


save_inventory.fail_count = 0


def update_inventory(inv: dict, records: list, baseline: bool = False) -> list:
    """把這一輪看到的名單更新進總帳，回傳「這輪第一次看到的新單號」清單。
    baseline=True 用在總帳第一次建立時：當下池子裡的全部標成「基準快照」，一律不搶。"""
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    newly: list = []
    for r in records:
        sid = r.get("summary_id")
        if sid is None:
            continue
        reason = skip_reason(r)
        row = inv.get(sid)
        if row is None:
            row = {
                "summary_id": sid,
                "首次看到": now_s,
                "首次狀態": r.get("status") or "",
                "來源": "基準快照" if baseline else "新出現",
                "曾冷卻": "Y" if r.get("status") == "CoolingDown" else "N",
                "我方動作": "",
                "我方帳號": "",
            }
            inv[sid] = row
            if not baseline:
                newly.append(r)
        if r.get("status") == "CoolingDown":
            row["曾冷卻"] = "Y"          # 一旦被別人拿過就永久留記號，回鍋也不搶
        row.update({
            "最後看到": now_s,
            "最後狀態": r.get("status") or "",
            "建檔時間": str(r.get("start_time") or "")[:16],
            "縣市": r.get("target_city") or "",
            "行政區": fmt_district(r),
            "類型": r.get("property_category") or "",
            "預算": fmt_budget(r),
            "電話": r.get("phone_number") or "",
            "app_time": str(r.get("app_time") or "")[:16],
            "符合篩選": "N" if reason else "Y",
            "不符原因": reason or "",
        })
    return newly


def is_truly_new(inv: dict, rec: dict) -> bool:
    """是不是「真新單」＝這個編號從沒出現在總帳裡（剛進池）。定義見 CONFIG，只有這一條：

      沒紀錄              → 剛進池的真新單，可搶（未釋出的名單不會出現在 query 裡）
      來源=新出現+首次Available → 我們親眼看到它進池、當時沒人碰 → 可搶
      曾冷卻=Y            → 二手貨（別人或我方拿過又回鍋），不搶
      來源=基準快照        → 建總帳之前就在池子裡＝來歷不明，不搶
                            （不用建檔日期救，那會把躺 7 天的舊貨誤判成新單）"""
    row = inv.get(rec.get("summary_id"))
    if row is None:
        return True                                   # 沒紀錄=這一刻剛進池
    if str(row.get("曾冷卻", "")).upper() == "Y":
        return False
    if row.get("來源") == "基準快照":
        return False
    return str(row.get("首次狀態", "")) == "Available"


def mark_inventory_grabbed(inv: dict, sid, account: str, action: str = "搶到") -> None:
    row = inv.get(sid)
    if row is not None:
        row["我方動作"] = action
        row["我方帳號"] = account
        if action == "搶到":
            # 自己搶到的也要蓋「曾冷卻」章。原因：查詢帳號看不到自己申請過的名單，
            # 所以我方搶走的那筆不會被觀測到 CoolingDown；7 天到期回鍋、app_time 又被
            # 洗掉時，它看起來就像一筆全新單 → 會拿配額去搶自己七天前搶過的東西。
            row["曾冷卻"] = "Y"


def seed_inventory_from_grabbed(inv: dict) -> int:
    """把 grabbed.csv 裡歷史搶過的編號補進總帳並蓋「曾冷卻」章。
    總帳是 2026-07-23 才開始記的，在那之前搶到的名單這幾天正陸續 7 天到期回鍋成
    Available（實測 53 筆裡已有 16 筆回到池子），沒有這一步就會重複搶自己的舊名單。"""
    n = 0
    now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not GRABBED_CSV.exists():
        return 0
    try:
        with GRABBED_CSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("搶到時間") or len(row) < 3:
                    continue
                sid = str(row[2]).strip()
                if not sid.isdigit():
                    continue
                sid = int(sid)
                if sid not in inv:
                    inv[sid] = {"summary_id": sid, "首次看到": row[0], "首次狀態": "(我方搶到)",
                                "來源": "我方歷史搶單", "最後看到": now_s}
                    n += 1
                inv[sid]["曾冷卻"] = "Y"
                if not inv[sid].get("我方動作"):
                    inv[sid]["我方動作"] = "搶到"
                    inv[sid]["我方帳號"] = row[1] if len(row) > 1 else ""
    except Exception as e:
        log(f"⚠ 用 grabbed.csv 補總帳失敗（略過）：{type(e).__name__}")
    return n


def notify(payload: dict) -> bool:
    """推一則到 n8n → LINE。回傳有沒有真的送出去。
    舊版把失敗吞掉又用 print（不進 log 檔），呼叫端還照樣寫「已推」——等於 log 會騙人說
    送出去了。斷網時推播本來就送不出去，這件事必須看得見，所以改成 log + 回傳成功與否。"""
    if not NOTIFY_WEBHOOK:
        return False
    try:
        r = httpx.post(NOTIFY_WEBHOOK, json=payload, timeout=15)
        if r.status_code >= 400:
            log(f"⚠ LINE 通知被拒 HTTP {r.status_code}: {r.text[:120]}")
            return False
        return True
    except Exception as e:
        log(f"⚠ LINE 通知送不出去（斷網時屬正常）：{type(e).__name__}")
        return False


def notify_grabbed(grabbed: list[dict], quota_left: int,
                   new_today: int | None = None, grabbed_today: int | None = None) -> None:
    payload = {"event": "grabbed", "grabbed": grabbed, "quota_left": quota_left}
    if new_today is not None:                # 開盤搶單才帶今日累計；補漏回查不帶（退回本批數）
        payload["new_today"] = new_today
        payload["grabbed_today"] = grabbed_today
    ok = notify(payload)
    extra = f"（今日新名單 {new_today}／搶到 {grabbed_today}）" if new_today is not None else ""
    # 2026-07-21：這裡原本不管 notify() 有沒有真的送出去，都固定印「已推」——
    # 導致一筆 LINE 因斷線送失敗（notify() 已回傳 False、且上面已印過失敗原因），
    # 這行卻照樣宣稱成功，讓人以為訊息有送到，白白錯過補救時機。資料本身沒有
    # 遺失（grabbed.csv／Notion 該有的都有），純粹是這行 log 講錯話，改成照實際結果印。
    if ok:
        log(f"📲 已推 {len(grabbed)} 筆到 LINE{extra}")
    else:
        log(f"❌ LINE 推播失敗，{len(grabbed)} 筆沒送到手機{extra}"
            f"（資料已存 grabbed.csv／Notion，不會遺失，之後可用 LINE 打「戰果」查回來）")


def push_heartbeat() -> None:
    """對 n8n 打一下心跳（fire-and-forget）。timeout 短、失敗靜默——
    斷網時段送不出去屬正常，絕不能拖慢搶單迴圈。"""
    if not HEARTBEAT_WEBHOOK:
        return
    try:
        httpx.post(HEARTBEAT_WEBHOOK,
                   json={"ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                   timeout=5)
    except Exception:
        pass


def write_daily_summary(date_str: str, new_today: int, grabbed_today: int, recovered: int = 0) -> None:
    """跨日結算落地到本機 CSV（一天一行）。取代原本每天推 LINE 的跨日結算——
    使用者嫌訊息多，改成：戰果想查用 LINE 打「戰果」；系統死活靠心跳告警；
    事後稽核看這個檔。date_str 是「被結算的那一天」（跨日前記住的昨天）。"""
    try:
        new = not DAILY_SUMMARY_CSV.exists()
        with DAILY_SUMMARY_CSV.open("a", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["日期", "新名單", "搶到", "補回"])
            w.writerow([date_str, new_today, grabbed_today, recovered])
    except Exception as e:
        log(f"⚠ 寫 daily_summary.csv 失敗：{type(e).__name__}")
    log(f"📒 跨日結算已落地（{date_str} 新名單 {new_today}／搶到 {grabbed_today}"
        f"{f'／補回 {recovered}' if recovered else ''}）")


def _notion_dt(s: str) -> str:
    """把 grab.py 的時間字串轉成 Notion 吃的 ISO（補台灣時區）。
    "2026-07-10 08:00:02" → "2026-07-10T08:00:02+08:00"；已含 T 的建檔時間也一併補時區。"""
    s = (s or "").strip().replace(" ", "T")
    return s + "+08:00" if s and "+" not in s else s


def _load_notion_pending() -> set:
    if not NOTION_PENDING.exists():
        return set()
    try:
        return {ln.strip() for ln in NOTION_PENDING.read_text(encoding="utf-8").splitlines() if ln.strip()}
    except Exception:
        return set()


def _save_notion_pending(sids: set) -> None:
    try:
        NOTION_PENDING.write_text("\n".join(sorted(sids, key=lambda s: (len(s), s))), encoding="utf-8")
    except Exception as e:
        log(f"⚠ 寫 notion_pending.txt 失敗（純記錄，下次啟動會少查一筆待補）：{type(e).__name__}")


def _mark_notion_pending(sid) -> None:
    pending = _load_notion_pending()
    pending.add(str(sid))
    _save_notion_pending(pending)


def _clear_notion_pending(sids: set) -> None:
    if not sids:
        return
    pending = _load_notion_pending() - {str(s) for s in sids}
    _save_notion_pending(pending)


def notion_exists(sid) -> bool | None:
    """查 Notion 資料庫裡有沒有這個 summary_id 的頁面。True/False=查到結果，
    None=查詢本身失敗（斷網/逾時等，不代表沒有），呼叫端遇到 None 要當「不確定」處理，
    絕不能當成 False 去重推，否則斷網時反而會造成重複建檔。"""
    if not (NOTION_TOKEN and NOTION_DB_ID):
        return None
    try:
        r = httpx.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers={"Authorization": f"Bearer {NOTION_TOKEN}",
                     "Notion-Version": "2022-06-28",
                     "Content-Type": "application/json"},
            json={"filter": {"property": "summary_id", "rich_text": {"equals": str(sid)}}, "page_size": 1},
            timeout=15,
        )
        if r.status_code >= 300:
            log(f"   ⚠ Notion 查詢失敗 HTTP {r.status_code}: {r.text[:150]}")
            return None
        return bool(r.json().get("results"))
    except Exception as e:
        log(f"   ⚠ Notion 查詢例外：{type(e).__name__}")
        return None


def load_grabbed_row(sid) -> dict | None:
    """從本機 grabbed.csv 撈回一筆完整資料，給 Notion 補寫回查用（重建 push_notion 要的欄位）。"""
    if not GRABBED_CSV.exists():
        return None
    try:
        with GRABBED_CSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("搶到時間") or len(row) < 9:
                    continue
                if str(row[2]).strip() == str(sid):
                    return {"grabbed_at": row[0], "account": row[1], "summary_id": row[2],
                             "name": row[3], "phone": row[4], "city": row[5],
                             "category": row[6], "budget": row[7], "start_time": row[8],
                             "district": row[9] if len(row) >= 10 else "",
                             "remarks": ""}
    except Exception as e:
        log(f"⚠ 讀 grabbed.csv 撈補寫資料失敗：{type(e).__name__}")
    return None


def reconcile_notion() -> int:
    """回查 notion_pending.txt，補上先前 push_notion 失敗的名單。
    每筆先用 notion_exists() 確認 Notion 裡真的沒有(例如 07-21 那次 ReadTimeout，其實伺服器
    已經寫進去、只是客戶端沒等到回應)，避免補寫變成重複建檔；查詢本身失敗(None)就跳過這筆、
    留到下次再查，絕不能在不確定的情況下硬推。全程 best-effort，出錯只記 log。"""
    pending = _load_notion_pending()
    if not pending:
        return 0
    synced = set()
    for sid in pending:
        exists = notion_exists(sid)
        if exists is None:
            continue                      # 查詢本身失敗，這筆先留著，下次回查再試
        if exists:
            synced.add(sid)               # 其實早就有了（只是先前誤判失敗），標記完成不用補推
            continue
        rec = load_grabbed_row(sid)
        if rec is None:
            log(f"⚠ notion_pending 有 {sid} 但 grabbed.csv 找不到這筆，先跳過")
            continue
        if push_notion(rec):
            log(f"   ↩ [Notion 補寫] {sid} {rec['name']}/{rec['phone']}")
            synced.add(sid)
    if synced:
        _clear_notion_pending(synced)
    return len(synced)


def push_notion(g: dict) -> bool:
    """把搶到的一筆寫進 Notion 資料庫（沒設 token 就跳過；失敗只記 log + 記進 notion_pending.txt
    等下次回查補寫，絕不影響搶單本身）。回傳有沒有真的寫進去。"""
    if not (NOTION_TOKEN and NOTION_DB_ID):
        return False
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
    if g.get("district"):
        props["行政區"] = {"rich_text": [{"text": {"content": g["district"]}}]}
    if g.get("remarks"):
        props["備註"] = {"rich_text": [{"text": {"content": g["remarks"][:2000]}}]}
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
            _mark_notion_pending(g["summary_id"])
            return False
        return True
    except Exception as e:
        # 逾時等例外不代表沒寫進去——伺服器可能已經處理成功、只是客戶端沒等到回應
        # （2026-07-21 實測過一次：ReadTimeout 但 Notion 裡其實有）。所以這裡不能斷定失敗，
        # 只能記進待查清單，讓 reconcile_notion() 之後用 notion_exists() 查清楚再決定要不要補推。
        log(f"   ⚠ Notion 寫入例外（不影響搶單，已記待查）：{type(e).__name__}")
        _mark_notion_pending(g["summary_id"])
        return False


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


def load_today_grabbed() -> tuple[int, set]:
    """讀 grabbed.csv 裡「今天搶到」的筆數與 summary_id 集合。
    watch 啟動時用來回填當日累計——計數器存記憶體，白天重啟過的話跨日結算
    會少算重啟前搶到的（2026-07-15 實際發生：全天 13 筆只報 6）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    count, sids = 0, set()
    if not GRABBED_CSV.exists():
        return count, sids
    try:
        with GRABBED_CSV.open(encoding="utf-8-sig", newline="") as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("搶到時間"):
                    continue
                if not row[0].startswith(today):
                    continue
                sid = row[2] if len(row) >= 9 else ""
                if sid:
                    count += 1
                    sids.add(int(sid) if str(sid).strip().isdigit() else sid)
    except Exception as e:
        log(f"⚠ 讀 grabbed.csv 回填當日累計失敗（從 0 起算）：{type(e).__name__}")
    return count, sids


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
        "district": fmt_district(app),
        "remarks": (app.get("remarks") or "").strip(),
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
    inventory = load_inventory()
    if ONLY_TRULY_NEW and inventory:
        before = len(cands)
        cands = [r for r in cands if is_truly_new(inventory, r)]
        if before != len(cands):
            print(f"♻ 其中 {before - len(cands)} 筆是二手貨（別人拿過回鍋 / 建總帳前就在池子裡），不搶")
    elif ONLY_TRULY_NEW:
        print("📒 還沒有 inventory.csv 總帳 → 分不出二手貨。先跑一次 --watch 建立基準再說")
        cands = []
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

def run_watch(clients: list, dry_run: bool) -> int:
    mode = "dry-run（只印不搶）" if dry_run else "實搶"
    labels = "、".join(c.label for c in clients)
    log(f"👁 watch 啟動（{mode}），帳號：{labels}（共 {len(clients)} 個，各 7 配額）")
    log(f"   全天分層輪詢：{WATCH_TIERS}（開始,結束,間隔秒）。Ctrl+C 結束。")
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
        n = reconcile_notion()
        if n:
            log(f"↩ 啟動回查補寫 Notion {n} 筆")
    except Exception as e:
        log(f"⚠ 啟動回查失敗（略過）：{type(e).__name__}")

    seen: set[int] = set()
    seen_day = None                  # 唯一的「今天是哪天」狀態，跨日時一次重置所有日累計
    done_accounts: set = set()       # 今日已用完配額的帳號 label
    all_done_logged_day = None
    last_alert = 0.0
    # 今日戰果累計（跨日歸零）。counted_today 專門給「新名單計數」用，跟搶單的 seen 分開——
    # seen 只在真的搶到/明確被拒才標，才能讓逾時中斷的單留給下一輪補搶；日累計不能干擾它。
    # 啟動時從 grabbed.csv 回填「今天已搶」——計數器存記憶體，白天重啟過的話跨日結算
    # 會少算重啟前搶到的（07-15 實際發生：全天 13 筆只報 6）。day_new 沒有可靠的落地
    # 來源可回讀（appearances.csv 沒存預算、也含不符篩選的），用「已搶筆數」當下限起算：
    # 每筆搶到的當時都算過一次新名單，重啟後頂多少算「看過但沒搶到」的，不會多算。
    day_grabbed, _today_sids = load_today_grabbed()
    day_new = day_grabbed
    counted_today: set = set(_today_sids)   # 回填過的不再重複算 day_new
    seen |= _today_sids                      # 也不用再嘗試搶（本來就已搶到）
    if day_grabbed:
        log(f"↺ 回填當日累計：今天已搶 {day_grabbed} 筆（重啟不歸零）")
    deep_sweep_turn = 0              # 全池掃描輪到哪個帳號（輪流換，避開自己申請的盲區）
    status_seen: dict = {}                          # 狀態變化觀測（記憶體，重啟會清空）
    last_deep_sweep = 0.0            # 上次全池掃描時刻；0=啟動後第一輪就先掃一次全池
    inventory = load_inventory()     # 全名單編號總帳（也是二手貨判定依據），撐過重啟
    inventory_ready = INVENTORY_CSV.exists()   # 檔案存在＝基準已建立過（要在 seed 之前判斷）
    last_inventory_save = 0.0
    skipped_secondhand_logged: set = set()   # 二手貨每個編號只喊一次，別洗版
    if inventory:
        log(f"📒 讀回名單總帳 {len(inventory)} 筆（{INVENTORY_CSV}）")
    seeded = seed_inventory_from_grabbed(inventory)   # 歷史搶過的一律蓋「曾冷卻」章，回鍋不再重搶
    if seeded:
        log(f"📒 用 grabbed.csv 補進 {seeded} 筆我方歷史搶單（回鍋時會被當二手貨擋掉）")
    consecutive_errors = 0           # 連續失敗次數；判斷是暫時塞車還是真的斷網
    alerted_disconnect = False       # 「斷線警告」有沒有真的送達；沒送達就別推恢復通知
    last_heartbeat = 0.0             # 上次心跳時刻；0=啟動後第一輪就先打一下

    while True:
        try:
            now = datetime.now()
            today = now.date()
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL_SEC:
                push_heartbeat()               # 放在查詢之前：就算 KEIS 掛了，程序活著也照報
                last_heartbeat = time.time()
            if seen_day is not None and seen_day != today:
                # 跨日：全天分層輪詢不再有「離開時段」這個時間點，改成每天換日的瞬間結算一次昨天。
                try:
                    rec = reconcile_applications(clients, dry_run)
                    if rec:
                        log(f"↩ 跨日回查補回 {len(rec)} 筆漏記名單")
                        notify_grabbed(rec, 0)
                    n = reconcile_notion()
                    if n:
                        log(f"↩ 跨日回查補寫 Notion {n} 筆")
                    write_daily_summary(seen_day.isoformat(), day_new,
                                        day_grabbed + len(rec), recovered=len(rec))  # 結算的是「昨天」
                except Exception as e:
                    log(f"⚠ 跨日收尾失敗（略過）：{type(e).__name__}")
                seen.clear()
                done_accounts.clear()
                day_new = 0
                day_grabbed = 0
                counted_today.clear()
            seen_day = today

            # 每輪掃 page1（PAGE_SIZE=100）；每隔 DEEP_SWEEP_SEC 改成全池分頁掃描，
            # 補抓「名次很深、但今天才釋出」的批次（07-23 漏接事故的根因，見 CONFIG 可視範圍）。
            deep_due = (time.time() - last_deep_sweep >= DEEP_SWEEP_SEC
                        and not in_expected_offline(now))
            if deep_due and DEEP_SWEEP_ROTATE and len(clients) > 1:
                # 輪流換帳號做全池掃描：帳號看不到自己申請過的名單，固定一個帳號會有盲區
                order = clients[deep_sweep_turn % len(clients):] + clients[:deep_sweep_turn % len(clients)]
                deep_sweep_turn += 1
                body = query_any(order, deep=True)
            else:
                body = query_any(clients, deep=deep_due)   # 主帳號一逾時就換下一個查，別整輪全盲
            if deep_due:
                last_deep_sweep = time.time()
            if consecutive_errors >= ERROR_ESCALATE_AFTER:
                log(f"✅ 網路恢復（先前連續失敗 {consecutive_errors} 次），回到正常監控頻率")
                # 只有「斷線警告真的推出去過」才推恢復通知：每晚必斷的時段推不出警告
                # （斷網時推播也送不出去），這時再推恢復等於每天早上噴一則沒資訊量的假警報。
                if alerted_disconnect:
                    notify({"event": "alert", "text": f"✅ KEIS 搶單：網路已恢復（先前斷線約連續失敗 {consecutive_errors} 次），回到正常監控頻率"})
                alerted_disconnect = False
            consecutive_errors = 0
            records = body.get("data", [])

            # 總帳：把這輪看到的每個編號都記起來（含不符條件的），並判定誰是真新單。
            # 第一次建立時把當下整池標成「基準快照」——那些多半是輪過好幾手的二手貨，不能搶。
            if not inventory_ready:
                deep_body = body if deep_due else query_any(clients, deep=True)
                last_deep_sweep = time.time()
                records = deep_body.get("data", records)
                update_inventory(inventory, records, baseline=True)
                seed_inventory_from_grabbed(inventory)   # 我方歷史搶單的章不能被基準蓋掉
                save_inventory(inventory)
                inventory_ready = True
                last_inventory_save = time.time()
                log(f"📒 建立名單總帳 inventory.csv：當下池子 {len(inventory)} 筆全部標為「基準快照」"
                    f"（來歷不明、一律不搶），之後新進池的編號才算真新單")
                body = deep_body
            else:
                newly_seen = update_inventory(inventory, records)
                if newly_seen or time.time() - last_inventory_save >= INVENTORY_SAVE_SEC:
                    save_inventory(inventory)
                    last_inventory_save = time.time()
                observe_appearances(newly_seen)   # 上架偵測＝總帳說沒看過的編號（跟搶單同一條規則）
                for r in newly_seen:              # 每個新編號都留一行 log，事後可追
                    log(f"🆕 新進池 id{r.get('summary_id')} 首次看到＝{r.get('status')}"
                        f"｜{r.get('target_city') or ''}{fmt_district(r)} "
                        f"{r.get('property_category') or ''} {fmt_budget(r)}"
                        f"｜建檔{str(r.get('start_time'))[:16]}"
                        f"｜{'符合條件' if matches(r) else '不搶:' + str(skip_reason(r))}")

            cands, _ = pick_candidates(body)
            status_seen = observe_status_changes(body.get("data", []), status_seen)  # 記錄狀態轉換(誰、幾點被申請)

            # 先算今日新名單累計——就算配額用完、還沒搶，也要算得到，這樣結算/搶到時 LINE
            # 才能顯示「新名單 N 筆卻只搶到 M 筆」，一眼分辨貨少 vs 搶輸/配額滿。用獨立的
            # counted_today，不動搶單的 seen。
            # 2026-07-23：只算「真新單」，別把二手回鍋貨算成今日新名單灌水
            for r in cands:
                if r["summary_id"] not in counted_today and (
                        not ONLY_TRULY_NEW or is_truly_new(inventory, r)):
                    counted_today.add(r["summary_id"])
                    day_new += 1

            interval = current_tier_interval(now)  # 全天分層：熱門時段5秒、一般1分鐘、深夜5分鐘

            active = [c for c in clients if c.label not in done_accounts]
            if not active:                    # 所有帳號配額都用完
                if all_done_logged_day != today:
                    log("🈵 所有帳號配額用完，改為純觀測上架時間（不搶）")
                    all_done_logged_day = today
                track_top_id(body.get("data", []))  # 每輪記錄page1最新單號，供事後判斷輪詢間隔有沒有漏接
                time.sleep(interval)   # 繼續依分層頻率觀測，不離開
                continue

            # 只搶「真新單」：擋掉別人拿滿 7 天到期、洗掉 app_time 回鍋的二手貨
            # （API 分不出來，只能靠總帳擋——見 CONFIG 的 ONLY_TRULY_NEW）
            fresh = [r for r in cands if r["summary_id"] not in seen]
            if ONLY_TRULY_NEW:
                secondhand = [r for r in fresh if not is_truly_new(inventory, r)]
                fresh = [r for r in fresh if is_truly_new(inventory, r)]
                unlogged = [r for r in secondhand if r["summary_id"] not in skipped_secondhand_logged]
                for r in unlogged:
                    skipped_secondhand_logged.add(r["summary_id"])
                    mark_inventory_grabbed(inventory, r["summary_id"], "", "略過(二手貨)")
                if len(unlogged) > 5:      # 一次一大票（多半是剛建完基準）→ 只記一行總數，別洗版
                    log(f"♻ 跳過 {len(unlogged)} 筆二手貨（別人拿過回鍋 / 建總帳前就在池子裡），"
                        f"明細看 {INVENTORY_CSV.name}")
                else:
                    for r in unlogged:
                        row = inventory.get(r["summary_id"]) or {}
                        why = "曾被別人拿過(回鍋)" if row.get("曾冷卻") == "Y" else "建總帳前就在池子裡"
                        log(f"♻ 跳過二手貨 id{r['summary_id']}（{why}）"
                            f"{r.get('target_city') or ''} {r.get('property_category') or ''}")
            grabbed_ids_this_round: list[int] = []
            if fresh:
                log(f"🔔 發現 {len(fresh)} 筆真新單（可搶帳號：{'、'.join(c.label for c in active)}）")
                # 逐筆搶：搶到就馬上寫 CSV + 標 seen；中途逾時不弄丟、剩下的下一輪自動補搶
                grabbed, newly_done, qleft = grab_across_accounts(
                    active, fresh, dry_run, seen=seen, persist=True)
                done_accounts |= newly_done
                day_grabbed += len(grabbed)
                grabbed_ids_this_round = [g["summary_id"] for g in grabbed]
                for g in grabbed:
                    mark_inventory_grabbed(inventory, g["summary_id"], g.get("account", ""))
                if grabbed:
                    save_inventory(inventory)
                    last_inventory_save = time.time()
                    notify_grabbed(grabbed, qleft, day_new, day_grabbed)

            # 這一輪自己剛搶到的id也一起納入，避免clients[0]自己申請過的名單從自己視野消失、
            # 造成 max_id 誤判變小（見 track_top_id 說明）
            track_top_id(body.get("data", []), also_ids=grabbed_ids_this_round)

            time.sleep(interval + random.uniform(-POLL_JITTER_SEC, POLL_JITTER_SEC))

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
            # 開盤尖峰逾時是常態；別死等，短間隔隨機重試，才不會錯過剛放出的名單。
            # 但連續失敗太多次（約30~80秒還沒好）就判斷是真的斷網，改成低頻重試。
            consecutive_errors += 1
            offline_ok = in_expected_offline(datetime.now())   # 每晚必斷的時段 → 預期行為
            if offline_ok:
                # 已知斷網時段：直接低頻重試、完全不告警（斷網時也推不出去），log 只在
                # 剛進入時記一行，別整夜每 5 分鐘洗一次。
                retry = float(ERROR_LONG_RETRY_SEC)
                if consecutive_errors == ERROR_ESCALATE_AFTER:
                    log(f"🌙 已知深夜斷網時段（{EXPECTED_OFFLINE[0]}~{EXPECTED_OFFLINE[1]}）連不上，"
                        f"屬預期行為：改每 {retry:.0f}s 靜靜重試，不告警")
                elif consecutive_errors > ERROR_ESCALATE_AFTER:
                    time.sleep(retry)
                    continue                    # 靜默重試，不再寫 log
            elif consecutive_errors >= ERROR_ESCALATE_AFTER:
                retry = float(ERROR_LONG_RETRY_SEC)
                if consecutive_errors == ERROR_ESCALATE_AFTER:
                    log(f"⚠ 連續失敗 {consecutive_errors} 次，判斷是斷線中，改成每 {retry:.0f}s 重試一次")
                    if time.time() - last_alert > 1800:
                        # 記住「警告有沒有真的送達」——沒送達就別在網路回來後推恢復通知
                        if notify({"event": "alert",
                                   "text": f"⚠ KEIS 搶單：疑似斷線，已連續失敗 {consecutive_errors} 次，改成每 {int(retry // 60)} 分鐘重試"}):
                            alerted_disconnect = True
                        last_alert = time.time()
            else:
                lo = OPEN_RUSH_RETRY_MIN if in_window(datetime.now(), OPEN_RUSH) else ERROR_RETRY_MIN
                retry = random.uniform(lo, ERROR_RETRY_MAX)
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
