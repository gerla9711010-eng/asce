#!/usr/bin/env python3
"""
永慶博愛凱璿 房管系統 (hq.houseol.com.tw) 自動簽到

每天在 9:00–10:00 之間（由 Windows 工作排程器隨機延遲觸發）自動到「差勤系統」點
【確認】簽到，然後把結果 POST 到 n8n webhook 推 LINE 回報。

⚠️ 差勤面板預設選的是【簽退】(value=1)，不是簽到！本腳本一定會先勾【簽到】
   (value=0) 再按確認，避免把自己簽退。

登入方式：用一個「專用」Chrome 設定檔 (persistent profile) 保存登入狀態，
不把帳密寫進腳本。session 過期時會 LINE 通知你重新登入，不會默默失敗。

用法:
    python clockin.py --login     # 一次性：開瀏覽器讓你手動登入 houseol，登入狀態存進專用設定檔
    python clockin.py --dry-run   # 演練：開頁、確認有登入、找到簽到鈕，但「不」真的送出
    python clockin.py             # 正式：勾簽到→按確認→驗證→推 LINE（工作排程器跑這個）

選項:
    --jitter N   送出前先隨機睡 0~N 秒（不規則化用；若已用工作排程器 RandomDelay 可不加）

環境變數（.env）:
    CLOCKIN_NOTIFY_WEBHOOK   n8n webhook URL（設了才推 LINE）
    CLOCKIN_HEADLESS         1=無視窗(預設)，0=顯示視窗（除錯用；--login 一律顯示視窗）
"""

import argparse
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

load_dotenv()

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

CLOCKIN_URL = "https://hq.houseol.com.tw/index.asp?module=main&file=clockin"
RECORD_URL = "https://hq.houseol.com.tw/index.asp?module=LogEmp&file=Log2"

HERE = Path(__file__).parent
PROFILE_DIR = HERE / "profile"          # 專用 Chrome 設定檔（登入狀態存這；不進 git）
LOG_FILE = HERE / "clockin.log"

NOTIFY_WEBHOOK = os.environ.get("CLOCKIN_NOTIFY_WEBHOOK", "").strip()
HEADLESS_ENV = os.environ.get("CLOCKIN_HEADLESS", "1").strip() != "0"

# 簽到 = value 0；簽退 = value 1（頁面預設竟然是簽退，務必先勾簽到）
SIGN_IN_RADIO = 'input[type=radio][name="LoginType"][value="0"]'
# 確認鈕是 <a>文字「確 認」（中間有空白），用 xpath 去掉空白比對
CONFIRM_XPATH = "xpath=//a[translate(normalize-space(.), ' 　', '')='確認']"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    try:
        with LOG_FILE.open("a", encoding="utf-8-sig") as f:
            f.write(line + "\n")
    except Exception:
        pass


def notify(ok: bool, detail: str = "", clock_time: str = "") -> None:
    """推 LINE。webhook 沒設就只印。"""
    if not NOTIFY_WEBHOOK:
        log(f"[notify skipped, no webhook] ok={ok} time={clock_time} {detail}")
        return
    try:
        httpx.post(
            NOTIFY_WEBHOOK,
            json={"event": "clockin", "ok": ok, "time": clock_time, "detail": detail},
            timeout=20,
        )
        log("[notify] LINE 已送出")
    except Exception as e:
        log(f"[notify FAILED] {e}")


def open_context(p, headless: bool):
    return p.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1280, "height": 800},
        locale="zh-TW",
    )


def is_logged_in(page) -> bool:
    """簽到面板出現 = 有登入；被導去登入頁（有密碼欄）= 沒登入。"""
    try:
        page.wait_for_selector(SIGN_IN_RADIO, timeout=8000)
        return True
    except PWTimeout:
        return False


