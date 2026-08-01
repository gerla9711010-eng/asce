#!/usr/bin/env python3
"""買方配案（房地客需 → i智慧即時案源）：房地負責「客戶要哪個範圍」，i智慧負責「現在真的有什麼」。

用法：
    python run_customer_match.py 采儒                    # 用她底下第一個子條件
    python run_customer_match.py 采儒 --need 文化中心周圍   # 指定子條件
    python run_customer_match.py 采儒 --need 文化中心周圍 --limit 10 --dry-run

第一次用之前，同一個 CDP Chrome（open_real_chrome.bat 開的那個、port 9223）除了原本
登入的 i智慧，**還要手動登入一次房地**（agent.foundi.info）——跟當初設定 i智慧一樣，
登入態會記住，之後不用再登。

流程：
    1. 房地：找到指定客戶的客需條件 → 讀候選清單，抽出社區/路名關鍵字（去重）
       + 讀存好的總價/房數/用途篩選（能抓多少算多少，抓不到就不篩那項）
    2. i智慧：逐個關鍵字現查，命中的開詳情頁抓專員聯絡方式＋分享連結
    3. 用「社區/路名＋樓層＋坪數＋總價」這組指紋去重（同一戶被多店委託只留一筆代表，
       其餘店的聯絡方式附註在同一筆底下，不會給客戶重複的分享連結）
    4. 輸出：印出來、存檔、複製到剪貼簿——跟 buyer_match.py 單獨跑的輸出格式一樣
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from playwright.async_api import async_playwright

import buyer_match
import foundi_need


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

        need = await foundi_need.load_customer_need(ctx, args.customer, args.need)
        if not need.areas:
            print("[INFO] 房地那邊這個客需沒有任何候選物件，沒東西可以拿去 i智慧 查")
            return

        areas = need.areas
        if args.limit_areas:
            areas = areas[: args.limit_areas]
            print(f"[INFO] --limit-areas 生效，只用前 {len(areas)} 個關鍵字")

        # 總價/房數/用途 CLI 給的優先，沒給才用房地讀到的；地理範圍（行政區）／
        # 屋齡/坪數/頂樓/車位這些一律照房地存的條件，不開放 CLI 覆蓋——
        # 使用者明講「房地怎麼設定條件，i智慧就要怎麼找」，開放覆蓋會違反這個原則。
        price_min = args.price_min if args.price_min is not None else need.price_min
        price_max = args.price_max if args.price_max is not None else need.price_max
        rooms_min = args.rooms_min if args.rooms_min is not None else need.rooms_min
        usage_any = [args.usage] if args.usage is not None else (need.usage_words or None)

        print(f"[INFO] 帶去 i智慧 查的關鍵字：{'、'.join(areas)}")
        print(f"[INFO] 行政區：{'、'.join(need.districts) or '不限'}")
        print(
            f"[INFO] 篩選條件：總價 {price_min or '不限'}~{price_max or '不限'}萬、"
            f"{rooms_min or '不限'}房以上、{need.baths_min or '不限'}衛以上、用途 {usage_any or ['不限']}、"
            f"屋齡 {need.age_min or '不限'}~{need.age_max or '不限'}年、"
            f"主建物 {need.main_area_ping_min or '不限'}~{need.main_area_ping_max or '不限'}坪、"
            f"土地 {need.land_ping_min or '不限'}~{need.land_ping_max or '不限'}坪、"
            f"樓層 {need.floor_min or '不限'}~{need.floor_max or '不限'}樓、"
            f"單價 {need.unit_price_min or '不限'}~{need.unit_price_max or '不限'}萬/坪、"
            f"{'不要頂樓、' if need.exclude_top_floor else ''}"
            f"{'需要有車位' if need.require_parking else '車位不限'}"
        )

        page = buyer_match.get_or_open_page(ctx, "is.ycut.com.tw")
        if page is None:
            page = await ctx.new_page()

        entries = await buyer_match.match_areas(
            page,
            areas,
            districts=need.districts or None,
            parking_mode="有" if need.require_parking else None,
            price_min=price_min,
            price_max=price_max,
            rooms_min=rooms_min,
            usage_any=usage_any,
            age_min=need.age_min,
            age_max=need.age_max,
            main_area_ping_min=need.main_area_ping_min,
            main_area_ping_max=need.main_area_ping_max,
            land_ping_min=need.land_ping_min,
            land_ping_max=need.land_ping_max,
            baths_min=need.baths_min,
            floor_min=need.floor_min,
            floor_max=need.floor_max,
            unit_price_min=need.unit_price_min,
            unit_price_max=need.unit_price_max,
            exclude_top_floor=need.exclude_top_floor,
            newest_first=args.newest,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        blocks = [
            buyer_match.format_block(card, agent, share_url) for card, agent, share_url in entries
        ]
        print(f"[INFO] 實際處理 {len(blocks)} 筆")
        label = (
            f"{args.customer}_{need.need_name}"
            .replace(",", "_").replace("/", "_").replace("\\", "_")
        )[:40]
        buyer_match.output_blocks(blocks, label)


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案：房地客需條件 → i智慧即時案源")
    ap.add_argument("customer", help="房地「客需條件」裡的客戶名字，例：采儒")
    ap.add_argument("--need", default=None, help="客戶底下的子條件名稱，例：文化中心周圍；不給就用第一個")
    ap.add_argument("--price-min", type=int, default=None, help="總價下限（萬），不給就用房地讀到的")
    ap.add_argument("--price-max", type=int, default=None, help="總價上限（萬），不給就用房地讀到的")
    ap.add_argument("--rooms-min", type=int, default=None, help="至少幾房，不給就用房地讀到的")
    ap.add_argument("--usage", default=None, help="用途關鍵字，不給就用房地讀到的")
    ap.add_argument("--limit", type=int, default=15, help="i智慧那邊最多處理幾筆詳情頁（預設 15）")
    ap.add_argument("--limit-areas", type=int, default=None, help="只用房地候選清單前 N 個關鍵字（除錯/先試跑用）")
    ap.add_argument(
        "--newest", action="store_true",
        help="i智慧改用「上架：新>舊」排序（預設是總價低到高）。想優先看新案、讓 🆕 標記浮上來就加這個",
    )
    ap.add_argument("--dry-run", action="store_true", help="開詳情頁抓專員資訊，但不點分享（除錯用）")
    args = ap.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
