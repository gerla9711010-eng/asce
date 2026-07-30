#!/usr/bin/env python3
"""買方配案：依條件掃 i智慧Pro 流通物件，逐筆取物件資訊＋專員聯絡方式＋公開分享連結。

啟動模式：CDP attach（跟桌面「自動比對專約」工具同一套）——
先跑 open_real_chrome.bat 開一個帶 --remote-debugging-port=9223 的 Chrome、
第一次手動登入一次 i智慧。之後 session（cookie）過期時，若 .env 有填
ISMART_ACCOUNT / ISMART_PASSWORD，腳本會自動重新登入，不用人在旁邊手動打帳密。
沒填的話才會退回「請手動登入」的提示。

用法：
    python buyer_match.py --area 苓雅區 --price-min 300 --price-max 500
    python buyer_match.py --area 三多商圈 --price-max 800 --rooms-min 2 --limit 10
    python buyer_match.py --area 苓雅區 --price-max 500 --list-only   # 只看筆數，不逐筆開詳情頁（快）
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import Page, async_playwright

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv 是選配，沒裝就跳過自動登入功能
    load_dotenv = None

CDP_PORT = 9223
CDP_URL = f"http://localhost:{CDP_PORT}"
ISMART_SEARCH_URL = "https://is.ycut.com.tw/is/case/search/all-case"

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

if load_dotenv:
    load_dotenv(BASE_DIR / ".env")

# Windows 中文版終端機預設用 cp950，物件標題常見的 emoji（🐣🌸 之類）不在這個字集裡，
# print() 到 console 會直接 UnicodeEncodeError 整支腳本中斷。GUI 模式不受影響
# （stdout 會被換成 QueueWriter，走的是 Python str、不經過 console 編碼），
# 這裡只是讓 CLI 模式在同樣情況下印「?」而不是整個炸掉。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")


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
    floor_raw: str = ""
    # 2026-07-29 實測確認 i智慧卡片有三個獨立的坪數欄位：建物（含公設的總坪）／
    # 主建（主建物）／地坪（土地）。房地的「主建物坪數」要對 main_area_ping，
    # 對到 area_ping 是比錯欄位（總坪一定比主建大，會放進不符合的物件）。
    main_area_ping: Optional[float] = None
    land_ping: Optional[float] = None
    baths: Optional[int] = None
    is_new: bool = False
    raw_text: str = field(repr=False, default="")

    def fingerprint(self) -> tuple:
        """同一門牌被多店簽委託時，每個委託是不同 case_id 但其實是同一戶——
        比對「是不是同一戶」不能用 case_id，要用地址／樓層／坪數／總價這組規格指紋。
        （2026-07-29 討論買方配案+房地整合時定案，見對話紀錄）"""
        loc = (self.community or self.address or "").strip()
        return (loc, (self.floor_raw or "").strip(), self.area_ping, self.price_wan)

    def unit_key(self) -> str:
        """跨天辨識「這是不是上次那一戶」用的 key（給 seen_store.py 記憶已回報過的案子）。

        跟上面的 `fingerprint()` 差一件事：**刻意不含總價**。總價另外存起來比對，
        變了要當「降價/調價」重新回報一次，不是當成一筆新物件。

        ⚠️ 不用 i智慧案號當主鍵：同一戶被永慶多店簽委託會有好幾個案號，用案號的話
        「同一戶換一家店重掛」會被誤判成新案。案號只在欄位缺到組不出指紋時當備援。"""
        loc = (self.community or self.address or "").strip()
        floor = (self.floor_raw or "").strip()
        ping = f"{self.area_ping:.1f}" if self.area_ping is not None else ""
        if loc and (floor or ping):
            return f"{loc}|{floor}|{ping}"
        return f"case:{self.case_id or self.case_name}"


@dataclass
class Agent:
    name_title: str = ""
    phone: str = ""
    store: str = ""
    store_addr: str = ""
    store_phone: str = ""
    also_listed_by: list["Agent"] = field(default_factory=list)


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
    mainAreaRaw: rowVal(c, '主建'),
    landAreaRaw: rowVal(c, '地坪'),
    floorRaw: rowVal(c, '樓層'),
    caseId: rowVal(c, '編號'),
    // NEW 標記是自訂元素 <case-new-tag-svg>（內嵌 SVG、沒有文字節點，
    // 2026-07-29 實測：搜文字「NEW」找不到，只能認這個 tag name）。
    // 排序切成「上架：新>舊」才看得到，預設排序（總價低到高）第一頁通常一個都沒有。
    isNew: !!c.querySelector('case-new-tag-svg'),
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

_NEXT_PAGE_DISABLED_JS = r"""
() => {
  const btn = document.querySelector('button.mat-paginator-navigation-next');
  if (!btn) return 'no_btn';
  if (btn.disabled || btn.classList.contains('mat-mdc-button-disabled'))
    return 'disabled';
  return 'ok';
}
"""


_SORT_NEWEST_JS = r"""
() => {
  // 排序選單是 inline 展開（不是 cdk overlay），選項清單長這樣：
  // 預設排序 / 總價：低>高 / … / 上架：新>舊 / 上架：舊>新
  // ⚠️ 2026-07-29 實測：點選項時只能點選項本身，往上連父層一起點會把選單收起來、排序不生效。
  const els = [...document.querySelectorAll('*')];
  const label = els.find(e => e.children.length === 0 && (e.textContent||'').trim() === '排序');
  if (!label || !label.parentElement) return 'no_sort_control';
  label.parentElement.click();
  const opt = [...document.querySelectorAll('.cursor-pointer')].find(
    e => (e.textContent||'').trim() === '上架：新>舊');
  if (!opt) return 'no_option';
  opt.click();
  return 'sorted';
}
"""


async def sort_by_newest(page: Page) -> bool:
    """把清單排序切成「上架：新>舊」。i智慧預設是總價低到高，第一頁通常都是便宜的舊案、
    一個 NEW 標記都沒有；要讓新案浮上來一定得先切排序。切不動不算致命錯誤（只是拿不到
    最新的），印警告繼續。"""
    try:
        state = await page.evaluate(_SORT_NEWEST_JS)
        if state != "sorted":
            print(f"[WARN] 切換「上架：新>舊」排序失敗（{state}），用網站預設排序繼續",
                  file=sys.stderr)
            return False
        await page.wait_for_timeout(3000)
        return True
    except Exception as e:
        print(f"[WARN] 切換排序失敗，用預設排序繼續：{e}", file=sys.stderr)
        return False


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


async def try_auto_login(page: Page) -> bool:
    """用 .env 的 ISMART_ACCOUNT / ISMART_PASSWORD 嘗試在當下的登入頁自動登入。
    選取器故意寫得寬鬆（沒特別指定 i智慧登入頁的確切 class），因為目前沒機會
    在不登出使用者現有 session 的情況下先看到登入頁長怎樣——第一次真的觸發時
    如果選錯欄位，請把當時登入頁的樣子回報，之後就能鎖定精確選取器。"""
    account = os.environ.get("ISMART_ACCOUNT")
    password = os.environ.get("ISMART_PASSWORD")
    if not account or not password:
        return False

    print("[INFO] 偵測到登入態過期，嘗試用 .env 帳密自動登入...")
    try:
        # i智慧走永慶 SSO（opid.ycut.com.tw），登入頁欄位是 name="userName"（人員編號）
        # + name="password"，2026-07-27 實測確認。抓不到才退回寬鬆猜測當備援。
        account_input = page.locator(
            'input[name="userName"], input[type="text"], input[type="email"], '
            'input[name*="account" i], input[placeholder*="帳號"], input[placeholder*="編號"], '
            'input[placeholder*="Email" i], input[placeholder*="帳" i]'
        ).first
        password_input = page.locator('input[name="password"], input[type="password"]').first
        await account_input.wait_for(timeout=10000)
        await account_input.click()
        await account_input.fill(account)
        await password_input.click()
        await password_input.fill(password)

        clicked = await page.evaluate("""() => {
            const candidates = [...document.querySelectorAll('button, input[type="submit"], a')];
            const el = candidates.find(e => {
                const t = (e.textContent || e.value || '').trim();
                return /登入|登錄|Login|Sign\\s*in|送出/i.test(t);
            });
            if (!el) return false;
            el.click();
            return true;
        }""")
        if not clicked:
            await password_input.press("Enter")

        for _ in range(15):
            await page.wait_for_timeout(1000)
            cur = page.url or ""
            if "opid.ycut.com.tw" not in cur and "/login" not in cur:
                print("[INFO] 自動登入成功")
                return True
        print("[WARN] 自動登入後仍停在登入頁，可能帳密錯誤或選取器對不上", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[WARN] 自動登入失敗：{e}", file=sys.stderr)
        return False


SEARCH_BOX_SELECTOR = 'input[placeholder*="編號"][placeholder*="案名"]'


async def _looks_like_login(page: Page) -> bool:
    cur = page.url or ""
    if "opid.ycut.com.tw" in cur or "/login" in cur.lower():
        return True
    try:
        return await page.evaluate(
            "() => !!document.querySelector('input[type=\"password\"]')"
        )
    except Exception:
        return False


async def ensure_search_page(page: Page) -> None:
    login_attempted = False
    for attempt in range(3):
        try:
            await page.goto(ISMART_SEARCH_URL, wait_until="domcontentloaded")
            # session 過期時，i智慧是先把 is.ycut.com.tw 這份文件載進來、
            # 前端 JS 判斷過期後才用 client-side redirect 轉去 opid.ycut.com.tw 登入頁——
            # domcontentloaded 那個時間點 URL 還沒變。
            # ⚠️ 2026-07-29 實測：轉址有時要 5 秒以上，舊版只在 1.5 秒後看一次 URL，
            # 慢一點就漏判，然後落去等搜尋框逾時 → 明明 .env 有帳密卻不會觸發自動登入，
            # 只回報「搜尋頁載入失敗」。改成輪詢 20 秒，登入頁跟搜尋框哪個先出現就走哪條。
            outcome = ""
            for _ in range(20):
                if await _looks_like_login(page):
                    outcome = "login"
                    break
                if await page.evaluate(
                    # 要看「看得到」而不只是「在 DOM 上」——搜尋框會先掛上去、隔一下才顯示，
                    # 只認 querySelector 的話下面 wait_for_selector（等 visible）還是會白等 20 秒
                    "(sel) => { const e = document.querySelector(sel);"
                    " return !!e && !!(e.offsetParent || e.getClientRects().length); }",
                    SEARCH_BOX_SELECTOR,
                ):
                    outcome = "search"
                    break
                await page.wait_for_timeout(1000)

            cur = page.url or ""
            if outcome == "login":
                if not login_attempted:
                    login_attempted = True
                    if await try_auto_login(page):
                        continue
                has_creds = bool(os.environ.get("ISMART_ACCOUNT"))
                reason = (
                    "自動登入失敗（帳密錯誤，或登入頁選取器對不上，請告訴我登入頁長怎樣讓我修）。"
                    if has_creds
                    else "沒在 .env 設定 ISMART_ACCOUNT/ISMART_PASSWORD，無法自動登入。"
                )
                raise RuntimeError(
                    f"i智慧登入態過期，被導去 {cur}。{reason}"
                    "請切到 open_real_chrome.bat 開的那個 Chrome 視窗手動重新登入，"
                    "登好後重跑這支腳本（不用重開 Chrome）。"
                )
            await page.wait_for_selector(SEARCH_BOX_SELECTOR, timeout=20000)
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


async def _click_next_page(page: Page) -> bool:
    """按分頁「下一頁」。用真的 Playwright click（不是 JS el.click()）——
    2026-07-27 實測發現「分享」那顆 Angular Material 風格按鈕不理會 JS 觸發的合成
    click（isTrusted=false），下一頁按鈕（mat-paginator）是同一個元件家族，同樣風險，
    先一併改掉、不要等真的遇到才修。"""
    state = await page.evaluate(_NEXT_PAGE_DISABLED_JS)
    if state != "ok":
        return False
    try:
        await page.locator("button.mat-paginator-navigation-next").click(timeout=3000)
    except Exception:
        return False
    return True


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
        if not await _click_next_page(page):
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

    baths = None
    m = re.search(r"([\d.]+)\s*衛", r.get("layout", "") or "")
    if m:
        baths = int(float(m.group(1)))  # 少數是「1.5衛」，無條件捨去當整數比

    def _ping(key: str) -> Optional[float]:
        mm = re.search(r"([\d.]+)\s*坪", r.get(key, "") or "")
        return float(mm.group(1)) if mm else None

    main_area_ping = _ping("mainAreaRaw")
    land_ping = _ping("landAreaRaw")

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
        floor_raw=r.get("floorRaw", "") or "",
        main_area_ping=main_area_ping,
        land_ping=land_ping,
        baths=baths,
        is_new=bool(r.get("isNew")),
        raw_text=text,
    )


def _agent_has_data(a: Optional[Agent]) -> bool:
    return bool(a and (a.name_title or a.phone or a.store or a.store_phone))


def dedup_by_fingerprint(
    entries: list[tuple[Card, Optional["Agent"], Optional[str]]]
) -> list[tuple[Card, Optional["Agent"], Optional[str]]]:
    """同一戶被多個店/多個關鍵字搜到時只留一筆代表，其餘的專員/店別併進
    representative 的 `also_listed_by`，輸出時會註明「同物件另有委託」，
    不會把同一間房子當成兩筆分享連結丟給客戶。

    ⚠️ 2026-07-29 實測踩到：某一筆的詳情頁抓專員資訊逾時失敗（`_parse_agent` 回傳全空的
    `Agent()`），空物件仍是「truthy」，原本會被當成「有資料的其他委託」印出一行空白的
    「（同物件另有委託：　　）」。改成明確判斷欄位是否真的有值：
    ①「代表」優先選 bucket 裡第一筆**真的抓到專員資訊**的（第一筆逾時失敗的話用第二筆頂替，
    card/share_url 跟著同一筆一起換，避免代表筆是空的但其他委託卻有資料這種本末倒置）
    ②「其他委託」只列真的有資料的，全空的直接跳過、不印出來。"""
    groups: dict[tuple, list[tuple[Card, Optional[Agent], Optional[str]]]] = {}
    order: list[tuple] = []
    for entry in entries:
        card = entry[0]
        key = card.fingerprint()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(entry)

    out: list[tuple[Card, Optional[Agent], Optional[str]]] = []
    for key in order:
        bucket = groups[key]
        primary_idx = next((i for i, (_, a, _) in enumerate(bucket) if _agent_has_data(a)), 0)
        card, agent, share_url = bucket[primary_idx]
        rest = bucket[:primary_idx] + bucket[primary_idx + 1 :]
        others = [a for (_, a, _) in rest if _agent_has_data(a)]
        if others:
            agent = agent or Agent()
            agent.also_listed_by = others
        out.append((card, agent, share_url))
    return out


_PARKING_TYPE_LABELS = [
    "坡道/平面", "坡道/機械", "昇降/平面", "昇降/機械",
    "庭院", "平移/機械", "獨立車庫", "塔式車位",
]


async def _select_districts(page: Page, districts: list[str]) -> None:
    """縣市區域是自訂元件（不是原生 select），流程：點開 → 選地區分類「南部」→
    選「高雄市」→ 勾最多 3 個區。2026-07-27 截圖實測過長相，見 README。
    這裡任何一步找不到就印警告、直接跳過（不影響其他篩選條件照跑）。"""
    if not districts:
        return
    try:
        dd = page.get_by_placeholder("縣市區域").first
        await dd.click(timeout=5000)
        await page.wait_for_timeout(400)
        await page.get_by_text("南部", exact=True).first.click(timeout=5000)
        await page.wait_for_timeout(300)
        await page.get_by_text("高雄市", exact=True).first.click(timeout=5000)
        await page.wait_for_timeout(300)
        for d in districts[:3]:
            try:
                await page.get_by_text(d, exact=True).first.click(timeout=3000)
                await page.wait_for_timeout(300)
            except Exception as e:
                print(f"[WARN] 行政區選項「{d}」點不到，略過：{e}", file=sys.stderr)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    except Exception as e:
        print(f"[WARN] 行政區下拉操作失敗（不影響其他條件，但這次沒篩到行政區）：{e}",
              file=sys.stderr)


async def _select_parking(page: Page, mode: Optional[str], types: Optional[list[str]]) -> None:
    """車位篩選在「進階搜尋」展開面板裡：不限/無/有 三選一，選「有」才會出現
    車位型態下拉（坡道/平面、坡道/機械...多選）。mode 為 None 或 "不限" 時完全不動它
    （維持網站預設，比較快）。"""
    if not mode or mode == "不限":
        return
    try:
        await page.get_by_text("進階搜尋", exact=True).first.click(timeout=5000)
        await page.wait_for_timeout(600)
        await page.get_by_text(mode, exact=True).first.click(timeout=5000)
        await page.wait_for_timeout(300)
        if mode == "有" and types:
            await page.get_by_text("車位型態不限", exact=True).first.click(timeout=5000)
            await page.wait_for_timeout(300)
            for t in types:
                try:
                    await page.get_by_text(t, exact=True).first.click(timeout=3000)
                    await page.wait_for_timeout(200)
                except Exception as e:
                    print(f"[WARN] 車位型態選項「{t}」點不到，略過：{e}", file=sys.stderr)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)
    except Exception as e:
        print(f"[WARN] 車位篩選操作失敗（不影響其他條件，但這次沒篩到車位）：{e}",
              file=sys.stderr)


async def submit_search(
    page: Page,
    keyword: str,
    districts: Optional[list[str]] = None,
    parking_mode: Optional[str] = None,
    parking_types: Optional[list[str]] = None,
) -> None:
    await ensure_search_page(page)
    await _select_districts(page, districts or [])
    await _select_parking(page, parking_mode, parking_types)
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


async def search_cards(
    page: Page,
    keyword: str,
    districts: Optional[list[str]] = None,
    parking_mode: Optional[str] = None,
    parking_types: Optional[list[str]] = None,
) -> list[Card]:
    """一次掃完所有分頁、回傳全部卡片（不點進詳情頁）。給 --list-only 預覽用。"""
    await submit_search(page, keyword, districts, parking_mode, parking_types)
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
        if not await _click_next_page(page):
            return
        for _ in range(20):
            await page.wait_for_timeout(300)
            if (await _range_label(page)) != label_before:
                break
        await page.wait_for_timeout(900)
    print(f"[WARN] 翻頁達上限 {max_pages} 頁仍有下一頁，關鍵字太廣的話建議縮小範圍",
          file=sys.stderr)


def _parse_floors(floor_raw: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """floor_raw 例：「12樓/共17樓」、「9~10樓/共24樓」、「1~4樓/共4樓」。
    回傳 (最低樓, 最高樓, 總樓層)；抓不到格式就三個 None。
    ⚠️ 地下室寫法（B1）跟純土地案（沒有樓層）都會落在 None，呼叫端要當作『不知道』
    處理、不要當成不符合——查不到絕不擋是這個 repo 一貫的原則。"""
    m = re.search(r"(\d+)(?:\s*[~\-]\s*(\d+))?\s*樓\s*/\s*共\s*(\d+)\s*樓", floor_raw or "")
    if not m:
        return None, None, None
    f1 = int(m.group(1))
    f2 = int(m.group(2)) if m.group(2) else f1
    return min(f1, f2), max(f1, f2), int(m.group(3))


def _is_top_floor(floor_raw: str) -> bool:
    lo, hi, total = _parse_floors(floor_raw)
    if hi is None or total is None:
        return False
    return hi >= total


def passes_filters(
    c: Card,
    price_min: Optional[int],
    price_max: Optional[int],
    rooms_min: Optional[int],
    usage_keyword: Optional[str],
    area_keyword: str,
    usage_any: Optional[list[str]] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    area_ping_min: Optional[float] = None,
    area_ping_max: Optional[float] = None,
    main_area_ping_min: Optional[float] = None,
    main_area_ping_max: Optional[float] = None,
    land_ping_min: Optional[float] = None,
    land_ping_max: Optional[float] = None,
    baths_min: Optional[int] = None,
    floor_min: Optional[int] = None,
    floor_max: Optional[int] = None,
    unit_price_min: Optional[float] = None,
    unit_price_max: Optional[float] = None,
    exclude_top_floor: bool = False,
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
    if usage_any and not any(w in c.usage for w in usage_any):
        return False
    if age_min is not None and (c.age_years is None or c.age_years < age_min):
        return False
    if age_max is not None and (c.age_years is None or c.age_years > age_max):
        return False
    if area_ping_min is not None and (c.area_ping is None or c.area_ping < area_ping_min):
        return False
    if area_ping_max is not None and (c.area_ping is None or c.area_ping > area_ping_max):
        return False
    if main_area_ping_min is not None and (
        c.main_area_ping is None or c.main_area_ping < main_area_ping_min
    ):
        return False
    if main_area_ping_max is not None and (
        c.main_area_ping is None or c.main_area_ping > main_area_ping_max
    ):
        return False
    if land_ping_min is not None and (c.land_ping is None or c.land_ping < land_ping_min):
        return False
    if land_ping_max is not None and (c.land_ping is None or c.land_ping > land_ping_max):
        return False
    if baths_min is not None and (c.baths is None or c.baths < baths_min):
        return False
    if unit_price_min is not None and (
        c.unit_price_wan is None or c.unit_price_wan < unit_price_min
    ):
        return False
    if unit_price_max is not None and (
        c.unit_price_wan is None or c.unit_price_wan > unit_price_max
    ):
        return False
    if floor_min is not None or floor_max is not None:
        lo, hi, _total = _parse_floors(c.floor_raw)
        # 解析不出樓層（土地案、B1 之類）就當作不知道、不擋
        if lo is not None:
            if floor_min is not None and hi < floor_min:
                return False
            if floor_max is not None and lo > floor_max:
                return False
    if exclude_top_floor and _is_top_floor(c.floor_raw):
        return False
    return True


def apply_filters(
    cards: list[Card],
    price_min: Optional[int],
    price_max: Optional[int],
    rooms_min: Optional[int],
    usage_keyword: Optional[str],
    area_keyword: str,
    **extra_filters,
) -> list[Card]:
    out = [
        c
        for c in cards
        if passes_filters(c, price_min, price_max, rooms_min, usage_keyword, area_keyword, **extra_filters)
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
    # 正常是 lines[0]="承辦人聯絡資訊", lines[1]="承辦人"（標籤）, 接著才是資料。
    # 2026-07-29 實測踩到：有些案件（有「主攻人」跟「承辦人」兩顆負責人）會多插一顆
    # 「主攻人」標籤，原本固定 skip 2 行會被推擠，把標籤字串當成資料塞進 name_title/
    # phone 欄位（同物件另有委託那行因此印出「承辦人　主攻人　鄒秀娥...」這種亂碼）。
    # 改成明確濾掉已知的標籤字串，不再靠固定位置硬跳過。
    _LABELS = {"承辦人聯絡資訊", "承辦人", "主攻人"}
    data = [l for l in lines if l not in _LABELS]
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
    開詳情頁抓專員資訊 → 點分享（會跳站內「提醒」對話框，這裡自動點確定）→
    抓公開分享頁網址 → 關掉開出來的分頁、回到清單頁。"""
    detail_page = await _open_card_detail(list_page, card_index)
    await detail_page.wait_for_load_state("domcontentloaded")
    try:
        await detail_page.wait_for_function(
            "() => (document.body.innerText || '').includes('承辦人聯絡資訊')",
            timeout=10000,
        )
    except Exception:
        pass  # 等不到也繼續，_parse_agent 找不到區塊就回空的 Agent

    body_text = await detail_page.evaluate("() => document.body.innerText")
    agent = _parse_agent(body_text)

    share_url = None
    if not dry_run:
        try:
            # 2026-07-27 實測釐清整個流程：
            # 1) 點「分享」btn 一定要用 Playwright 的 locator.click()（真的滑鼠事件），
            #    JS el.click() 點得到但頁面沒反應（合成事件被這顆 Angular 按鈕忽略）。
            # 2) 點下去**不是**原生 JS confirm()，是站內 Angular Material 對話框
            #    （「提醒」：不動產經紀業管理條例提醒），要點框裡的「確定」才會真的
            #    開新分頁。截圖驗證過長相，見 PR 說明。
            share_btn = detail_page.get_by_text("分享", exact=True).first
            await share_btn.wait_for(state="visible", timeout=8000)
            await share_btn.click()

            confirm_btn = detail_page.get_by_text("確定", exact=True).first
            await confirm_btn.wait_for(state="visible", timeout=5000)
            async with detail_page.context.expect_page(timeout=10000) as share_info:
                await confirm_btn.click()
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
    """精簡版輸出（2026-07-29 使用者指定）：只留標題／社區名或路名／屋齡／開價／分享連結。

    專員姓名電話、店別、坪數、格局、編號都拿掉了——那些是自己作業時要查的，
    這份是要直接貼給客戶看的。要查專員聯絡方式改看 `output/` 存檔或自己開 i智慧。
    地址優先用社區名，沒有社區名（公寓、透天常見）才退用路名。"""
    lines = [f"◆ {'🆕 ' if card.is_new else ''}{card.case_name}"]

    where = (card.community or "").strip() or card.address.strip()
    if where:
        lines.append(where)

    if card.age_years is not None:
        lines.append(f"屋齡 {card.age_years} 年")

    if card.price_wan is not None:
        lines.append(f"開價 {card.price_wan} 萬")

    if share_url:
        lines.append(share_url)
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────


