# -*- coding: utf-8 -*-
"""
買方配案系統 — 無人值守收集器（雙擊視窗按鈕觸發用，不排程）

流程：開瀏覽器(獨立 profile，第一次要手動登入一次) → 注入 collect.js → FDBM.run()
→ 輪詢進度、遇到分頁重整/讀不到客需樹自動重試 → 跑完/撞上限就停 → 匯出 localStorage
→ 轉成 data.json → node build_page.js → 覆蓋桌面「買方配案.html」。

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
import shutil
import subprocess
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
DESKTOP_DIR = Path(r"C:\Users\user\OneDrive\桌面")
OUT_HTML = DESKTOP_DIR / "買方配案.html"
DATA_JSON = BASE / "data.json"
STATE_BACKUP = BASE / "state-auto.json"

FULL = "--full" in sys.argv


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
            viewport={"width": 1280, "height": 900},
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

        out("STATUS|開始跑 collect.js…")
        inject_and_run(page, opts)

        stall_retries = 0
        reload_retries = 0
        last_saved = -1

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
                inject_and_run(page, {"slow": 3})
                continue

            if prog is None:
                continue

            if prog.get("saved", -1) != last_saved or True:
                out("PROGRESS|%d|%d|%d|%d" % (
                    prog.get("done", 0), prog.get("total", 0),
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
                    inject_and_run(page, {"slow": 3})
                    continue
                break

        limit_hit = bool(prog.get("stop")) and bool(prog.get("limitText"))
        if limit_hit:
            out("STATUS|撞到查詢次數上限，停在 %d/%d，資料沒有損失，下次再接著跑" % (
                prog.get("done", 0), prog.get("total", 0)))
        else:
            out("STATUS|全部跑完，%d/%d" % (prog.get("done", 0), prog.get("total", 0)))

        out("STATUS|匯出資料…")
        state_json = page.evaluate("() => localStorage.getItem('FDBM_STATE')")
        context.close()

    if not state_json:
        out("ERROR|localStorage 裡沒有資料，沒東西可以匯出")
        return

    STATE_BACKUP.write_text(state_json, encoding="utf-8")
    data = state_to_data(state_json)
    DATA_JSON.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    out("STATUS|產生頁面…")
    try:
        r = subprocess.run(
            ["node", "build_page.js", "data.json", "buyer-match.html"],
            cwd=str(BASE), capture_output=True, text=True, timeout=60,
        )
        if r.returncode != 0:
            out("ERROR|build_page.js 失敗：%s" % (r.stderr or r.stdout)[:300])
            return
    except Exception as e:
        out("ERROR|build_page.js 執行失敗：%s" % e)
        return

    try:
        shutil.copy(BASE / "buyer-match.html", OUT_HTML)
    except Exception as e:
        out("ERROR|複製到桌面失敗：%s（頁面還在 %s）" % (e, BASE / "buyer-match.html"))
        return

    out("DONE|" + json.dumps({
        "demands": data["demands"],
        "items": sum(len(o["items"]) for o in data["out"]),
        "limitHit": limit_hit,
        "path": str(OUT_HTML),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
