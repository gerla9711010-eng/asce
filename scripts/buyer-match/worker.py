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
from pathlib import Path

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
    opts = {"slow": 3}
    if FULL:
        opts["full"] = 1

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False,
            # 不鎖死 viewport、固定縮放 1：Windows 文字大小 191% 時，鎖 1280x900 會讓頁面
            # 超出螢幕一半、Ctrl- 也縮不回來，LINE 登入 QR code 掃不到（2026-10-05 踩過）
            no_viewport=True,
            args=["--start-maximized", "--force-device-scale-factor=1"],
        )
        page = context.pages[0] if context.pages else context.new_page()

        out("STATUS|開啟房地物件頁…")
        page.goto(URL, wait_until="domcontentloaded")

        if not wait_logged_in(page, 8000):
            out("NEED_LOGIN")
            if not wait_logged_in(page, 600000):
                out("ERROR|等了 10 分鐘還沒登入，中止")
                context.close()
                return
        out("LOGIN_OK")
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

        while True:
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
                    prog.get("saved", 0), prog.get("cards", 0),
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
                    time.sleep(4)
                    try:
                        p2 = get_progress(page)
                    except Exception:
                        break
                    if p2 and not p2.get("running") and p2.get("total"):
                        break
                for e in page.evaluate(ERRS_JS):
                    out("STATUS|⚠️ 補跑仍失敗：%s（%s）" % (e["key"], e["error"][:120]))
            else:
                out("STATUS|⚠️ 重整後回不到客需頁，沒補跑；失敗的客需下次會再跑")

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
    data = state_to_data(state_json)
    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # 只留網址一份（10-07 使用者決定不再產桌面「買方配案.html」）：upload() 自己用 data.json 產頁再發布
    out("STATUS|產生頁面並發布到網址…")
    try:
        from upload import upload
        url = upload()
    except Exception as e:
        out("ERROR|發布失敗：%s（資料已存在 data.json，修好後跑 python upload.py 重發就好）" % e)
        return

    out("DONE|" + json.dumps({
        "demands": data["demands"],
        "items": sum(len(o["items"]) for o in data["out"]),
        "limitHit": limit_hit,
        "url": url,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
