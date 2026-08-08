#!/usr/bin/env python3
"""買方配案（整組批次）：跑完房地「客需條件」某個群組（A買/B買/C買/其他）底下
所有客戶、每個客戶存的每一個子條件，逐一去 i智慧 現查、各自存檔。

用法：
    python run_group_match.py A買                       # 整組全部跑
    python run_group_match.py A買 B買 C買                 # 三組依序跑完（GUI 的「★ 全部群組」走這條）
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
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from playwright.async_api import async_playwright

import buyer_match
import foundi_need
import manifest
import seen_store


def _unit_block(group: "seen_store.UnitGroup") -> str:
    """一戶輸出一段：用開價最低那筆當代表，同一戶其他店的開價附註在後面。"""
    card, agent, share_url = group.entry
    body = buyer_match.format_block(card, agent, share_url)
    note = group.note()
    return f"{body}\n{note}" if note else body


@dataclass
class JobResult:
    """一個「客戶／客需」跑完的結果。用 dataclass 而不是一串文字，是為了讓
    daily_run.py 組 LINE 訊息時直接讀數字，不用回頭用 regex 解析自己印的字。"""

    customer: str
    need: str
    hits: int = 0            # 這次實際輸出（存檔）幾段
    new: Optional[int] = None       # 以下四個只有 only_new 模式才有值（單位是「戶」）
    repriced: Optional[int] = None  # 降價的戶數
    skipped: Optional[int] = None   # 跟上次一樣、略過的戶數
    raised: Optional[int] = None    # 最低開價變高（多半是便宜的委託下架）→ 不回報
    error: str = ""

    @property
    def text(self) -> str:
        if self.error:
            return f"錯誤：{self.error}"
        if self.new is None:
            return f"{self.hits} 筆"
        parts = [f"新 {self.new} 戶"]
        if self.repriced:
            parts.append(f"降價 {self.repriced} 戶")
        if self.skipped:
            parts.append(f"同前 {self.skipped} 戶略過")
        if self.raised:
            parts.append(f"漲價 {self.raised} 戶略過")
        return "／".join(parts)


async def run_group(
    ctx,
    group: str,
    customer: Optional[str] = None,
    limit: int = 15,
    dry_run: bool = False,
    newest: bool = False,
    only_new: bool = False,
    on_result=None,
) -> list[JobResult]:
    """跑完一個群組（可限定單一客戶），回傳每個「客戶／客需」的 JobResult。

    ctx 是已經連上的 CDP context——CLI（下面的 run）跟排程（daily_run.py）各自
    處理連線/登入檢查，這裡只負責迴圈本身，兩邊行為保證一致。

    `only_new=True`（每天 08:10 那班用）：跟 `seen_store.py` 記的比對，只輸出上次
    沒出現過的＋總價變了的，昨天看過的同一批不再寫檔。

    `on_result(JobResult)`：每跑完一個客需就叫一次。排程那邊拿它把進度寫進
    `daily_run.log`——整組要跑 40 分鐘以上，只在最後才記一筆的話，中途卡住／被關機
    打斷時完全看不出停在哪一位客戶（這 repo 一再吃到的「事後查不到」）。
    """
    foundi_page = await foundi_need.get_or_open_foundi_page(ctx)
    customers = await foundi_need.list_group(foundi_page, group)

    # 房地上已經被移走的客戶／客需，manifest 跟看板要跟著清掉，不然舊資料會一直
    # 陰魂不散地留在網址上（2026-08-06 使用者實測抓到：移出房地後，看板還有她）。
    valid_keys = {f"{name}／{need}" for name, needs in customers for need in needs}
    removed = manifest.prune_group(group, valid_keys)
    if removed:
        print(f"[INFO] 房地已移除、看板同步清掉 {len(removed)} 筆：{'、'.join(removed)}")

    if customer:
        customers = [(name, needs) for name, needs in customers if name == customer]
        if not customers:
            raise RuntimeError(f"群組「{group}」裡找不到客戶「{customer}」")

    total_jobs = sum(len(needs) for _, needs in customers)
    print(f"[INFO] 群組「{group}」共 {len(customers)} 位客戶、{total_jobs} 個客需子條件要跑")

    i智慧_page = buyer_match.get_or_open_page(ctx, "is.ycut.com.tw")
    if i智慧_page is None:
        i智慧_page = await ctx.new_page()

    summary: list[JobResult] = []
    seen_data = seen_store.load() if only_new else {}

    def record(result: JobResult) -> None:
        summary.append(result)
        if on_result:
            try:
                on_result(result)
            except Exception as e:  # 進度回報壞掉不該害整批停下來
                print(f"[WARN] on_result 回呼失敗（忽略）：{e}", file=sys.stderr)

    job_no = 0
    for cust, needs in customers:
        for need in needs:
            job_no += 1
            print(f"\n[INFO] ({job_no}/{total_jobs}) 客戶「{cust}」／子條件「{need}」")
            try:
                fneed = await foundi_need.load_customer_need(ctx, cust, need)
            except RuntimeError as e:
                print(f"[WARN] 讀房地客需失敗，跳過：{e}", file=sys.stderr)
                record(JobResult(cust, need, error=str(e)))
                continue

            if not fneed.areas:
                print("[INFO] 這個子條件沒有任何候選物件，跳過")
                record(
                    JobResult(cust, need, hits=0,
                              new=0 if only_new else None,
                              repriced=0 if only_new else None,
                              skipped=0 if only_new else None,
                              raised=0 if only_new else None)
                )
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
                    type_any=fneed.type_words or None,
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
                    fallback_hints=fneed.fallback_hints or None,
                )
            except Exception as e:
                print(f"[WARN] 查 i智慧 失敗，跳過：{e}", file=sys.stderr)
                record(JobResult(cust, need, error=str(e)))
                continue

            label = (
                f"{cust}_{need}"
                .replace(",", "_").replace("，", "_")
                .replace("/", "_").replace("\\", "_")
            )[:60]
            buyer_match.OUTPUT_DIR.mkdir(exist_ok=True)

            if only_new:
                scope = seen_store.scope_key(cust, need)
                fresh, dropped, skipped, raised = seen_store.classify(
                    seen_data, scope, entries
                )
                blocks = [_unit_block(g) for g in fresh]
                # ⚠️ 這裡刻意不叫 `group`——外層 run_group() 的參數也叫 group（群組名字串），
                # 這個 for 迴圈原本重用同一個名字，會把外層 group 悄悄覆蓋成 UnitGroup 物件，
                # 害後面 manifest.record_result(group, ...) 拿到錯的值（2026-08-01 wiring manifest 時抓到）。
                for repriced_group, old_price in dropped:
                    note = seen_store.price_change_note(old_price, repriced_group.min_price)
                    body = _unit_block(repriced_group)
                    blocks.append(f"{note}\n{body}" if note else body)
                print(
                    f"[INFO] 撈到 {len(entries)} 筆委託 → 新 {len(fresh)} 戶／"
                    f"降價 {len(dropped)} 戶／同前 {skipped} 戶略過"
                    + (f"／漲價 {raised} 戶略過" if raised else "")
                )
                record(
                    JobResult(cust, need, hits=len(blocks), new=len(fresh),
                              repriced=len(dropped), skipped=skipped, raised=raised)
                )
                # 每跑完一個客需就存一次，中途掛掉不會把前面 40 分鐘的記憶全丟掉
                seen_store.save(seen_data)

                # 「完整清單」快照跟 only_new 篩選無關，一律用這次 i智慧 現查的 entries
                # 整批覆蓋——只回報新案/降價不代表沒重新查過，物件下架就該從網頁上消失，
                # 不用等哪天有人手動點「完整查詢」才會更新。
                full_blocks = [
                    buyer_match.format_block(card, agent, share_url)
                    for card, agent, share_url in entries
                ]
                if full_blocks:
                    full_path = (
                        buyer_match.OUTPUT_DIR
                        / f"{datetime.now():%Y%m%d_%H%M%S}_{label}_full.txt"
                    )
                    full_path.write_text("\n\n".join(full_blocks), encoding="utf-8")
                    manifest.update_full(group, cust, need, full_path, len(full_blocks))
                else:
                    manifest.update_full(group, cust, need, None, 0)
            else:
                blocks = [
                    buyer_match.format_block(card, agent, share_url)
                    for card, agent, share_url in entries
                ]
                record(JobResult(cust, need, hits=len(blocks)))

            if blocks:
                out_path = (
                    buyer_match.OUTPUT_DIR
                    / f"{datetime.now():%Y%m%d_%H%M%S}_{label}.txt"
                )
                out_path.write_text("\n\n".join(blocks), encoding="utf-8")
                print(f"[INFO] 已存檔：{out_path}")
                manifest.record_result(
                    group, cust, need, out_path, len(blocks), only_new=only_new
                )

    return summary


def format_summary(group: str, summary: list[JobResult]) -> str:
    return "\n".join(f"客戶：{r.customer}／{r.need} → {r.text}" for r in summary)


async def _connect_ctx(p):
    """連上已開著的 CDP Chrome，拿到 context。連不到就直接結束（訊息講清楚怎麼救）。"""
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
    return browser.contexts[0] if browser.contexts else await browser.new_context()


def _copy_report(report: str) -> None:
    try:
        import pyperclip

        pyperclip.copy(report)
        print("\n[INFO] 總表已複製到剪貼簿")
    except Exception as e:
        print(f"[WARN] 複製到剪貼簿失敗（總表仍在上面）：{e}", file=sys.stderr)


async def run(args) -> None:
    async with async_playwright() as p:
        ctx = await _connect_ctx(p)

        try:
            summary = await run_group(
                ctx,
                args.group,
                customer=args.customer,
                limit=args.limit,
                dry_run=args.dry_run,
                newest=args.newest,
                only_new=getattr(args, "only_new", False),
            )
        except RuntimeError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
            sys.exit(1)

        print("\n" + "=" * 40)
        print(f"群組「{args.group}」跑完，共 {len(summary)} 個客需子條件：\n")
        report = format_summary(args.group, summary)
        print(report)
        _copy_report(report)


async def run_all(args, groups: list[str]) -> None:
    """一次跑好幾個群組（GUI 的「★ 全部群組」／CLI 給多個群組名）。

    CDP 只連一次，群組之間接著跑；某一組整組失敗（例如群組名字在房地找不到）只印警告
    往下跑，不會把後面幾組一起拖掉——整批要跑好幾小時，不該因為第一組打錯字就白等。
    """
    async with async_playwright() as p:
        ctx = await _connect_ctx(p)

        sections: list[str] = []
        for i, group in enumerate(groups, 1):
            print("\n" + "=" * 40)
            print(f"[INFO] ({i}/{len(groups)}) 開始跑群組「{group}」")
            try:
                summary = await run_group(
                    ctx,
                    group,
                    customer=None,
                    limit=args.limit,
                    dry_run=args.dry_run,
                    newest=args.newest,
                    only_new=getattr(args, "only_new", False),
                )
            except RuntimeError as e:
                print(f"[WARN] 群組「{group}」整組失敗，跳過：{e}", file=sys.stderr)
                sections.append(f"【{group}】整組失敗：{e}")
                continue

            print(f"\n群組「{group}」跑完，共 {len(summary)} 個客需子條件：\n")
            body = format_summary(group, summary)
            print(body)
            sections.append(f"【{group}】{len(summary)} 個客需\n{body}")

        report = "\n\n".join(sections)
        print("\n" + "=" * 40)
        print(f"全部 {len(groups)} 組跑完：\n")
        print(report)
        _copy_report(report)


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案：批次跑房地某個群組底下全部客戶的客需")
    ap.add_argument(
        "group", nargs="+",
        help="房地「客需條件」裡的群組名稱，例：A買、B買、C買、其他。給多個就一組一組接著跑",
    )
    ap.add_argument("--customer", default=None, help="只跑這組裡的某個客戶（全部子條件），不給就整組跑")
    ap.add_argument("--limit", type=int, default=15, help="每個客需子條件在 i智慧 最多處理幾筆（預設 15）")
    ap.add_argument("--dry-run", action="store_true", help="開詳情頁抓專員資訊，但不點分享（除錯/試跑用）")
    ap.add_argument(
        "--newest", action="store_true",
        help="i智慧改用「上架：新>舊」排序（預設是總價低到高）。想優先看新案、讓 🆕 標記浮上來就加這個",
    )
    ap.add_argument(
        "--only-new", action="store_true",
        help="只輸出上次沒出現過的＋總價變了的（記憶存 state/seen.json）。"
             "每天 08:10 排程預設就是這個模式；手動想看完整清單就不要加",
    )
    args = ap.parse_args()

    groups = args.group
    if len(groups) > 1:
        if args.customer:
            ap.error("--customer 只能配單一群組使用")
        asyncio.run(run_all(args, groups))
    else:
        args.group = groups[0]   # 底下 run() 一路都當字串用
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