def do_login() -> None:
    """開一個有畫面的瀏覽器，讓使用者手動登入 houseol，登入狀態會存進 PROFILE_DIR。"""
    print("=" * 60)
    print("即將開啟瀏覽器。請在裡面登入 houseol 房管系統，")
    print("看到『差勤系統』簽到畫面後，回這個視窗按 Enter 完成設定。")
    print("（登入狀態會存進 scripts/clockin/profile，之後排程就用它）")
    print("=" * 60)
    with sync_playwright() as p:
        ctx = open_context(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(CLOCKIN_URL, wait_until="domcontentloaded")
        input("登入完成後按 Enter…")
        if is_logged_in(page):
            log("[login] 偵測到簽到面板，登入狀態已儲存 ✅")
        else:
            log("[login] ⚠️ 沒偵測到簽到面板，可能還沒登入成功，請重跑 --login")
        ctx.close()


def run(dry_run: bool, jitter: int) -> int:
    if jitter > 0:
        s = random.randint(0, jitter)
        log(f"[jitter] 隨機延遲 {s} 秒後動作")
        time.sleep(s)

    headless = HEADLESS_ENV
    with sync_playwright() as p:
        ctx = open_context(p, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 捕捉並自動關掉任何 alert/confirm 對話框，記下訊息（多半是「簽到成功」之類）
        dialog_msgs: list[str] = []

        def on_dialog(d):
            dialog_msgs.append(d.message)
            try:
                d.accept()
            except Exception:
                pass

        page.on("dialog", on_dialog)

        page.goto(CLOCKIN_URL, wait_until="domcontentloaded")

        if not is_logged_in(page):
            ctx.close()
            log("[run] ⚠️ 未登入（session 可能過期）")
            notify(False, "登入過期，請在店裡電腦跑 `python clockin.py --login` 重新登入")
            return 2

        # 一定先勾【簽到】(value=0)，別誤按到預設的簽退
        page.check(SIGN_IN_RADIO)
        log("[run] 已選【簽到】")

        confirm = page.locator(CONFIRM_XPATH).first
        if confirm.count() == 0:
            ctx.close()
            log("[run] ⚠️ 找不到確認鈕")
            notify(False, "頁面上找不到【確認】鈕，版面可能改了")
            return 3

        now = datetime.now().strftime("%H:%M")

        if dry_run:
            log(f"[dry-run] 一切就緒（已登入、已勾簽到、找到確認鈕）。"
                f"若正式執行會在 {now} 送出簽到。未真的送出。")
            ctx.close()
            return 0

        # 正式：按確認
        confirm.click()
        log("[run] 已按【確認】，等待回應…")
        # 等對話框 / AJAX 反應
        for _ in range(10):
            page.wait_for_timeout(500)
            if dialog_msgs:
                break

        msg = " / ".join(dialog_msgs).strip()
        # 讀一下頁面現況（有些站是把結果寫在畫面上而非 alert）
        try:
            body_txt = page.inner_text("body")
        except Exception:
            body_txt = ""

        ctx.close()

        # 判斷成功：對話框或畫面含「成功 / 已簽 / OK」等；含「失敗 / 錯誤」則失敗
        blob = (msg + " " + body_txt)
        fail_words = ["失敗", "錯誤", "重複", "已經簽退", "不可"]
        ok_words = ["成功", "已簽到", "簽到成功", "完成", "OK"]
        is_fail = any(w in blob for w in fail_words) and not any(w in (msg or "") for w in ok_words)
        ok = (any(w in blob for w in ok_words) or bool(msg)) and not is_fail

        detail = msg if msg else "（無對話框訊息，請看 LINE 內容或到記錄查詢確認）"
        log(f"[run] 結果 ok={ok} 訊息={detail!r}")
        notify(ok, detail, clock_time=now)
        return 0 if ok else 4


def main():
    ap = argparse.ArgumentParser(description="houseol 自動簽到")
    ap.add_argument("--login", action="store_true", help="一次性：手動登入並存進專用設定檔")
    ap.add_argument("--dry-run", action="store_true", help="演練，不真的送出簽到")
    ap.add_argument("--jitter", type=int, default=0, help="送出前隨機睡 0~N 秒")
    args = ap.parse_args()

    if not PROFILE_DIR.exists() and not args.login:
        log("⚠️ 還沒建立登入設定檔。請先跑：python clockin.py --login")
        sys.exit(1)

    if args.login:
        do_login()
        return

    sys.exit(run(dry_run=args.dry_run, jitter=args.jitter))


if __name__ == "__main__":
    main()
