# -*- coding: utf-8 -*-
"""
買方配案系統 — 無人值守收集器（雙擊視窗按鈕觸發用，不排程）

流程：開瀏覽器(獨立 profile，第一次要手動登入一次) → 注入 collect.js → FDBM.run()
→ 輪詢進度、遇到分頁重整/讀不到客需樹自動重試 → 跑完/撞上限就停 → 匯出 localStorage
→ 轉成 data.json → upload.py（build_page.js 產頁 → 發布到 https://yc-buyer-match.pages.dev/）。

用法：python worker.py [--full]
輸出：每行印一則狀態，給 gui.py 解析：
  STATUS|訊息
  NEED_LOGIN
  LOGIN_OK
  PROGRESS|done|total|saved|cards
  DONE|json摘要
  ERROR|訊息
"""
import sys
import json
import time
import random
from pathlib import Path

import httpx

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
PROFILE_DIR = BASE / "browser-profile"
COLLECT_JS = (BASE / "collect.js").read_text(encoding="utf-8")
URL = "https://agent.foundi.info/tool/property/list"
DATA_JSON = BASE / "data.json"
STATE_BACKUP = BASE / "state-auto.json"
SEEN_JSON = BASE / "seen.json"
KEIS_ENV = Path.home() / "OneDrive" / "桌面" / "keis" / ".env"   # 跟 591-ad/keis.py 同一份帳密
KEIS_API = "https://keis.kshouse.com.tw/api/v1"


class Stop(Exception):
    """KEIS 說不要再來了（429／登入失敗）：整趟停，不走「失敗再試」"""


class Keis:
    """collect.js 的 window.keisLookup 背後這支：拿房地卡片摘要去 KEIS houses/public 找同一戶。

    要溫和（使用者 10-19 特別交代別對 KEIS 造成負擔）：一次只送一個、每筆間隔隨機 2~4 秒、
    只查新卡片（舊的 collect.js 沿用上次結果）。401 重登一次；其他錯誤連續 3 次就回 fatal，
    collect.js 收到會整趟停手，不重試硬打。人在 KEIS 頁面按一次「查詢」就是 6 個請求，這邊一張卡 1 個。
    """

    def __init__(self):
        self.c = None
        self.last = 0.0
        self.fails = 0
        self.dead = ""
        self.n = 0
        self.cache = {}  # 同一趟裡條件一模一樣的查詢只打一次（同一間常同時出現在好幾個客需）

    def _login(self):
        env = {}
        for line in KEIS_ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
        self.c = httpx.Client(timeout=30, headers={"user-agent": "Mozilla/5.0",
                                                   "referer": "https://keis.kshouse.com.tw/case"})
        r = self.c.post(KEIS_API + "/auth/login", params={"device_type": "desktop"},
                        data={"username": env["KEIS_USERNAME"], "password": env["KEIS_PASSWORD"]})
        if r.status_code != 200:
            # 登入失敗不重試（密碼錯、被擋、限流重登只會更糟；10-21 就是一直重登被 429）
            raise Stop("KEIS 登入失敗 HTTP %d，整趟停手不重試" % r.status_code)
        self.c.headers["authorization"] = "Bearer " + r.json()["access_token"]

    def lookup(self, q):
        if self.dead:
            return {"fatal": self.dead}
        ck = json.dumps(q or {}, sort_keys=True, ensure_ascii=False)
        if ck in self.cache:
            return self.cache[ck]
        wait = self.last + random.uniform(2, 4) - time.time()
        if wait > 0:
            time.sleep(wait)
        body = dict(q or {}, source_type="all", order_by="created_at", order_direction="desc",
                    limit=50, offset=0)  # 同一戶可能幾十家刊登（10-19 興安街一間公寓 40 筆），抓少了「另有 N 家」會算少
        try:
            if self.c is None:
                self._login()
            for attempt in (1, 2):
                r = self.c.post(KEIS_API + "/houses/public", json=body)
                if r.status_code == 429:
                    raise Stop("KEIS 回 429 限流，整趟停手不重試（10-21 規矩）")
                if r.status_code == 401:
                    if attempt == 2:  # 剛重登完還是 401：再登也沒用，別一張卡一次登入
                        raise Stop("KEIS 重登後還是 401，整趟停手")
                    self._login()
                    continue
                r.raise_for_status()
                break
            self.fails = 0
            self.n += 1
            keep = ("url", "title", "price", "unit_price", "type", "community", "store_name", "created_at",
                    "floor_start", "total_floors", "building_area", "land_area", "age")
            res = {"houses": [{k: h.get(k) for k in keep} for h in r.json().get("houses", []) if h.get("url")]}
            self.cache[ck] = res
            return res
        except Stop as e:
            self.dead = str(e)
            return {"fatal": self.dead}
        except Exception as e:
            self.fails += 1
            if self.fails >= 3 or isinstance(e, (FileNotFoundError, KeyError)):
                self.dead = "%s: %s" % (type(e).__name__, str(e)[:120])
                return {"fatal": self.dead}
            self.last = time.time()
            return self.lookup(q)  # 單次失敗：照節奏再試（連續 3 次就放棄）
        finally:
            self.last = time.time()


