#!/usr/bin/env python3
"""每天 08:10 自動跑房地/i智慧配案（預設 A買 整組），跑完推 LINE 總表。

用法（平常不用手動跑，Windows 工作排程會叫它）：
    python daily_run.py                 # 正式跑 A買 整組，跑完推 LINE
    python daily_run.py --group B買      # 換一組
    python daily_run.py --dry-run        # 不點分享連結（試跑）
    python daily_run.py --notify-test    # 只推一則測試訊息，確認 LINE 通得到

排程安裝：`powershell -ExecutionPolicy Bypass -File .\\install-daily-task.ps1`

設計重點（都是這個 repo 踩過的坑）：
1. **沒登入就中止並喊人**：房地沒有 .env 帳密可以自動重登，登入態掉了的話客需清單
   會是空的、整支腳本會「成功」地回報 0 筆。所以開跑前先驗房地＋i智慧登入態，
   不是登入狀態就推 LINE 叫人去登、當場中止，絕不靜靜撈到 0 筆。
2. **失敗一定要推**：不管是 Chrome 沒開、沒登入、還是中途炸掉，都推 LINE。
   沒有訊息＝排程根本沒跑（那是另一種要查的狀況），不會跟「跑了但沒東西」混在一起。
3. 門市 00:00~約 07:22 斷網，08:10 已恢復，所以推播送得出去。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

import buyer_match
import chrome_cdp
import foundi_need
import run_group_match
import seen_store

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "daily_run.log"


class _NullStream:
    """排程跑的是 pythonw.exe，沒有 console → sys.stdout/stderr 是 None。
    print() 遇到 None 會安靜跳過，但第三方套件（traceback、playwright）不見得都有防呆，
    一個 AttributeError 就會讓整支死在推 LINE 之前——那正是最不能沉默的時刻。"""

    def write(self, s):
        pass

    def flush(self):
        pass


if sys.stdout is None:
    sys.stdout = _NullStream()
if sys.stderr is None:
    sys.stderr = _NullStream()

try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
    # webhook 沿用搶單那支的 n8n endpoint（keis-grab），所以也讀 scripts/keis/.env，
    # 不用把同一條 URL 抄兩份。已經有值的不覆蓋（buyer-match 自己的 .env 優先）。
    load_dotenv(BASE_DIR.parent / "keis" / ".env", override=False)
except ImportError:  # dotenv 沒裝就只能靠系統環境變數
    pass


def webhook_url() -> str:
    return (
        os.environ.get("BUYER_MATCH_NOTIFY_WEBHOOK")
        or os.environ.get("KEIS_NOTIFY_WEBHOOK")
        or ""
    ).strip()


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass  # OneDrive 偶爾鎖檔，log 寫不進去不該害整批中止


def notify(text: str) -> bool:
    """推一則純文字到 LINE（走 n8n `keis-grab` webhook 的 event=alert 分支，
    那個分支就是「原封不動把 body.text 推出去」，不用另外開 workflow）。"""
    url = webhook_url()
    if not url:
        log("⚠ 沒設 BUYER_MATCH_NOTIFY_WEBHOOK / KEIS_NOTIFY_WEBHOOK，這次不推 LINE")
        return False
    try:
        r = httpx.post(url, json={"event": "alert", "text": text}, timeout=20)
        if r.status_code >= 400:
            log(f"⚠ LINE 通知被拒 HTTP {r.status_code}: {r.text[:120]}")
            return False
        log("📲 已推 LINE")
        return True
    except Exception as e:
        log(f"⚠ LINE 通知送不出去（斷網時屬正常）：{type(e).__name__}")
        return False


def build_report(group: str, summary: list, dry_run: bool, only_new: bool) -> str:
    """把總表壓成一則 LINE 訊息：先講總數，再逐筆列，失敗的獨立標出來。"""
    errors = [r for r in summary if r.error]
    hits = [r for r in summary if not r.error and r.hits > 0]
    total = sum(r.hits for r in summary if not r.error)
    customers = {r.customer for r in summary}

    head = f"🏠 房地/i智慧配案（{group}）{datetime.now():%m/%d %H:%M}\n"
    if only_new:
        new_total = sum(r.new or 0 for r in summary if not r.error)
        repriced_total = sum(r.repriced or 0 for r in summary if not r.error)
        skipped_total = sum(r.skipped or 0 for r in summary if not r.error)
        head += (
            f"{len(customers)} 位客戶／{len(summary)} 個客需\n"
            f"🆕 新案 {new_total} 筆"
            + (f"｜🔻 改價 {repriced_total} 筆" if repriced_total else "")
            + f"｜看過的略過 {skipped_total} 筆"
        )
    else:
        head += f"{len(customers)} 位客戶／{len(summary)} 個客需，命中 {total} 筆"
    if dry_run:
        head += "（試跑，沒有分享連結）"

    lines = [f"・{r.customer}／{r.need} → {r.text}" for r in hits[:30]]
    if len(hits) > 30:
        lines.append(f"…另有 {len(hits) - 30} 個客需有結果，詳見電腦上的 output 資料夾")
    body = "\n".join(lines) if lines else (
        "（今天沒有新案源，都是看過的）" if only_new else "（今天沒有任何客需命中新案源）"
    )

    tail = "\n📂 結果在門市電腦 桌面\\工具\\買方配案\\output"
    if errors:
        err_lines = "\n".join(f"・{r.customer}／{r.need}：{r.error}" for r in errors[:5])
        tail = f"\n⚠ {len(errors)} 個客需失敗：\n{err_lines}" + tail
    return f"{head}\n\n{body}{tail}"


async def run(args) -> int:
    ok, msg = chrome_cdp.ensure_cdp(timeout_sec=90)
    log(f"Chrome CDP：{msg}")
    if not ok:
        notify(f"❌ 房地/i智慧配案沒跑成\n原因：{msg}\n👉 請在門市電腦雙擊 open_real_chrome.bat 後手動再跑一次")
        return 2

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(buyer_match.CDP_URL)
        except Exception as e:
            log(f"連不到 CDP：{e}")
            notify(
                "❌ 房地/i智慧配案沒跑成\n"
                f"原因：連不到 Chrome 除錯埠 {buyer_match.CDP_PORT}\n"
                "👉 請在門市電腦雙擊 open_real_chrome.bat 後手動再跑一次"
            )
            return 2

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()

        # ① 房地登入態（沒有自動重登，只能喊人）
        foundi_page = await foundi_need.get_or_open_foundi_page(ctx)
        try:
            await foundi_need.ensure_logged_in(foundi_page)
            log("房地登入態 OK")
        except foundi_need.FoundiNotLoggedIn as e:
            log(f"房地沒登入：{e}")
            notify(
                "🔑 房地要重新登入，今天的配案沒跑\n"
                f"（{e}）\n"
                "👉 門市電腦 → 那個配案用的 Chrome 視窗 → 登入 agent.foundi.info，"
                "登好後雙擊桌面「房地i智慧配案」手動跑一次"
            )
            return 3

        # ② i智慧登入態（這支有 .env 帳密，ensure_search_page 會自己試著重登）
        ismart_page = buyer_match.get_or_open_page(ctx, "is.ycut.com.tw")
        if ismart_page is None:
            ismart_page = await ctx.new_page()
        try:
            await buyer_match.ensure_search_page(ismart_page)
            log("i智慧登入態 OK")
        except Exception as e:
            log(f"i智慧沒登入：{e}")
            notify(
                "🔑 i智慧要重新登入，今天的配案沒跑\n"
                f"（{e}）\n"
                "👉 門市電腦 → 那個配案用的 Chrome 視窗 → 登入 is.ycut.com.tw，"
                "登好後雙擊桌面「房地i智慧配案」手動跑一次"
            )
            return 3

        log(
            f"開始跑群組「{args.group}」（limit={args.limit}, dry_run={args.dry_run}, "
            f"only_new={args.only_new}）"
        )
        try:
            summary = await run_group_match.run_group(
                ctx,
                args.group,
                limit=args.limit,
                dry_run=args.dry_run,
                newest=args.newest,
                only_new=args.only_new,
            )
        except Exception as e:
            log(f"整批失敗：{type(e).__name__}: {e}")
            traceback.print_exc()
            notify(f"❌ 房地/i智慧配案跑到一半失敗\n原因：{type(e).__name__}: {e}\n👉 請到門市電腦手動跑一次看看")
            return 4

        if args.only_new:
            # 30 天沒再出現的紀錄清掉（案子早就下架了），檔案不會無限長大
            data = seen_store.load()
            removed = seen_store.prune(data)
            if removed:
                seen_store.save(data)
                log(f"清掉 {removed} 筆 30 天沒再出現的記憶")

        report = build_report(args.group, summary, args.dry_run, args.only_new)
        log("跑完：\n" + run_group_match.format_summary(args.group, summary))
        notify(report)
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="每天自動跑房地/i智慧配案並推 LINE")
    ap.add_argument("--group", default="A買", help="要跑的群組，預設 A買")
    ap.add_argument("--limit", type=int, default=15, help="每個客需在 i智慧 最多處理幾筆（預設 15）")
    ap.add_argument("--dry-run", action="store_true", help="不點分享連結（試跑用）")
    ap.add_argument(
        "--all", dest="only_new", action="store_false",
        help="輸出完整清單（預設只輸出上次沒出現過的＋總價變了的，記憶存 state/seen.json）",
    )
    ap.set_defaults(only_new=True)
    ap.add_argument(
        "--no-newest", dest="newest", action="store_false",
        help="改用總價低到高排序（預設是「上架新>舊」，每天跑要的是新案）",
    )
    ap.set_defaults(newest=True)
    ap.add_argument("--notify-test", action="store_true", help="只推一則測試訊息就結束")
    args = ap.parse_args()

    if args.notify_test:
        ok = notify(f"🔔 房地/i智慧配案：通知測試（{datetime.now():%m/%d %H:%M}）")
        sys.exit(0 if ok else 1)

    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