def get_or_open_page(ctx, url_substr: str, fresh_url: Optional[str] = None):
    """在既有 CDP context 裡找一個網址含 url_substr 的分頁，沒有就開新分頁。
    i智慧／房地共用同一個 CDP Chrome（同一組登入態）時都靠這個找對分頁。"""
    for pg in ctx.pages:
        if url_substr in pg.url:
            return pg
    return None  # 呼叫端自己 await ctx.new_page()（這裡不能是 async）


async def match_areas(
    page: Page,
    areas: list[str],
    districts: Optional[list[str]] = None,
    parking_mode: Optional[str] = None,
    parking_types: Optional[list[str]] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    rooms_min: Optional[int] = None,
    usage: Optional[str] = None,
    usage_any: Optional[list[str]] = None,
    age_min: Optional[int] = None,
    age_max: Optional[int] = None,
    area_ping_min: Optional[float] = None,
    area_ping_max: Optional[float] = None,
    main_area_ping_min: Optional[float] = None,
    main_area_ping_max: Optional[float] = None,
    land_ping_min: Optional[float] = None,
    land_ping_max: Optional[float] = None,
    baths_min: Optional[int] = None,
    floor_min: Optional[int] = None,
    floor_max: Optional[int] = None,
    unit_price_min: Optional[float] = None,
    unit_price_max: Optional[float] = None,
    exclude_top_floor: bool = False,
    newest_first: bool = False,
    limit: int = 15,
    dry_run: bool = False,
) -> list[tuple[Card, Optional[Agent], Optional[str]]]:
    """逐個關鍵字搜 i智慧，命中的開詳情頁抓專員/分享連結，全部關鍵字跑完後
    用 Card.fingerprint() 去重（同一戶被多店委託、或被多個關鍵字重複搜到都只留一筆）。
    `limit` 是**全部關鍵字加總**的處理上限，不是每個關鍵字各自 15 筆。

    `districts`／`parking_mode` 是網站端真篩選（跟 `--district`/`--parking` 一樣）；
    其餘（price/rooms/usage/age/area_ping/exclude_top_floor）都是 Python 端讀卡片文字
    後自己過濾，見 `passes_filters()`。"""
    all_entries: list[tuple[Card, Optional[Agent], Optional[str]]] = []
    for area in areas or [""]:
        if len(all_entries) >= limit:
            break
        remaining = limit - len(all_entries)
        await submit_search(page, area, districts, parking_mode, parking_types)
        if newest_first:
            await sort_by_newest(page)
        hit_this_area = 0
        async for page_no, raw in iter_pages(page):
            for idx, r in enumerate(raw):
                if hit_this_area >= remaining:
                    break
                card = _parse_card(r)
                if not passes_filters(
                    card, price_min, price_max, rooms_min, usage, area,
                    usage_any=usage_any, age_min=age_min, age_max=age_max,
                    area_ping_min=area_ping_min, area_ping_max=area_ping_max,
                    main_area_ping_min=main_area_ping_min,
                    main_area_ping_max=main_area_ping_max,
                    land_ping_min=land_ping_min, land_ping_max=land_ping_max,
                    baths_min=baths_min,
                    floor_min=floor_min, floor_max=floor_max,
                    unit_price_min=unit_price_min, unit_price_max=unit_price_max,
                    exclude_top_floor=exclude_top_floor,
                ):
                    continue
                print(
                    f"[INFO] 關鍵字「{area or '(不限)'}」第 {page_no} 頁第 {idx + 1} 張命中："
                    f"{card.case_name}"
                )
                agent, share_url = await open_detail_and_fetch(page, idx, dry_run=dry_run)
                all_entries.append((card, agent, share_url))
                hit_this_area += 1
                await page.wait_for_timeout(400)
            if hit_this_area >= remaining:
                break

    deduped = dedup_by_fingerprint(all_entries)
    dropped = len(all_entries) - len(deduped)
    if dropped:
        print(f"[INFO] 去重：{len(all_entries)} 筆 → {len(deduped)} 筆（{dropped} 筆是同一戶的重複委託/重複關鍵字）")
    return deduped


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
        page = get_or_open_page(ctx, "is.ycut.com.tw")
        if page is None:
            page = await ctx.new_page()

        districts = [d.strip() for d in args.district.split(",") if d.strip()] if args.district else []
        parking_types = (
            [t.strip() for t in args.parking_type.split(",") if t.strip()]
            if args.parking_type
            else []
        )
        areas = [a.strip() for a in args.area.split(",") if a.strip()] or [""]

        if args.list_only:
            all_cards: list[Card] = []
            for area in areas:
                cards = await search_cards(page, area, districts, args.parking, parking_types)
                all_cards.extend(
                    apply_filters(
                        cards,
                        price_min=args.price_min,
                        price_max=args.price_max,
                        rooms_min=args.rooms_min,
                        usage_keyword=args.usage,
                        area_keyword=area,
                    )
                )
            print(f"[INFO] 篩選後符合條件：{len(all_cards)} 筆")
            for c in all_cards[: args.limit or len(all_cards)]:
                print(format_block(c, None, None))
                print()
            return

        entries = await match_areas(
            page,
            areas,
            districts=districts,
            parking_mode=args.parking,
            parking_types=parking_types,
            price_min=args.price_min,
            price_max=args.price_max,
            rooms_min=args.rooms_min,
            usage=args.usage,
            limit=args.limit,
            dry_run=args.dry_run,
        )
        blocks = [format_block(card, agent, share_url) for card, agent, share_url in entries]
        print(f"[INFO] 實際處理 {len(blocks)} 筆")
        label = (args.area or (districts[0] if districts else "search")).replace(",", "_")[:40]
        output_blocks(blocks, label)