# 增量記錄跟著帳號走、不跟著電腦走：state（已看過的物件）和 seen.json（NEW 標記）存在 OneDrive 桌面，
# 家裡/公司兩台共用。否則另一台的記錄停在舊日期，會把一堆舊物件當新的全展開、燒光查詢額度（2026-10-15）。
def _sync_dir():
    for od in sorted(Path.home().glob("OneDrive*")):
        d = od / "桌面"
        if d.is_dir():
            sd = d / "買方配案資料"
            sd.mkdir(exist_ok=True)
            return sd
    return None


SYNC_DIR = _sync_dir()


def merge_states(a_json, b_json):
    """兩份 state 逐客需合併，同一客需取 at 較新的那份。"""
    def load(x):
        try:
            return (json.loads(x) or {}).get("demands", {}) if x else {}
        except Exception:
            return {}
    a, b = load(a_json), load(b_json)
    out = dict(a)
    for k, v in b.items():
        if k not in out or (v.get("at") or "") > (out[k].get("at") or ""):
            out[k] = v
    return json.dumps({"demands": out}, ensure_ascii=False)


def pull_seen():
    if SYNC_DIR and (SYNC_DIR / "seen.json").exists():
        src = SYNC_DIR / "seen.json"
        if not SEEN_JSON.exists() or src.stat().st_mtime > SEEN_JSON.stat().st_mtime:
            SEEN_JSON.write_bytes(src.read_bytes())
            out("STATUS|已從 OneDrive 同步 NEW 記錄")


def push_sync():
    if not SYNC_DIR:
        return
    try:
        if STATE_BACKUP.exists():
            (SYNC_DIR / "state-auto.json").write_bytes(STATE_BACKUP.read_bytes())
        if SEEN_JSON.exists():
            (SYNC_DIR / "seen.json").write_bytes(SEEN_JSON.read_bytes())
    except Exception as e:
        out("STATUS|⚠️ 同步到 OneDrive 失敗：%s" % e)

FULL = "--full" in sys.argv
ERRS_JS = "() => FDBM.R.out.filter(o => o.error).map(o => ({key: o.folder + '/' + o.client + '/' + o.demand, error: o.error}))"
# 每跑幾個客需就重整一次頁面：同一頁一路跑 57 個客需，renderer 會漲到 9GB、越跑越慢（10-05 實跑）。
# 重整就歸零；每個客需跑完 collect.js 就存進 localStorage，重整不會掉資料
BATCH = 10


def out(line):
    print(line, flush=True)


def page_state(page):
    """跟 collect.js 的 openPanel() 判斷方式一致，避免頁面上其他地方出現同樣文字造成誤判。"""
    try:
        return page.evaluate("""
        () => ({
          hasPassword: !!document.querySelector('input[type=password]'),
          hasTree: !!document.querySelector('mat-nested-tree-node'),
          hasToggle: [...document.querySelectorAll('button,div,span')]
            .some(e => e.textContent.trim()==='客需條件' && e.children.length<3),
        })
        """)
    except Exception:
        return None


def wait_logged_in(page, timeout_ms):
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        st = page_state(page)
        if st and not st["hasPassword"] and (st["hasTree"] or st["hasToggle"]):
            return True
        time.sleep(1.5)
    return False


def inject_and_run(page, opts):
    page.evaluate(COLLECT_JS)
    page.evaluate("(opts) => FDBM.run(opts)", opts)


def get_progress(page):
    return page.evaluate("() => (typeof FDBM==='undefined' ? null : FDBM.progress())")


def state_to_data(state_json):
    st = json.loads(state_json)
    demands = st.get("demands", {})
    out_list = []
    for key, d in demands.items():
        seg = key.split("/")
        out_list.append({
            "folder": d.get("folder") or (seg[0] if len(seg) > 0 else ""),
            "client": d.get("client") or (seg[1] if len(seg) > 1 else ""),
            "demand": d.get("demand") or "/".join(seg[2:]),
            "total": d.get("total"),
            "cards": d.get("cards", []),
            "items": d.get("items", []),
            "at": d.get("at", ""),
        })
    ats = sorted([o["at"] for o in out_list if o["at"]])
    return {
        "mode": "state",
        "out": out_list,
        "demands": len(out_list),
        "startedAt": ats[0] if ats else "",
        "finishedAt": ats[-1] if ats else "",
    }


