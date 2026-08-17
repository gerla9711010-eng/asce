#!/usr/bin/env python3
"""買方配案：跑房地「客需條件」某個群組/客戶/子條件，逐一列出候選物件裡有永慶房屋
官網（buy.yungching.com.tw）連結的那幾戶。

用法：
    python run_yc_links.py A買                        # 整組全部跑
    python run_yc_links.py A買 B買 C買                  # 三組依序跑完
    python run_yc_links.py A買 --customer 采儒          # 只跑這組裡的某個客戶（全部子條件）
    python run_yc_links.py A買 --customer 采儒 --need 美術館   # 只跑單一子條件
    python run_yc_links.py A買 --limit 10               # 每個子條件最多查前 10 筆候選（預設 15）

第一次用之前：
    1. 雙擊桌面「買方配案」裡開真 Chrome 的捷徑（或手動用
       `--remote-debugging-port=9223 --user-data-dir=<見 chrome_cdp.profile_dir()>`
       開一個 Chrome），登入 agent.foundi.info 一次
    2. 這支會自動接上那個 Chrome（CDP），沒開著會自己開一個新的、等你登入

只做「查、印出來、存成 output/ 底下的文字檔」，不做去重記憶／LINE 推播／看板——
單純是抓永慶連結，其他批次基礎設施（`seen_store.py`／`manifest.py`／
`build_static_view.py`／`daily_run.py`）之後真的要接排程/通知再另外討論、另外做。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

import chrome_cdp
import foundi_need
import yc_link

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

# Windows 中文版終端機預設用 cp950，中文訊息／連結裡的字元不在這個字集裡時 print()
# 會亂碼甚至整支中斷——跟舊版 buyer_match.py 同一個修法。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


def _sanitize(name: str) -> str:
    return (
        name.replace(",", "_").replace("，", "_").replace("/", "_").replace("\\", "_")
    )[:60]


def _format_report(customer: str, need: str, results: list[yc_link.YcLinkResult]) -> str:
    found = [r for r in results if r.yc_link]
    lines = [f"客戶：{customer}／子條件：{need}", f"查了 {len(results)} 筆候選，找到 {len(found)} 筆永慶連結", ""]
    for r in results:
        if r.yc_link:
            lines.append(f"✅ {r.title}（{r.subtitle}）\n   {r.yc_link}")
        else:
            lines.append(f"・{r.title}（{r.subtitle}）→ {r.note or '沒有永慶連結'}")
    return "\n".join(lines)


async def _connect_ctx(p):
    ok, msg = chrome_cdp.ensure_cdp()
    print(f"[INFO] CDP Chrome：{msg}")
    if not ok:
        print(
            f"[ERROR] {msg}\n"
            "請確認 Chrome 有裝在預設路徑，或已有一個 Chrome 開著把 9223 佔用掉了。",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        browser = await p.chromium.connect_over_cdp(chrome_cdp.CDP_URL)
    except Exception as e:
        print(f"[ERROR] 連不到 {chrome_cdp.CDP_URL}：{e}", file=sys.stderr)
        sys.exit(1)
    return browser.contexts[0] if browser.contexts else await browser.new_context()


async def run_customer_need(ctx, customer: str, need: str, limit: int) -> list[yc_link.YcLinkResult]:
    fneed = await foundi_need.load_customer_need(ctx, customer, need)
    if fneed.candidate_count == 0:
        print("[INFO] 這個子條件沒有任何候選物件，跳過")
        return []
    page = await foundi_need.get_or_open_foundi_page(ctx)
    return await yc_link.collect_yc_links(page, max_candidates=limit)


async def run_group(ctx, group: str, customer: str | None, need: str | None, limit: int) -> None:
    foundi_page = await foundi_need.get_or_open_foundi_page(ctx)
    customers = await foundi_need.list_group(foundi_page, group)

    if customer:
        customers = [(name, needs) for name, needs in customers if name == customer]
        if not customers:
            raise RuntimeError(f"群組「{group}」裡找不到客戶「{customer}」")
        if need:
            customers = [(name, [n for n in needs if n == need]) for name, needs in customers]
            customers = [(name, needs) for name, needs in customers if needs]
            if not customers:
                raise RuntimeError(f"客戶「{customer}」底下找不到子條件「{need}」")

    total_jobs = sum(len(needs) for _, needs in customers)
    print(f"[INFO] 群組「{group}」共 {len(customers)} 位客戶、{total_jobs} 個客需子條件要跑")

    OUTPUT_DIR.mkdir(exist_ok=True)
    job_no = 0
    for cust, needs in customers:
        for n in needs:
            job_no += 1
            print(f"\n[INFO] ({job_no}/{total_jobs}) 客戶「{cust}」／子條件「{n}」")
            try:
                results = await run_customer_need(ctx, cust, n, limit)
            except Exception as e:
                print(f"[WARN] 這個子條件失敗，跳過：{e}", file=sys.stderr)
                continue

            if not results:
                continue

            report = _format_report(cust, n, results)
            print(report)

            found = sum(1 for r in results if r.yc_link)
            out_path = (
                OUTPUT_DIR
                / f"{datetime.now():%Y%m%d_%H%M%S}_{_sanitize(cust)}_{_sanitize(n)}_yc.txt"
            )
            out_path.write_text(report, encoding="utf-8")
            print(f"[INFO] 已存檔：{out_path}（找到 {found} 筆永慶連結）")


async def main_async(args) -> None:
    async with async_playwright() as p:
        ctx = await _connect_ctx(p)

        foundi_page = await foundi_need.get_or_open_foundi_page(ctx)
        try:
            await foundi_need.ensure_logged_in(foundi_page)
            print("[INFO] 房地登入態 OK")
        except foundi_need.FoundiNotLoggedIn as e:
            print(f"[ERROR] {e}\n請在剛才開起來的 Chrome 視窗登入 agent.foundi.info 後再跑一次", file=sys.stderr)
            sys.exit(3)

        for group in args.group:
            print("\n" + "=" * 40)
            print(f"[INFO] 開始跑群組「{group}」")
            try:
                await run_group(ctx, group, args.customer, args.need, args.limit)
            except RuntimeError as e:
                print(f"[WARN] 群組「{group}」整組失敗，跳過：{e}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案：抓候選物件裡的永慶房屋官網連結")
    ap.add_argument("group", nargs="+", help="房地「客需條件」裡的群組名稱，例：A買、B買、C買、其他")
    ap.add_argument("--customer", default=None, help="只跑這組裡的某個客戶（全部子條件）")
    ap.add_argument("--need", default=None, help="只跑指定子條件（要搭配 --customer）")
    ap.add_argument(
        "--limit", type=int, default=yc_link.DEFAULT_MAX_CANDIDATES,
        help=f"每個子條件最多查前幾筆候選（預設 {yc_link.DEFAULT_MAX_CANDIDATES}，候選多時逐筆點開查很慢）",
    )
    args = ap.parse_args()

    if args.need and not args.customer:
        ap.error("--need 要搭配 --customer 一起用")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
