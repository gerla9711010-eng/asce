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

跑完會存成 output/ 底下的文字檔，也會把整輪結果寫成 output/latest_run.json、
呼叫 `build_static_view.py` 重產看板 HTML、預設自動部署到 Cloudflare Pages
（`--no-publish` 關掉最後這步，只留本機檔案）。會用 `seen_store.py` 記住每個
客戶/子條件之前看過哪些連結，重跑只標「這次新出現」的（🆕），不會漏掉已看過的
舊案子（只是不特別標新）。不做 LINE 推播、不排程——手動跑一次是一次，排程/通知
之後真的要接再另外討論、另外做。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

import build_static_view
import chrome_cdp
import foundi_need
import seen_store
import yc_link

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
RUN_JSON_PATH = OUTPUT_DIR / "latest_run.json"

# 部署用同一套 kh-market-tool 管線（yc-tools.pages.dev 專案），細節見
# docs/reference.md「公開網頁：Cloudflare Pages 發布鏈路」。
DEPLOY_SCRIPT = Path.home() / "kh-market-tool" / "update.py"

# Windows 中文版終端機預設用 cp950，中文訊息／連結裡的字元不在這個字集裡時 print()
# 會亂碼甚至整支中斷——跟舊版 buyer_match.py 同一個修法。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


def _sanitize(name: str) -> str:
    return (
        name.replace(",", "_").replace("，", "_").replace("/", "_").replace("\\", "_")
    )[:60]


def _format_report(
    customer: str, need: str, results: list[yc_link.YcLinkResult], new_links: set[str]
) -> str:
    found = [r for r in results if r.yc_link]
    new_count = sum(1 for r in found if r.yc_link in new_links)
    lines = [
        f"客戶：{customer}／子條件：{need}",
        f"查了 {len(results)} 筆候選，找到 {len(found)} 筆永慶連結（其中 {new_count} 筆是新出現的）",
        "",
    ]
    for r in results:
        if r.yc_link:
            mark = "🆕 " if r.yc_link in new_links else ""
            display_title = r.full_title or r.title
            price_line = f"\n   開價 {r.price}" if r.price else ""
            lines.append(f"✅ {mark}{display_title}（{r.subtitle}）{price_line}\n   {r.yc_link}\n")
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


async def run_group(
    ctx, group: str, customer: str | None, need: str | None, limit: int, seen_data: dict
) -> list[dict]:
    """跑完一組，回傳這組每個客需子條件的結構化結果（給看板 JSON 用）。"""
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
    group_result: list[dict] = []
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

            new_links = seen_store.mark_seen(
                seen_data, cust, n, [r.yc_link for r in results if r.yc_link]
            )

            report = _format_report(cust, n, results, new_links)
            print(report)

            found = sum(1 for r in results if r.yc_link)
            out_path = (
                OUTPUT_DIR
                / f"{datetime.now():%Y%m%d_%H%M%S}_{_sanitize(cust)}_{_sanitize(n)}_yc.txt"
            )
            out_path.write_text(report, encoding="utf-8")
            print(f"[INFO] 已存檔：{out_path}（找到 {found} 筆永慶連結，{len(new_links)} 筆新出現）")

            candidates = []
            for r in results:
                d = asdict(r)
                d["is_new"] = bool(r.yc_link) and r.yc_link in new_links
                candidates.append(d)
            group_result.append({"customer": cust, "need": n, "candidates": candidates})
    return group_result


async def main_async(args) -> None:
    all_groups: list[dict] = []
    seen_data = seen_store.load()
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
                jobs = await run_group(ctx, group, args.customer, args.need, args.limit, seen_data)
            except RuntimeError as e:
                print(f"[WARN] 群組「{group}」整組失敗，跳過：{e}", file=sys.stderr)
                continue
            all_groups.append({"group": group, "customers": jobs})

    removed = seen_store.prune(seen_data)
    seen_store.save(seen_data)
    if removed:
        print(f"[INFO] 去重記憶清掉 {removed} 筆超過 {seen_store.RETAIN_DAYS} 天沒再出現的連結")

    OUTPUT_DIR.mkdir(exist_ok=True)
    RUN_JSON_PATH.write_text(
        json.dumps(
            {"generated_at": datetime.now().isoformat(timespec="seconds"), "groups": all_groups},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n[INFO] 整輪結果已寫入：{RUN_JSON_PATH}")

    html_path = build_static_view.build()
    print(f"[INFO] 看板已重產：{html_path}")

    if args.publish:
        if not DEPLOY_SCRIPT.exists():
            print(f"[WARN] 找不到部署腳本 {DEPLOY_SCRIPT}，略過部署（看板 HTML 已產好，之後可手動部署）")
            return
        print("[INFO] 部署到 Cloudflare Pages（python update.py --deploy-only）...")
        proc = subprocess.run(
            [sys.executable, "update.py", "--deploy-only"],
            cwd=DEPLOY_SCRIPT.parent,
        )
        if proc.returncode != 0:
            print(f"[WARN] 部署失敗（exit {proc.returncode}），看板 HTML 已產好，之後可手動跑 update.py --deploy-only")
        else:
            print("[INFO] 已部署，網址：https://yc-tools.pages.dev/buyer-match/")


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案：抓候選物件裡的永慶房屋官網連結")
    ap.add_argument("group", nargs="+", help="房地「客需條件」裡的群組名稱，例：A買、B買、C買、其他")
    ap.add_argument("--customer", default=None, help="只跑這組裡的某個客戶（全部子條件）")
    ap.add_argument("--need", default=None, help="只跑指定子條件（要搭配 --customer）")
    ap.add_argument(
        "--limit", type=int, default=yc_link.DEFAULT_MAX_CANDIDATES,
        help=f"每個子條件最多查前幾筆候選（預設 {yc_link.DEFAULT_MAX_CANDIDATES}，候選多時逐筆點開查很慢）",
    )
    ap.add_argument(
        "--no-publish", dest="publish", action="store_false",
        help="只重產本機看板 HTML，不部署到 Cloudflare Pages",
    )
    args = ap.parse_args()

    if args.need and not args.customer:
        ap.error("--need 要搭配 --customer 一起用")

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