def main():
    PROFILE_DIR.mkdir(exist_ok=True)
    pull_seen()
    opts = {"slow": 3}
    if FULL:
        opts["full"] = 1

    keis = Keis()
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False,
            # 不鎖死 viewport、固定縮放 1：Windows 文字大小 191% 時，鎖 1280x900 會讓頁面
            # 超出螢幕一半、Ctrl- 也縮不回來，LINE 登入 QR code 掃不到（2026-10-05 踩過）
            no_viewport=True,
            args=["--start-maximized", "--force-device-scale-factor=1"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        # 掛在 context 上，重整／換頁都還在；collect.js 看到 window.keisLookup 就不點開卡片
        context.expose_function("keisLookup", keis.lookup)

        out("STATUS|開啟房地物件頁…")
        page.goto(URL, wait_until="domcontentloaded")

        if not wait_logged_in(page, 8000):
            out("NEED_LOGIN")
            if not wait_logged_in(page, 600000):
                out("ERROR|等了 10 分鐘還沒登入，中止")
                context.close()
                return
        out("LOGIN_OK")
        if SYNC_DIR and not FULL and (SYNC_DIR / "state-auto.json").exists():
            try:
                cur = page.evaluate("() => localStorage.getItem('FDBM_STATE')")
                merged = merge_states(cur, (SYNC_DIR / "state-auto.json").read_text(encoding="utf-8"))
                page.evaluate("s => localStorage.setItem('FDBM_STATE', s)", merged)
                out("STATUS|已合併 OneDrive 上的增量記錄（%d 個客需）" % len(json.loads(merged)["demands"]))
            except Exception as e:
                out("STATUS|⚠️ 合併 OneDrive 記錄失敗：%s" % e)
        time.sleep(1.5)  # 剛登入完/剛載入完，給頁面穩定一下再注入，避免插在導覽中途

        def batch_opts(frm):
            return dict(opts, **{"from": frm, "to": frm + BATCH})

        start = 0
        out("STATUS|開始跑 collect.js…")
        inject_and_run(page, batch_opts(start))

        stall_retries = 0
        reload_retries = 0
        failed = []  # 失敗的客需 key：collect.js 只記在 R.out 不存檔，進度輪詢只看得到最後兩行 log 會漏掉
        last_saved = -1
        seen_notes = set()
        kstat = {"keisHit": 0, "keisMiss": 0, "fallback": 0}  # collect.js 每批 run() 會歸零，這邊累加
        base = {"saved": 0, "cards": 0}  # 同上，給 GUI 進度行用（不累加的話每批重整後又從 0 算）

        while True:
            # 不能用 time.sleep：sync Playwright 只有在呼叫 Playwright 時才會處理 keisLookup 回呼，
            # 睡著的那 4 秒 collect.js 的 KEIS 查詢會整個卡住
            try:
                page.wait_for_timeout(4000)
            except Exception:
                time.sleep(4)
            try:
                prog = get_progress(page)
            except Exception as e:
                reload_retries += 1
                if reload_retries > 8:
                    out("ERROR|頁面一直重整/失去連線，放棄：%s" % str(e)[:200])
                    context.close()
                    return
                out("STATUS|頁面重整了，重新注入腳本繼續…")
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                except Exception:
                    pass
                time.sleep(2)
                if not wait_logged_in(page, 30000):
                    out("STATUS|重整後畫面還沒就緒，再等等…")
                    continue
                inject_and_run(page, batch_opts(start))  # 從這批開頭重來；已存的客需會很快跳過
                continue

            if prog is None:
                continue

            # collect.js 的 note() 印出來：0/0 展開客需樹那段才看得到在做什麼（2026-10-05 第一次實跑，
            # 視窗只有一排「進度 0/0」，分不出是在展開還是卡死）
            for msg in prog.get("err") or []:
                if msg not in seen_notes:
                    seen_notes.add(msg)
                    out("STATUS|" + msg)

            if prog.get("saved", -1) != last_saved or True:
                out("PROGRESS|%d|%d|%d|%d" % (
                    start + prog.get("done", 0), prog.get("total", 0),  # done 是這一批內的計數
                    base["saved"] + prog.get("saved", 0), base["cards"] + prog.get("cards", 0),
                ))
                last_saved = prog.get("saved", -1)

            if not prog.get("running"):
                if prog.get("total", 0) == 0 and prog.get("done", 0) == 0:
                    stall_retries += 1
                    if stall_retries > 6:
                        out("ERROR|一直讀不到客需樹，放棄")
                        context.close()
                        return
                    out("STATUS|讀不到客需樹，稍等重試（%d/6）…" % stall_retries)
                    time.sleep(5)
                    inject_and_run(page, batch_opts(start))
                    continue
                stall_retries = 0
                for k in kstat:
                    kstat[k] += prog.get(k, 0)
                for k in base:
                    base[k] += prog.get(k, 0)
                for e in page.evaluate(ERRS_JS):
                    failed.append(e["key"])
                    out("STATUS|⚠️ 客需失敗：%s（%s）" % (e["key"], e["error"][:120]))
                start += BATCH
                if prog.get("stop") or start >= prog.get("total", 0):
                    break
                out("STATUS|重整頁面釋放記憶體，接著跑第 %d 個客需起…" % (start + 1))
                try:
                    page.reload(wait_until="domcontentloaded")
                except Exception:
                    pass
                if not wait_logged_in(page, 60000):
                    out("ERROR|重整後一分鐘還沒回到客需頁，中止（已跑完的客需都存了，下次會接著跑）")
                    context.close()
                    return
                time.sleep(1.5)
                inject_and_run(page, batch_opts(start))
                continue

        # 10-07 那趟 8 個客需默默沒存到、單獨重跑又全好 → 失敗的最後自動補跑一次
        if failed and not prog.get("stop"):
            out("STATUS|補跑剛才失敗的 %d 個客需…" % len(failed))
            try:
                page.reload(wait_until="domcontentloaded")
            except Exception:
                pass
            if wait_logged_in(page, 60000):
                time.sleep(1.5)
                inject_and_run(page, dict(opts, only=failed))
                while True:
                    try:
                        page.wait_for_timeout(4000)
                        p2 = get_progress(page)
                    except Exception:
                        break
                    if p2 and not p2.get("running") and p2.get("total"):
                        break
                for e in page.evaluate(ERRS_JS):
                    out("STATUS|⚠️ 補跑仍失敗：%s（%s）" % (e["key"], e["error"][:120]))
            else:
                out("STATUS|⚠️ 重整後回不到客需頁，沒補跑；失敗的客需下次會再跑")

        if keis.dead:
            out("STATUS|⚠️ KEIS 查不動停手了（%s），已跑完的客需都存了，下次會接著跑" % keis.dead)
        out("STATUS|KEIS 查了 %d 次：對到 %d 張卡、沒對到 %d 張（非永慶體系）、摘要不全改點開 %d 張" % (
            keis.n, kstat["keisHit"], kstat["keisMiss"], kstat["fallback"]))
        limit_hit = bool(prog.get("stop")) and bool(prog.get("limitText"))
        if limit_hit:
            out("STATUS|撞到查詢次數上限，停在 %d/%d，資料沒有損失，下次再接著跑" % (
                start - BATCH + prog.get("done", 0), prog.get("total", 0)))
        else:
            out("STATUS|全部跑完，%d/%d" % (prog.get("total", 0), prog.get("total", 0)))

        out("STATUS|匯出資料…")
        state_json = page.evaluate("() => localStorage.getItem('FDBM_STATE')")
        context.close()

    if not state_json:
        out("ERROR|localStorage 裡沒有資料，沒東西可以匯出")
        return

    STATE_BACKUP.write_text(state_json, encoding="utf-8")
    push_sync()  # 先存 state（發布失敗也不丟），發布後 seen.json 更新再存一次
    data = state_to_data(state_json)
    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # 只留網址一份（10-07 使用者決定不再產桌面「買方配案.html」）：upload() 自己用 data.json 產頁再發布
    out("STATUS|產生頁面並發布到網址…")
    try:
        from upload import upload
        url = upload()
        push_sync()
    except Exception as e:
        out("ERROR|發布失敗：%s（資料已存在 data.json，修好後跑 python upload.py 重發就好）" % e)
        return
    # 發布成功就把本機副本刪掉：真資料在 OneDrive（兩台共用），本機這幾份只在「發布失敗要重發」時有用。
    # 留著的話另一台跑過之後它就過時，10-24 Claude 讀了這裡 10-19 的 data.json 跟使用者雞同鴨講一輪。
    for f in (DATA_JSON, STATE_BACKUP, BASE / "dist" / "index.html"):
        try:
            f.unlink()
        except OSError:
            pass

    out("DONE|" + json.dumps({
        "demands": data["demands"],
        "items": sum(len(o["items"]) for o in data["out"]),
        "limitHit": limit_hit,
        "url": url,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
