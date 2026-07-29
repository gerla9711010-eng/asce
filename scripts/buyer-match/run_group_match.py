#!/usr/bin/env python3
"""買方配案（整組批次）：跑完房地「客需條件」某個群組（A買/B買/C買/其他）底下
所有客戶、每個客戶存的每一個子條件，逐一去 i智慧 現查、各自存檔。

用法：
    python run_group_match.py A買                       # 整組全部跑
    python run_group_match.py A買 --customer 采儒         # 只跑這組裡的某個客戶（全部子條件）
    python run_group_match.py A買 --dry-run --limit 5     # 先小規模試跑，不點分享連結

跟 `run_customer_match.py`（單一客戶單一子條件）差在這支會自己迴圈整組，每個
「客戶/子條件」各自存一個檔在 output/，跑完印一張總表（誰有幾筆命中、誰失敗）。
第一次用之前的設定（CDP Chrome、i智慧＋房地登入）跟 `run_customer_match.py` 一樣，
見 README。

⚠️ 一整組可能有好幾十個「客戶 × 子條件」組合，每組都要逐關鍵字查 i智慧 + 開詳情頁，
真的跑完可能要幾十分鐘。建議先用 `--dry-run --limit 5` 抓時間感、確認沒有奇怪的
客戶/子條件名稱撞到選擇器問題，再拿掉限制跑正式的。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright

import buyer_match
import foundi_need


async def run_group(
    ctx,
    group: str,
    customer: Optional[str] = None,
    limit: int = 15,
    dry_run: bool = False,
    newest: bool = False,
) -> list[tuple[str, str, str]]:
    """跑完一個群組（可限定單一客戶），回傳 [(客戶, 子條件, 結果文字)] 總表。

    ctx 是已經連上的 CDP context——CLI（下面的 run）跟排程（daily_run.py）各自
    處理連線/登入檢查，這裡只負責迴圈本身，兩邊行為保證一致。
    """
    foundi_page = await foundi_need.get_or_open_foundi_page(ctx)
    customers = await foundi_need.list_group(foundi_page, group)
    if customer:
        customers = [(name, needs) for name, needs in customers if name == customer]
        if not customers:
            raise RuntimeError(f"群組「{group}」裡找不到客戶「{customer}」")

    total_jobs = sum(len(needs) for _, needs in customers)
    print(f"[INFO] 群組「{group}」共 {len(customers)} 位客戶、{total_jobs} 個客需子條件要跑")

    i智慧_page = buyer_match.get_or_open_page(ctx, "is.ycut.com.tw")
    if i智慧_page is None:
        i智慧_page = await ctx.new_page()

    summary: list[tuple[str, str, str]] = []  # (customer, need, result_text)
    job_no = 0
    for cust, needs in customers:
        for need in needs:
            job_no += 1
            print(f"\n[INFO] ({job_no}/{total_jobs}) 客戶「{cust}」／子條件「{need}」")
            try:
                fneed = await foundi_need.load_customer_need(ctx, cust, need)
            except RuntimeError as e:
                print(f"[WARN] 讀房地客需失敗，跳過：{e}", file=sys.stderr)
                summary.append((cust, need, f"錯誤：{e}"))
                continue

            if not fneed.areas:
                print("[INFO] 這個子條件沒有任何候選物件，跳過")
                summary.append((cust, need, "0 筆候選"))
                continue

            try:
                entries = await buyer_match.match_areas(
                    i智慧_page,
                    fneed.areas,
                    districts=fneed.districts or None,
                    parking_mode="有" if fneed.require_parking else None,
                    price_min=fneed.price_min,
                    price_max=fneed.price_max,
                    rooms_min=fneed.rooms_min,
                    usage_any=fneed.usage_words or None,
                    age_min=fneed.age_min,
                    age_max=fneed.age_max,
                    main_area_ping_min=fneed.main_area_ping_min,
                    main_area_ping_max=fneed.main_area_ping_max,
                    land_ping_min=fneed.land_ping_min,
                    land_ping_max=fneed.land_ping_max,
                    baths_min=fneed.baths_min,
                    floor_min=fneed.floor_min,
                    floor_max=fneed.floor_max,
                    unit_price_min=fneed.unit_price_min,
                    unit_price_max=fneed.unit_price_max,
                    exclude_top_floor=fneed.exclude_top_floor,
                    newest_first=newest,
                    limit=limit,
                    dry_run=dry_run,
                )
            except Exception as e:
                print(f"[WARN] 查 i智慧 失敗，跳過：{e}", file=sys.stderr)
                summary.append((cust, need, f"錯誤：{e}"))
                continue

            blocks = [
                buyer_match.format_block(card, agent, share_url)
                for card, agent, share_url in entries
            ]
            summary.append((cust, need, f"{len(blocks)} 筆"))

            if blocks:
                label = f"{cust}_{need}".replace(",", "_").replace("，", "_")[:60]
                buyer_match.OUTPUT_DIR.mkdir(exist_ok=True)
                out_path = (
                    buyer_match.OUTPUT_DIR
                    / f"{datetime.now():%Y%m%d_%H%M%S}_{label}.txt"
                )
                out_path.write_text("\n\n".join(blocks), encoding="utf-8")
                print(f"[INFO] 已存檔：{out_path}")

    return summary


def format_summary(group: str, summary: list[tuple[str, str, str]]) -> str:
    return "\n".join(f"客戶：{c}／{n} → {r}" for c, n, r in summary)


async def run(args) -> None:
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(buyer_match.CDP_URL)
        except Exception:
            print(
                f"[ERROR] 連不到 {buyer_match.CDP_URL}。\n"
                "請先雙擊 open_real_chrome.bat 開瀏覽器（i智慧、房地都要先手動登入過），"
                "確認視窗開著之後再重跑這支腳本。",
                file=sys.stderr,
            )
            sys.exit(1)

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()

        try:
            summary = await run_group(
                ctx,
                args.group,
                customer=args.customer,
                limit=args.limit,
                dry_run=args.dry_run,
                newest=args.newest,
            )
        except RuntimeError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)

        print("\n" + "=" * 40)
        print(f"群組「{args.group}」跑完，共 {len(summary)} 個客需子條件：\n")
        report = format_summary(args.group, summary)
        print(report)

        try:
            import pyperclip

            pyperclip.copy(report)
            print("\n[INFO] 總表已複製到剪貼簿")
        except Exception as e:
            print(f"[WARN] 複製到剪貼簿失敗（總表仍在上面）：{e}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案：批次跑房地某個群組底下全部客戶的客需")
    ap.add_argument("group", help="房地「客需條件」裡的群組名稱，例：A買、B買、C買、其他")
    ap.add_argument("--customer", default=None, help="只跑這組裡的某個客戶（全部子條件），不給就整組跑")
    ap.add_argument("--limit", type=int, default=15, help="每個客需子條件在 i智慧 最多處理幾筆（預設 15）")
    ap.add_argument("--dry-run", action="store_true", help="開詳情頁抓專員資訊，但不點分享（除錯/試跑用）")
    ap.add_argument(
        "--newest", action="store_true",
        help="i智慧改用「上架：新>舊」排序（預設是總價低到高）。想優先看新案、讓 🆕 標記浮上來就加這個",
    )
    args = ap.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
