#!/usr/bin/env python3
"""買方配案：依條件掃 i智慧Pro 流通物件，逐筆取物件資訊＋專員聯絡方式＋公開分享連結。

啟動模式：CDP attach（跟桌面「自動比對專約」工具同一套）——
先跑 open_real_chrome.bat 開一個帶 --remote-debugging-port=9223 的 Chrome、
手動登入一次 i智慧，之後這支腳本用 connect_over_cdp 連進去操作，不存帳密、
不用另外處理登入流程。

用法：
    python buyer_match.py --area 苓雅區 --price-min 300 --price-max 500
    python buyer_match.py --area 三多商圈 --price-max 800 --rooms-min 2 --limit 10
    python buyer_match.py --area 苓雅區 --price-max 500 --list-only   # 只看筆數，不逐筆開詳情頁（快）
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright

CDP_URL = "http://localhost:9223"
ISMART_SEARCH_URL = "https://is.ycut.com.tw/is/case/search/all-case"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"


# ──────────────────────────────────────────────────────────────
# 資料結構
# ──────────────────────────────────────────────────────────────


@dataclass
class Card:
    case_name: str
    community: Optional[str]
    address: str
    usage: str
    layout: str
    age_years: Optional[float]
    area_ping: Optional[float]
    case_id: Optional[str]
    price_wan: Optional[int]
    unit_price_wan: Optional[float]
    rooms: Optional[int]
    raw_text: str = field(repr=False, default="")


@dataclass
class Agent:
    name_title: str = ""
    phone: str = ""
    store: str = ""
    store_addr: str = ""
    store_phone: str = ""


# ──────────────────────────────────────────────────────────────
# i智慧 清單頁：搜尋 + 掃卡片（沿用「自動比對專約」實測過的手法）
# ──────────────────────────────────────────────────────────────

_EXTRACT_CARDS_JS = r"""
() => {
  const rowVal = (c, label) => {
    const rows = c.querySelectorAll('.d-flex.column-gap-12.fz-14');
    for (const r of rows) {
      const k = r.children;
      if (k.length >= 2 && ((k[0].textContent || '').trim() === label)) {
        return (k[1].textContent || '').trim();
      }
    }
    return '';
  };
  const cards = [...document.querySelectorAll(
    '.border-bottom-1-e0e0e0.d-flex.relative.is-hover-background-color')];
  return cards.map(c => ({
    caseName: c.querySelector('.color-212121.fz-21')?.textContent?.trim() || '',
    community: c.querySelector('.fz-16.color-fe6501')?.textContent?.trim() || '',
    addr: c.querySelector('.fz-16.color-212121')?.textContent?.trim() || '',
    usage: rowVal(c, '用途'),
    layout: rowVal(c, '格局'),
    ageRaw: rowVal(c, '屋齡'),
    areaRaw: rowVal(c, '建物'),
    caseId: rowVal(c, '編號'),
    text: (c.innerText || '').replace(/\s+/g, ' ').trim(),
  }));
}
"""

_SET_PAGESIZE_30_JS = r"""
() => {
  const sel = document.querySelector('.paginator-select-group select');
  if (!sel) return 'no_select';
  if (sel.value === '30') return 'already';
  const setter = Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype, 'value').set;
  setter.call(sel, '30');
  sel.dispatchEvent(new Event('change', {bubbles: true}));
  return 'set';
}
"""

_NEXT_PAGE_JS = r"""
() => {
  const btn = document.querySelector('button.mat-paginator-navigation-next');
  if (!btn) return 'no_btn';
  if (btn.disabled || btn.classList.contains('mat-mdc-button-disabled'))
    return 'disabled';
  btn.click();
  return 'clicked';
}
"""

_CLICK_EXACT_TEXT_JS = r"""
(label) => {
  const els = [...document.querySelectorAll('button, a, div, span')];
  const el = els.find(e => (e.textContent || '').trim() === label
    && e.children.length === 0);
  if (!el) return 'not_found';
  const clickable = el.closest('button, a') || el;
  clickable.click();
  return 'clicked';
}
"""


async def _ensure_scope_all(page: Page) -> None:
    """把「範圍」切到「全部」，避免預設「複數店」漏掉非本店流通物件。"""
    try:
        result = await page.evaluate("""() => {
            const btns = [...document.querySelectorAll('is-radio-button, is-radio-button-v3')];
            const all_btn = btns.find(b => (b.textContent || '').trim() === '全部');
            if (!all_btn) return 'not_found';
            if (all_btn.classList.contains('selected')) return 'already_selected';
            all_btn.click();
            return 'clicked';
        }""")
        if result == "clicked":
            await page.wait_for_timeout(500)
    except Exception as e:
        print(f"[WARN] 切範圍失敗（不影響搜尋、繼續）：{e}", file=sys.stderr)


async def ensure_search_page(page: Page) -> None:
    for attempt in range(3):
        try:
            await page.goto(ISMART_SEARCH_URL, wait_until="domcontentloaded")
            cur = page.url or ""
            if "opid.ycut.com.tw" in cur or "/login" in cur:
                raise RuntimeError(
                    f"i智慧登入態過期，被導去 {cur}。"
                    "請切到 open_real_chrome.bat 開的那個 Chrome 視窗手動重新登入，"
                    "登好後重跑這支腳本（不用重開 Chrome）。"
                )
            await page.wait_for_selector(
                'input[placeholder*="編號"][placeholder*="案名"]', timeout=20000
            )
            await _ensure_scope_all(page)
            return
        except RuntimeError:
            raise
        except Exception as e:
            print(f"[WARN] 搜尋頁第 {attempt + 1}/3 次嘗試失敗：{e}", file=sys.stderr)
            await page.wait_for_timeout(2000)
    raise RuntimeError("i智慧搜尋頁載入失敗")


async def _range_label(page: Page) -> str:
    try:
        return await page.evaluate(
            "() => (document.querySelector('.mat-paginator-range-label')"
            "?.textContent || '').trim()"
        )
    except Exception:
        return ""


async def _collect_all_cards(page: Page, max_pages: int = 15) -> list[dict]:
    try:
        r = await page.evaluate(_SET_PAGESIZE_30_JS)
        if r == "set":
            await page.wait_for_timeout(1800)
    except Exception as e:
        print(f"[WARN] 設每頁 30 筆失敗（用預設頁大小繼續）：{e}", file=sys.stderr)

    all_raw: list[dict] = []
    for _ in range(max_pages):
        await page.wait_for_timeout(300)
        all_raw.extend(await page.evaluate(_EXTRACT_CARDS_JS))

        label_before = await _range_label(page)
        nxt = await page.evaluate(_NEXT_PAGE_JS)
        if nxt != "clicked":
            break
        for _ in range(20):
            await page.wait_for_timeout(300)
            if (await _range_label(page)) != label_before:
                break
        await page.wait_for_timeout(900)
    else:
        print(f"[WARN] 翻頁達上限 {max_pages} 頁仍有下一頁，關鍵字太廣的話建議縮小範圍",
              file=sys.stderr)

    print(f"[INFO] 掃到 {len(all_raw)} 張卡")
    return all_raw


def _parse_card(r: dict) -> Card:
    text = r.get("text", "")
    case_id = (r.get("caseId") or "").strip() or None

    price_wan = None
    unit_price_wan = None
    if case_id:
        m = re.search(re.escape(case_id) + r"\s*([\d,]+)\s*萬\s*([\d.]+)?\s*萬/坪", text)
        if m:
            price_wan = int(m.group(1).replace(",", ""))
            if m.group(2):
                unit_price_wan = float(m.group(2))
    if price_wan is None:
        m = re.search(r"([\d,]+)\s*萬", text)
        if m:
            price_wan = int(m.group(1).replace(",", ""))

    age = None
    m = re.search(r"([\d.]+)\s*年", r.get("ageRaw", "") or "")
    if m:
        age = float(m.group(1))

    area = None
    m = re.search(r"([\d.]+)\s*坪", r.get("areaRaw", "") or "")
    if m:
        area = float(m.group(1))

    rooms = None
    m = re.search(r"(\d+)\s*房", r.get("layout", "") or "")
    if m:
        rooms = int(m.group(1))

    return Card(
        case_name=r.get("caseName", ""),
        community=(r.get("community") or None),
        address=r.get("addr", ""),
        usage=r.get("usage", ""),
        layout=r.get("layout", ""),
        age_years=age,
        area_ping=area,
        case_id=case_id,
        price_wan=price_wan,
        unit_price_wan=unit_price_wan,
        rooms=rooms,
        raw_text=text,
    )


async def submit_search(page: Page, keyword: str) -> None:
    await ensure_search_page(page)
    inp = page.locator('input[placeholder*="編號"][placeholder*="案名"]').first
    await inp.click()
    await inp.fill("")
    await inp.type(keyword, delay=30)
    await page.wait_for_timeout(200)

    clicked = await page.evaluate("""() => {
        const b = [...document.querySelectorAll('button')].find(
            el => (el.textContent || '').trim() === '搜尋');
        if (!b) return false;
        b.click();
        return true;
    }""")
    if not clicked:
        await inp.press("Enter")
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    await page.wait_for_timeout(900)

    try:
        r = await page.evaluate(_SET_PAGESIZE_30_JS)
        if r == "set":
            await page.wait_for_timeout(1800)
    except Exception as e:
        print(f"[WARN] 設每頁 30 筆失敗（用預設頁大小繼續）：{e}", file=sys.stderr)


async def search_cards(page: Page, keyword: str) -> list[Card]:
    """一次掃完所有分頁、回傳全部卡片（不點進詳情頁）。給 --list-only 預覽用。"""
    await submit_search(page, keyword)
    raw = await _collect_all_cards(page)
    return [_parse_card(r) for r in raw]


async def iter_pages(page: Page, max_pages: int = 15):
    """逐頁 yield 當下 DOM 的原始卡片清單（不累積）。

    每個 item 是 (page_no, raw_cards)。**在還沒讓這個 generator 前進到下一頁之前**，
    呼叫端要用 raw_cards 裡的 index 把這一頁想點的卡片點完——
    一旦翻到下一頁，原本這頁的 DOM 就沒了，index 也跟著失效。
    呼叫端可以在任何一頁處理完後直接 break（不用特別通知，generator 會自動關閉、不再翻頁）。
    """
    for page_no in range(1, max_pages + 1):
        await page.wait_for_timeout(300)
        raw = await page.evaluate(_EXTRACT_CARDS_JS)
        yield page_no, raw

        label_before = await _range_label(page)
        nxt = await page.evaluate(_NEXT_PAGE_JS)
        if nxt != "clicked":
            return
        for _ in range(20):
            await page.wait_for_timeout(300)
            if (await _range_label(page)) != label_before:
                break
        await page.wait_for_timeout(900)
    print(f"[WARN] 翻頁達上限 {max_pages} 頁仍有下一頁，關鍵字太廣的話建議縮小範圍",
          file=sys.stderr)


def passes_filters(
    c: Card,
    price_min: Optional[int],
    price_max: Optional[int],
    rooms_min: Optional[int],
    usage_keyword: Optional[str],
    area_keyword: str,
) -> bool:
    if area_keyword and area_keyword not in c.address and area_keyword not in (c.community or ""):
        return False
    if price_min is not None and (c.price_wan is None or c.price_wan < price_min):
        return False
    if price_max is not None and (c.price_wan is None or c.price_wan > price_max):
        return False
    if rooms_min is not None and (c.rooms is None or c.rooms < rooms_min):
        return False
    if usage_keyword and usage_keyword not in c.usage:
        return False
    return True


def apply_filters(
    cards: list[Card],
    price_min: Optional[int],
    price_max: Optional[int],
    rooms_min: Optional[int],
    usage_keyword: Optional[str],
    area_keyword: str,
) -> list[Card]:
    out = [
        c
        for c in cards
        if passes_filters(c, price_min, price_max, rooms_min, usage_keyword, area_keyword)
    ]
    out.sort(key=lambda c: (c.price_wan is None, c.price_wan or 0))
    return out


# ──────────────────────────────────────────────────────────────
# 詳情頁：專員聯絡資訊 + 分享連結
# ──────────────────────────────────────────────────────────────


def _parse_agent(body_text: str) -> Agent:
    idx = body_text.find("承辦人聯絡資訊")
    if idx == -1:
        return Agent()
    chunk = body_text[idx : idx + 500]
    end = chunk.find("帶看注意事項")
    if end != -1:
        chunk = chunk[:end]
    lines = [l.strip() for l in chunk.splitlines() if l.strip()]
    # lines[0] = "承辦人聯絡資訊", lines[1] = "承辦人"（標籤）, 接著才是資料
    data = lines[2:]
    keys = ["name_title", "phone", "store", "store_addr", "store_phone"]
    kwargs = dict(zip(keys, data))
    return Agent(**kwargs)


_CARD_SELECTOR = ".border-bottom-1-e0e0e0.d-flex.relative.is-hover-background-color"


async def _open_card_detail(list_page: Page, card_index: int):
    """點第 card_index 張卡開出詳情頁（新分頁）。整張卡的容器理論上就是可點區域
    （class 裡的 is-hover-background-color 就是整行 hover 樣式），保險起見
    容器點不出新分頁的話、退回點卡片標題文字。"""
    card = list_page.locator(_CARD_SELECTOR).nth(card_index)
    try:
        async with list_page.context.expect_page(timeout=6000) as info:
            await card.click()
        return await info.value
    except Exception:
        title = card.locator(".color-212121.fz-21").first
        async with list_page.context.expect_page(timeout=15000) as info:
            await title.click()
        return await info.value


async def open_detail_and_fetch(
    list_page: Page, card_index: int, dry_run: bool
) -> tuple[Agent, Optional[str]]:
    """點清單第 card_index 張卡（0-based，對應當下渲染頁面上的卡片順序）→
    開詳情頁抓專員資訊 → 點分享（會跳原生確認視窗，這裡自動按確定）→
    抓公開分享頁網址 → 關掉開出來的分頁、回到清單頁。"""
    detail_page = await _open_card_detail(list_page, card_index)
    await detail_page.wait_for_load_state("domcontentloaded")
    await detail_page.wait_for_timeout(600)

    body_text = await detail_page.evaluate("() => document.body.innerText")
    agent = _parse_agent(body_text)

    share_url = None
    if not dry_run:
        detail_page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
        try:
            async with detail_page.context.expect_page(timeout=8000) as share_info:
                r = await detail_page.evaluate(_CLICK_EXACT_TEXT_JS, "分享")
                if r != "clicked":
                    raise RuntimeError("找不到「分享」按鈕")
            share_page = await share_info.value
            await share_page.wait_for_load_state("domcontentloaded")
            share_url = share_page.url
            await share_page.close()
        except Exception as e:
            print(f"[WARN] 取分享連結失敗（不影響其他資訊）：{e}", file=sys.stderr)

    await detail_page.close()
    return agent, share_url


# ──────────────────────────────────────────────────────────────
# 輸出格式
# ──────────────────────────────────────────────────────────────


def format_block(card: Card, agent: Optional[Agent], share_url: Optional[str]) -> str:
    lines = [f"◆ {card.case_name}"]
    loc = card.address + (f"（{card.community}）" if card.community else "")
    lines.append(loc)
    spec = f"{card.usage}｜{card.layout}"
    if card.age_years is not None:
        spec += f"｜屋齡{card.age_years}年"
    if card.area_ping is not None:
        spec += f"｜建物{card.area_ping}坪"
    lines.append(spec)
    price = f"總價 {card.price_wan}萬" if card.price_wan is not None else "總價未知"
    if card.unit_price_wan is not None:
        price += f"（{card.unit_price_wan}萬/坪）"
    price += f"　編號 {card.case_id or '-'}"
    lines.append(price)
    if agent:
        if agent.name_title or agent.phone:
            lines.append(f"專員：{agent.name_title}　{agent.phone}")
        if agent.store or agent.store_phone:
            lines.append(f"店別：{agent.store}　{agent.store_phone}")
    if share_url:
        lines.append(f"物件連結：{share_url}")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────


async def run(args) -> None:
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            print(
                f"[ERROR] 連不到 {CDP_URL}。\n"
                "請先雙擊 open_real_chrome.bat 開瀏覽器（第一次要手動登入 i智慧），"
                "確認視窗開著之後再重跑這支腳本。",
                file=sys.stderr,
            )
            sys.exit(1)

        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = None
        for pg in ctx.pages:
            if "is.ycut.com.tw" in pg.url:
                page = pg
                break
        if page is None:
            page = await ctx.new_page()

        if args.list_only:
            cards = await search_cards(page, args.area)
            matched = apply_filters(
                cards,
                price_min=args.price_min,
                price_max=args.price_max,
                rooms_min=args.rooms_min,
                usage_keyword=args.usage,
                area_keyword=args.area,
            )
            print(f"[INFO] 篩選後符合條件：{len(matched)} 筆（共掃到 {len(cards)} 筆）")
            for c in matched[: args.limit or len(matched)]:
                print(format_block(c, None, None))
                print()
            return

        # 逐頁處理：在同一頁的 DOM 還活著的時候就把命中的卡片點掉，
        # 避免「先掃完全部分頁、再回頭點某個 index」時 index 早已失效的問題。
        # i智慧預設就是總價由低到高排序，所以逐頁蒐集＝由便宜到貴，跟 --limit
        # 想要「先給便宜的」的直覺一致，不用另外全域排序。
        await submit_search(page, args.area)
        blocks: list[str] = []
        total_seen = 0
        async for page_no, raw in iter_pages(page):
            total_seen += len(raw)
            for idx, r in enumerate(raw):
                if len(blocks) >= args.limit:
                    break
                card = _parse_card(r)
                if not passes_filters(
                    card, args.price_min, args.price_max, args.rooms_min, args.usage, args.area
                ):
                    continue
                print(f"[INFO] 第 {page_no} 頁第 {idx + 1} 張命中，處理第 {len(blocks) + 1}/{args.limit} 筆：{card.case_name}")
                agent, share_url = await open_detail_and_fetch(page, idx, dry_run=args.dry_run)
                blocks.append(format_block(card, agent, share_url))
                await page.wait_for_timeout(400)
            if len(blocks) >= args.limit:
                break

        print(f"[INFO] 共掃到 {total_seen} 筆、實際處理 {len(blocks)} 筆")

        if not blocks:
            print("[INFO] 沒有符合條件的物件")
            return

        output = "\n\n".join(blocks)
        print("\n" + "=" * 40 + "\n")
        print(output)

        OUTPUT_DIR.mkdir(exist_ok=True)
        out_path = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{args.area}.txt"
        out_path.write_text(output, encoding="utf-8")
        print(f"\n[INFO] 已存檔：{out_path}")

        try:
            import pyperclip

            pyperclip.copy(output)
            print("[INFO] 已複製到剪貼簿，可直接貼給客戶")
        except Exception as e:
            print(f"[WARN] 複製到剪貼簿失敗（內容仍在上面/檔案裡）：{e}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案：依條件掃 i智慧流通物件")
    ap.add_argument("--area", required=True, help="行政區/社區/路名關鍵字，例：苓雅區、三多商圈")
    ap.add_argument("--price-min", type=int, default=None, help="總價下限（萬）")
    ap.add_argument("--price-max", type=int, default=None, help="總價上限（萬）")
    ap.add_argument("--rooms-min", type=int, default=None, help="至少幾房")
    ap.add_argument("--usage", default=None, help="用途關鍵字，例：住宅（排除店面/透天等）")
    ap.add_argument("--limit", type=int, default=15, help="最多處理幾筆詳情頁（預設 15）")
    ap.add_argument("--list-only", action="store_true", help="只列出篩選後清單，不開詳情頁/不抓專員與分享連結（快速預覽用）")
    ap.add_argument("--dry-run", action="store_true", help="開詳情頁抓專員資訊，但不點分享（除錯用）")
    args = ap.parse_args()

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
