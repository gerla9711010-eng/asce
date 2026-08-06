#!/usr/bin/env python3
"""每天 08:10 自動跑房地/i智慧配案（預設 A買→B買→C買 三組），跑完推 LINE 總表。

用法（平常不用手動跑，Windows 工作排程會叫它）：
    python daily_run.py                 # 正式跑 A買+B買+C買，跑完推 LINE
    python daily_run.py --group B買      # 只跑其中一組
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
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

import build_static_view
import buyer_match
import chrome_cdp
import foundi_need
import run_group_match
import seen_store

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "daily_run.log"

# 每天早上要跑的群組，一組跑完接著下一組（2026-08-05 從只跑 A買 改成三組都跑）。
# 房地「客需條件」底下還有「其他」之類的雜項資料夾，那些不是要配的買方名單，不跑。
DEFAULT_GROUPS = ("A買", "B買", "C買")


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


def build_report(
    results: list[tuple[str, list | None]], dry_run: bool, only_new: bool
) -> str:
    """把總表壓成一則 LINE 訊息：先講總數，再逐筆列，失敗的獨立標出來。

    `results` 是 [(群組名, 該組的 summary)]，整組跑不起來的那組 summary 是 None
    （例：群組名在房地找不到）——那種要單獨講，不能混在「沒命中」裡面。"""
    dead_groups = [g for g, s in results if s is None]
    summary = [r for _, s in results if s for r in s]
    group_label = "＋".join(g for g, _ in results)

    errors = [r for r in summary if r.error]
    hits = [r for r in summary if not r.error and r.hits > 0]
    total = sum(r.hits for r in summary if not r.error)
    customers = {r.customer for r in summary}

    head = f"🏠 房地/i智慧配案（{group_label}）{datetime.now():%m/%d %H:%M}\n"
    if only_new:
        new_total = sum(r.new or 0 for r in summary if not r.error)
        repriced_total = sum(r.repriced or 0 for r in summary if not r.error)
        skipped_total = sum((r.skipped or 0) + (r.raised or 0) for r in summary if not r.error)
        head += (
            f"{len(customers)} 位客戶／{len(summary)} 個客需\n"
            f"🆕 新案 {new_total} 戶"
            + (f"｜🔻 降價 {repriced_total} 戶" if repriced_total else "")
            + f"｜看過的略過 {skipped_total} 戶"
        )
    else:
        head += f"{len(customers)} 位客戶／{len(summary)} 個客需，命中 {total} 筆"
    if dry_run:
        head += "（試跑，沒有分享連結）"

    # 跑多組時逐筆列會分不出誰是哪一組，所以照組分段；總行數還是上限 30 行，
    # 免得 A買+B買+C買 一次擠出幾百行 LINE 訊息。
    lines: list[str] = []
    shown = 0
    for group, group_summary in results:
        if not group_summary:
            continue
        group_hits = [r for r in group_summary if not r.error and r.hits > 0]
        if not group_hits:
            continue
        if len(results) > 1:
            lines.append(f"【{group}】{len(group_hits)} 個客需有結果")
        for r in group_hits:
            if shown >= 30:
                break
            lines.append(f"・{r.customer}／{r.need} → {r.text}")
            shown += 1
    if len(hits) > shown:
        lines.append(f"…另有 {len(hits) - shown} 個客需有結果，詳見電腦上的 output 資料夾")
    body = "\n".join(lines) if lines else (
        "（今天沒有新案源，都是看過的）" if only_new else "（今天沒有任何客需命中新案源）"
    )

    tail = "\n📂 結果在門市電腦 桌面\\工具\\買方配案\\output"
    if errors:
        err_lines = "\n".join(f"・{r.customer}／{r.need}：{r.error}" for r in errors[:5])
        tail = f"\n⚠ {len(errors)} 個客需失敗：\n{err_lines}" + tail
    if dead_groups:
        tail = f"\n❌ 整組沒跑成：{'、'.join(dead_groups)}（詳見 daily_run.log）" + tail
    return f"{head}\n\n{body}{tail}"


# ── 開機觸發要的兩道保險（2026-08-05 加）─────────────────────────
# 排程改成「登入後 15 分鐘」也跑（早到就早跑完），08:10 那個保留當備援。
# 於是多出兩種以前不會發生的狀況，各補一道：
#   ① 門市 00:00~約 07:22 斷網：太早開機的話，一開跑什麼都連不到。以前這會被
#      當成「登入態掉了」推一則假的「🔑 房地要重新登入」，害人白掃一次 QR Code。
#      → 先等網路通再開始，而且斷網期間 LINE 本來也送不出去，安靜等就好。
#   ② 一天跑兩次：中午重開機會再觸發一次，白花兩小時又推一則重複的 LINE。
#      → 成功跑完就記下日期，同一天再被叫起來就直接跳過（--force 可略過這道）。
NET_PROBE_URL = "https://agent.foundi.info"
STATE_PATH = BASE_DIR / "state" / "daily_run_state.json"


def wait_for_network(max_wait_sec: int = 45 * 60, interval_sec: int = 60) -> bool:
    """等到連得上房地為止。回 False＝等到逾時還是不通（這種時候 LINE 也推不出去）。"""
    deadline = time.monotonic() + max_wait_sec
    attempt = 0
    while True:
        attempt += 1
        try:
            httpx.head(NET_PROBE_URL, timeout=10, follow_redirects=True)
            if attempt > 1:
                log(f"網路通了（等了 {attempt} 次）")
            return True
        except Exception as e:
            if time.monotonic() >= deadline:
                log(f"等了 {max_wait_sec // 60} 分鐘網路還是不通（{type(e).__name__}），這次不跑")
                return False
            if attempt == 1:
                log(f"連不到 {NET_PROBE_URL}（{type(e).__name__}）——門市半夜到約 07:22 斷網，等網路通再開始")
            time.sleep(interval_sec)


def already_ran_today() -> bool:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("last_success_date") == f"{datetime.now():%Y-%m-%d}"


def mark_ran_today() -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(
            json.dumps(
                {"last_success_date": f"{datetime.now():%Y-%m-%d}",
                 "finished_at": datetime.now().isoformat(timespec="seconds")},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError as e:
        # 記不起來最多是重開機時多跑一次，不該讓「已經跑完的這班」算失敗
        log(f"⚠ 當日紀錄寫不進去（{type(e).__name__}），重開機可能會重跑一次")


async def run(args) -> int:
    if not args.force and already_ran_today():
        log("今天已經跑完過一輪，這次跳過（要重跑就加 --force）")
        return 0

    if not wait_for_network():
        return 5

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

        # 一組一組接著跑（預設 A買→B買→C買）。某一組炸掉只記下來、繼續下一組——
        # 整批要跑好幾小時，不該因為第一組出問題就讓後面兩組整天沒資料。
        results: list[tuple[str, list | None]] = []
        for i, group in enumerate(args.group, 1):
            log(
                f"({i}/{len(args.group)}) 開始跑群組「{group}」（limit={args.limit}, "
                f"dry_run={args.dry_run}, only_new={args.only_new}）"
            )
            try:
                summary = await run_group_match.run_group(
                    ctx,
                    group,
                    limit=args.limit,
                    dry_run=args.dry_run,
                    newest=args.newest,
                    only_new=args.only_new,
                    on_result=lambda r: log(f"  ({r.customer}／{r.need}) → {r.text}"),
                )
            except Exception as e:
                log(f"群組「{group}」整組失敗：{type(e).__name__}: {e}")
                traceback.print_exc()
                results.append((group, None))
                continue
            results.append((group, summary))

        if all(s is None for _, s in results):
            notify(
                "❌ 房地/i智慧配案跑到一半失敗\n"
                f"原因：{'、'.join(g for g, _ in results)} 每一組都沒跑成（詳見 daily_run.log）\n"
                "👉 請到門市電腦手動跑一次看看"
            )
            return 4

        if args.only_new:
            # 30 天沒再出現的紀錄清掉（案子早就下架了），檔案不會無限長大
            data = seen_store.load()
            removed = seen_store.prune(data)
            if removed:
                seen_store.save(data)
                log(f"清掉 {removed} 筆 30 天沒再出現的記憶")

        # 重產單檔 HTML 看板（OneDrive 那份），跑完就是最新的，不用人再手動產一次。
        # 包 try：看板產不出來不該讓「配案本身跑成功了」變成失敗，頂多是看板停在舊資料。
        try:
            build_static_view.build(build_static_view.DEFAULT_OUT, "standalone")
            log("已更新看板 HTML")
        except Exception as e:
            log(f"⚠ 看板 HTML 更新失敗（配案結果不受影響）：{type(e).__name__}: {e}")

        report = build_report(results, args.dry_run, args.only_new)
        for group, summary in results:
            if summary:
                log(f"「{group}」跑完：\n" + run_group_match.format_summary(group, summary))
        if not args.dry_run:
            mark_ran_today()
        notify(report)
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="每天自動跑房地/i智慧配案並推 LINE")
    ap.add_argument(
        "--group", nargs="+", default=list(DEFAULT_GROUPS),
        help=f"要跑的群組，可給多個，預設 {' '.join(DEFAULT_GROUPS)}（依序跑完）",
    )
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
    ap.add_argument(
        "--force", action="store_true",
        help="今天已經跑過也照跑（排程開機那班跟 08:10 那班共用「一天一次」的鎖）",
    )
    ap.add_argument("--notify-test", action="store_true", help="只推一則測試訊息就結束")
    args = ap.parse_args()

    if args.notify_test:
        ok = notify(f"🔔 房地/i智慧配案：通知測試（{datetime.now():%m/%d %H:%M}）")
        sys.exit(0 if ok else 1)

    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