def output_blocks(blocks: list[str], label: str) -> None:
    """把結果印出來、存成 output/<時間戳>_<label>.txt、複製到剪貼簿。
    `buyer_match.py` CLI 跟 `run_customer_match.py`（房地客需 → i智慧）共用這段。"""
    if not blocks:
        print("[INFO] 沒有符合條件的物件")
        return

    output = "\n\n".join(blocks)
    print("\n" + "=" * 40 + "\n")
    print(output)

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_path = OUTPUT_DIR / f"{datetime.now():%Y%m%d_%H%M%S}_{label}.txt"
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
    ap.add_argument(
        "--area", default="",
        help="社區/路名關鍵字（可留空，跟 --district 擇一或併用），例：三多商圈；"
        "逗號分隔可給多個，會逐一搜尋再合併去重，例：文化皇家,文化中心華廈,警察一村",
    )
    ap.add_argument(
        "--district", default=None,
        help="行政區，逗號分隔最多 3 個（走網站真的行政區下拉，非文字比對），例：苓雅區,三民區"
    )
    ap.add_argument("--price-min", type=int, default=None, help="總價下限（萬）")
    ap.add_argument("--price-max", type=int, default=None, help="總價上限（萬）")
    ap.add_argument("--rooms-min", type=int, default=None, help="至少幾房")
    ap.add_argument("--usage", default=None, help="用途關鍵字，例：住宅（排除店面/透天等）")
    ap.add_argument(
        "--parking", default=None, choices=["無", "有"],
        help="車位篩選，不給就不篩（維持網站預設「不限」）"
    )
    ap.add_argument(
        "--parking-type", default=None,
        help=f"--parking 有 時才有作用，逗號分隔多選，可選：{'、'.join(_PARKING_TYPE_LABELS)}"
    )
    ap.add_argument("--limit", type=int, default=15, help="最多處理幾筆詳情頁（預設 15）")
    ap.add_argument("--list-only", action="store_true", help="只列出篩選後清單，不開詳情頁/不抓專員與分享連結（快速預覽用）")
    ap.add_argument("--dry-run", action="store_true", help="開詳情頁抓專員資訊，但不點分享（除錯用）")
    args = ap.parse_args()

    if not args.area and not args.district:
        print("[WARN] 沒給 --area 也沒給 --district，會掃整個高雄市，量很大、建議先加 --list-only 看筆數",
              file=sys.stderr)

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
