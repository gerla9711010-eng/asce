"""房地（agent.foundi.info）客需條件讀取：給一個客戶名字（+可選的子條件名），
把他存好的圈選範圍/篩選條件讀出來，轉成 buyer_match.py 能吃的關鍵字清單＋篩選參數。

房地只負責「範圍從哪裡來」，物件新不新完全不管——真正即時的案源永遠是回頭去
i智慧現查現撈（見 buyer_match.py 的 match_areas）。

DOM 選擇器是 2026-07-29 用瀏覽器實測房地頁面挖出來的（見對話紀錄），不是用猜的：
- 客需條件側欄：`div.nav-rail-item` 文字「客需條件」
- 客戶（folder）：`mat-nested-tree-node.folder`，展開用文字按鈕
- 子條件（entry）：`mat-nested-tree-node.entry` 底下 `button.entry-title`
- 列表/地圖切換：`mat-button-toggle-group[role="radiogroup"] mat-button-toggle`（第一個是列表）
- 篩選條件摘要：`div.text-body-s.filter-preview`
- 物件卡片：`div.panel-heading-container.hover-property-summary`
- 載入更多：文字符合 /更多|沒有更多/ 的 button，「沒有更多」代表已經到底
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Page

import buyer_match

FOUNDI_BASE_URL = "https://agent.foundi.info/tool/property/map"

# i智慧「縣市區域」下拉最多勾 3 個區（buyer_match._select_districts 的網站限制），
# 框選模式沒有明確區名可以解析、只能從候選清單反推涵蓋哪些區，所以也用同一個上限。
_MAX_DISTRICTS = 3

_BUILDING_TYPE_WORDS = ["住宅", "店面", "透天", "華廈", "大樓", "店住", "辦公"]


@dataclass
class FoundiNeed:
    customer: str
    need_name: str
    areas: list[str] = field(default_factory=list)
    # 社區關鍵字 -> [(路名, 這戶自己的樓層, 這戶自己的主建坪數), ...]。
    # 只有「主關鍵字是社區名」的候選才會有 entry——社區名在 i智慧 搜 0 筆時，
    # match_areas 會改搜路名，但額外要求樓層+主建坪數對得上（大樓保險機制，2026-08-01）。
    fallback_hints: dict[str, list[tuple[str, Optional[int], Optional[float]]]] = field(
        default_factory=dict
    )
    districts: list[str] = field(default_factory=list)
    filter_summary: str = ""
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    rooms_min: Optional[int] = None
    usage_words: list[str] = field(default_factory=list)
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    # 房地的「主建物坪數」對應 i智慧卡片的「主建」欄位（不是含公設的「建物」）
    main_area_ping_min: Optional[float] = None
    main_area_ping_max: Optional[float] = None
    land_ping_min: Optional[float] = None
    land_ping_max: Optional[float] = None
    baths_min: Optional[int] = None
    floor_min: Optional[int] = None
    floor_max: Optional[int] = None
    unit_price_min: Optional[float] = None
    unit_price_max: Optional[float] = None
    exclude_top_floor: bool = False
    require_parking: bool = False
    candidate_count: int = 0


_EXTRACT_FOUNDI_CARDS_JS = r"""
() => {
  const cards = [...document.querySelectorAll(
    'div.panel-heading-container.hover-property-summary')];
  return cards.map(c => ({
    title: c.querySelector('.title')?.textContent?.trim() || '',
    subtitle: c.querySelector('.subtitle')?.textContent?.trim() || '',
    community: c.querySelector('.anchor-minor')?.textContent?.trim() || '',
    text: (c.innerText || '').replace(/\s+/g, ' ').trim(),
  }));
}
"""


async def get_or_open_foundi_page(ctx) -> Page:
    for pg in ctx.pages:
        if "agent.foundi.info" in pg.url:
            return pg
    page = await ctx.new_page()
    await page.goto(FOUNDI_BASE_URL, wait_until="domcontentloaded")
    return page


class FoundiNotLoggedIn(RuntimeError):
    """房地登入態沒了（被導去登入頁）。單獨一個型別，讓排程那邊能推 LINE 叫人去登。"""


async def ensure_logged_in(page: Page) -> None:
    """確認房地是登入狀態，不是就丟 FoundiNotLoggedIn。

    ⚠️ 房地沒有 .env 帳密可以自動重登（i智慧 有），所以這裡只能「偵測 + 明講」。
    非做不可的原因：登入態掉了的時候，客需清單會是空的，整支腳本會一路跑完然後
    回報「0 筆」——看起來像今天沒新案，其實是根本沒登入。這個 repo 一再踩到
    「流程回報成功≠事情做到了」，寧可整批中止也不要靜靜撈到 0 筆。"""
    await page.goto(FOUNDI_BASE_URL, wait_until="domcontentloaded")
    # 房地也是前端 JS 判斷過期後才 client-side redirect，domcontentloaded 當下 URL 可能還沒變
    await page.wait_for_timeout(2000)
    cur = page.url or ""
    if "accounts/login" in cur or "/login" in cur or "/signin" in cur:
        raise FoundiNotLoggedIn(f"房地登入態過期，被導去 {cur}")

    # URL 沒變也可能是登入頁蓋在同一路徑上（或畫面還沒渲染完），再確認客需樹在不在。
    for _ in range(10):
        if await page.evaluate(
            "() => !!document.querySelector('mat-nested-tree-node.folder')"
            " || !!document.querySelector('div.nav-rail-item')"
        ):
            return
        await page.wait_for_timeout(1000)
    has_password_box = await page.evaluate(
        "() => !!document.querySelector('input[type=\"password\"]')"
    )
    if has_password_box:
        raise FoundiNotLoggedIn(f"房地停在登入頁（{cur}）")
    raise FoundiNotLoggedIn(f"房地頁面載入 10 秒後仍看不到客需側欄（目前網址 {cur}）")


async def _open_customer_need_sidebar(page: Page) -> None:
    """點開左側「客需條件」面板。

    ⚠️ 2026-07-29 實測踩到：這顆是切換開關（開⇄關），不是「保證打開」——上一輪執行
    如果把它點開了、面板沒被關掉，下一輪再點一次會變成關掉，害後面找不到客戶（曾經
    真的炸過：`RuntimeError: 房地客需條件裡找不到客戶`）。改成先看樹狀結構在不在
    DOM 上，已經展開了就不要再點。"""
    try:
        already_open = await page.evaluate(
            "() => !!document.querySelector('mat-nested-tree-node.folder')"
        )
        if already_open:
            return
        await page.get_by_text("客需條件", exact=True).first.click(timeout=5000)
        # ⚠️ 2026-07-30 踩到：舊版點完只等 500ms 就往下走，樹還沒渲染出來的時候
        # 呼叫端會拿到空清單（GUI 的三層下拉整個是空的，看起來像房地沒資料）。
        # 改成等到樹真的出現，最多 8 秒。
        for _ in range(16):
            await page.wait_for_timeout(500)
            if await page.evaluate(
                "() => !!document.querySelector('mat-nested-tree-node.folder')"
            ):
                return
        print("[WARN] 點開「客需條件」後 8 秒內看不到客戶樹", file=sys.stderr)
    except Exception as e:
        print(f"[WARN] 點「客需條件」失敗（可能面板已經開著，繼續往下走）：{e}", file=sys.stderr)


async def _select_customer_need(page: Page, customer: str, need: Optional[str]) -> str:
    """展開指定客戶的資料夾、點進去某個子條件（沒指定 need 就點第一個）。
    回傳實際點進去的子條件名稱。

    全部走 JS evaluate（不用 Playwright 的 get_by_text），因為子條件名稱後面常常跟著一顆
    未讀提醒數字的 `<mat-chip>`（例：「美術館」+ 徽章「9」），這個徽章是巢狀在同一個
    label span 裡、不是分開的元素——用 `.textContent` 撈會黏成「美術館9」，害文字比對
    失敗。這裡改成只取 label 自己的「直接文字節點」（忽略巢狀的 mat-chip 子元素），
    2026-07-29 用真實頁面驗證過兩種情況（有徽章／沒徽章）都對得上。"""
    result = await page.evaluate(
        """({customer, need}) => {
            const ownText = (el) => [...el.childNodes]
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('').trim();

            const folders = [...document.querySelectorAll('mat-nested-tree-node.folder')];
            const folder = folders.find(f => {
                const label = f.querySelector(':scope > div.folder-title span.folder-title-text');
                return label && ownText(label) === customer;
            });
            if (!folder) return {error: 'customer_not_found'};

            // 資料夾預設可能是收合的，展開一次讓底下的 entry 出現在 DOM 上
            const folderBtn = folder.querySelector(':scope > div.folder-title button.mdc-button');
            if (folderBtn) folderBtn.click();

            const entries = [...folder.querySelectorAll('mat-nested-tree-node.entry')];
            if (!entries.length) return {error: 'no_entries'};

            let target = null;
            if (need) {
                target = entries.find(e => {
                    const label = e.querySelector('button.entry-title span.mdc-button__label');
                    return label && ownText(label) === need;
                });
                if (!target) return {error: 'need_not_found', available: entries.map(e =>
                    ownText(e.querySelector('button.entry-title span.mdc-button__label')))};
            } else {
                target = entries[0];
            }

            const label = target.querySelector('button.entry-title span.mdc-button__label');
            const name = ownText(label);
            target.querySelector('button.entry-title').click();
            return {picked: name};
        }""",
        {"customer": customer, "need": need},
    )

    if result.get("error") == "customer_not_found":
        raise RuntimeError(f"房地客需條件裡找不到客戶「{customer}」")
    if result.get("error") == "no_entries":
        raise RuntimeError(f"客戶「{customer}」底下沒有任何子條件，請檢查房地那邊有沒有存過")
    if result.get("error") == "need_not_found":
        available = "、".join(result.get("available", []))
        raise RuntimeError(f"客戶「{customer}」底下找不到子條件「{need}」，現有的是：{available}")

    await page.wait_for_timeout(1200)
    return result["picked"]


async def list_group(page: Page, group_name: str) -> list[tuple[str, list[str]]]:
    """列出「客需條件」某個群組（A買／B買／C買／其他）底下所有客戶、以及各自存了
    哪些子條件名稱——給 `run_group_match.py` 批次跑一整個群組用。

    2026-07-29 實測確認：群組本身跟客戶是同一種 `mat-nested-tree-node.folder`
    （只是巢狀了一層：群組 folder → 客戶 folder → 客需 entry），選擇器沿用
    `_select_customer_need` 那套「只取直接文字節點」的寫法，同樣要避開子條件
    名稱裡可能夾帶的未讀提醒 `<mat-chip>` 徽章。"""
    await _open_customer_need_sidebar(page)
    result = await page.evaluate(
        """(groupName) => {
            const ownText = (el) => [...el.childNodes]
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('').trim();

            const allFolders = [...document.querySelectorAll('mat-nested-tree-node.folder')];
            const topLevel = allFolders.filter(
                f => !f.parentElement.closest('mat-nested-tree-node.folder'));
            const group = topLevel.find(f => {
                const label = f.querySelector(':scope > div.folder-title span.folder-title-text');
                return label && ownText(label) === groupName;
            });
            if (!group) return {error: 'group_not_found'};

            const groupBtn = group.querySelector(':scope > div.folder-title button.mdc-button');
            if (groupBtn) groupBtn.click();

            const customerFolders = [...group.querySelectorAll('mat-nested-tree-node.folder')];
            const customers = customerFolders.map(cf => {
                const label = cf.querySelector(':scope > div.folder-title span.folder-title-text');
                const name = label ? ownText(label) : '';
                const custBtn = cf.querySelector(':scope > div.folder-title button.mdc-button');
                if (custBtn) custBtn.click();
                const entries = [...cf.querySelectorAll('mat-nested-tree-node.entry')];
                const needs = entries.map(e => {
                    const l = e.querySelector('button.entry-title span.mdc-button__label');
                    return l ? ownText(l) : '';
                });
                return {name, needs};
            });
            return {customers};
        }""",
        group_name,
    )
    if result.get("error") == "group_not_found":
        raise RuntimeError(f"房地客需條件裡找不到群組「{group_name}」（應該是 A買/B買/C買/其他）")
    return [(c["name"], c["needs"]) for c in result["customers"] if c["name"]]


async def list_groups(page: Page) -> list[str]:
    """列出「客需條件」最上層的群組名稱（A買／B買／C買／其他…）。
    給 GUI 的群組下拉用——不寫死清單，房地那邊多開一組就自己會出現。"""
    await _open_customer_need_sidebar(page)
    return await page.evaluate(
        """() => {
            const ownText = (el) => [...el.childNodes]
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('').trim();
            const all = [...document.querySelectorAll('mat-nested-tree-node.folder')];
            return all
                .filter(f => !f.parentElement.closest('mat-nested-tree-node.folder'))
                .map(f => {
                    const label = f.querySelector(':scope > div.folder-title span.folder-title-text');
                    return label ? ownText(label) : '';
                })
                .filter(Boolean);
        }"""
    )


async def find_customer_group(page: Page, customer: str) -> Optional[str]:
    """這位客戶在房地「客需條件」裡屬於哪個群組（A買/B買/C買/其他）——
    給 `run_customer_match.py` 記 manifest 用（單一客戶查詢本來不知道群組，
    網頁看板要按群組分頁就需要這個）。找不到就回 None，不當成錯誤
    （查詢本身不靠這個，只是看板分類會歸到「未分類」）。"""
    for group in await list_groups(page):
        try:
            customers = await list_group(page, group)
        except RuntimeError:
            continue
        if any(name == customer for name, _needs in customers):
            return group
    return None


async def read_all_groups(page: Page) -> dict[str, list[tuple[str, list[str]]]]:
    """一次把整棵樹讀出來：{群組: [(客戶, [客需, ...]), ...]}。
    GUI 的三層下拉就是吃這個——讀一次就能離線切換群組/客戶，不用每次點都回去問房地。"""
    tree: dict[str, list[tuple[str, list[str]]]] = {}
    for group in await list_groups(page):
        try:
            tree[group] = await list_group(page, group)
        except RuntimeError as e:
            print(f"[WARN] 讀群組「{group}」失敗，跳過：{e}", file=sys.stderr)
    return tree


async def _switch_to_list_view(page: Page) -> None:
    try:
        await page.evaluate("""() => {
            const rg = document.querySelector('mat-button-toggle-group[role="radiogroup"]');
            if (!rg) return 'no_group';
            const first = rg.querySelector('mat-button-toggle button');
            if (!first) return 'no_button';
            first.click();
            return 'clicked';
        }""")
        await page.wait_for_timeout(1000)
    except Exception as e:
        print(f"[WARN] 切列表檢視失敗，續用目前畫面：{e}", file=sys.stderr)


async def _load_all_cards(page: Page, max_clicks: int = 30) -> list[dict]:
    """房地列表是「載入更多」按鈕（不是分頁），按到按鈕字樣變成「沒有更多」為止。
    ⚠️ 2026-07-29 實測發現頁面上同時有兩顆文字都含「更多」的按鈕——真正的分頁按鈕
    是 `button.load-more`（在 `.load-more-container` 裡），另一顆「更多 N」是完全無關的
    分類頁籤（class 是 `category-buttons`）。選錯會誤判分頁狀態，這裡鎖定 class 不能只認文字。"""
    for _ in range(max_clicks):
        state = await page.evaluate("""() => {
            const btn = document.querySelector('.load-more-container button.load-more');
            if (!btn) return 'no_btn';
            const label = btn.textContent.trim();
            if (label === '沒有更多') return 'done';
            btn.click();
            return 'clicked';
        }""")
        if state in ("done", "no_btn"):
            break
        await page.wait_for_timeout(700)
    return await page.evaluate(_EXTRACT_FOUNDI_CARDS_JS)


def _parse_range(summary: str, label: str, unit: str) -> tuple[Optional[float], Optional[float]]:
    """通用的『XX數字~數字單位』／『XX數字單位~不限』／『XX數字單位以上/以下』解析。
    2026-07-29 實測踩到房地同一種欄位在不同客需會有不同寫法（例：主建物坪數在采儒那筆是
    `28~99坪`，在 Jessica 那筆卻是 `25坪~不限`），regex 故意把單位字放在數字後面設成可選、
    上限也接受『不限』字面，兩種寫法都要吃得下去。"""
    m = re.search(
        rf"{label}\s*([\d.]+)\s*{unit}?\s*[~\-]\s*(不限|[\d.]+)\s*{unit}?", summary
    )
    if m:
        lo = float(m.group(1))
        hi = None if m.group(2) == "不限" else float(m.group(2))
        return lo, hi
    m = re.search(rf"{label}\s*([\d.]+)\s*{unit}?\s*以上", summary)
    if m:
        return float(m.group(1)), None
    m = re.search(rf"{label}\s*([\d.]+)\s*{unit}?\s*以下", summary)
    if m:
        return None, float(m.group(1))
    return None, None


def _parse_filter_summary(summary: str) -> dict:
    """從『買賣、框選、高雄市(3區)、大樓、住宅、總價1000~2100萬、...』這種摘要文字
    盡量抓出各項篩選條件，抓不到就是 None／False，呼叫端自己決定要不要補（不是致命錯誤）。"""
    price_min, price_max = _parse_range(summary, "總價", "萬")
    age_f_min, age_f_max = _parse_range(summary, "屋齡", "年")
    main_ping_min, main_ping_max = _parse_range(summary, "主建物坪數", "坪")
    land_ping_min, land_ping_max = _parse_range(summary, "土地坪數", "坪")
    floor_min, floor_max = _parse_range(summary, "樓層", "樓")
    bath_min, _bath_max = _parse_range(summary, "衛浴數", "衛")
    unit_price_min, unit_price_max = _parse_range(summary, "單價", "萬")

    # 房數同樣有多種寫法：`房數3~99房`（采儒/美術館）、`房數2房~不限`（Jessica）、`2房以上`
    rooms_min = None
    m = re.search(r"房數\s*(\d+)\s*房?\s*[~\-]\s*(?:不限|\d+\s*房?)", summary)
    if m:
        rooms_min = int(m.group(1))
    else:
        m = re.search(r"(\d+)\s*房以上", summary)
        if m:
            rooms_min = int(m.group(1))

    usage_words = [w for w in _BUILDING_TYPE_WORDS if w in summary]

    # 「地址」模式摘要會直接列區名（例：高雄市 鳳山區,三民區,...、），框選模式只給
    # 「高雄市(3區)」這種數量、沒有區名可解析——後者要靠候選清單反推（見 load_customer_need）。
    districts: list[str] = []
    m = re.search(r"高雄市\s+([^、]+)、", summary)
    if m:
        districts = [d.strip() for d in m.group(1).split(",") if d.strip()]

    return {
        "price_min": int(price_min) if price_min is not None else None,
        "price_max": int(price_max) if price_max is not None else None,
        "rooms_min": rooms_min,
        "usage_words": usage_words,
        "age_min": int(age_f_min) if age_f_min is not None else None,
        "age_max": int(age_f_max) if age_f_max is not None else None,
        "main_area_ping_min": main_ping_min,
        "main_area_ping_max": main_ping_max,
        "land_ping_min": land_ping_min,
        "land_ping_max": land_ping_max,
        "baths_min": int(bath_min) if bath_min is not None else None,
        "floor_min": int(floor_min) if floor_min is not None else None,
        "floor_max": int(floor_max) if floor_max is not None else None,
        "unit_price_min": unit_price_min,
        "unit_price_max": unit_price_max,
        "exclude_top_floor": "不要頂樓" in summary,
        "require_parking": "有車位" in summary,
        "districts": districts,
    }


def _parse_candidate_specs(text: str) -> tuple[Optional[int], Optional[float]]:
    """從候選卡片自己的 text 抓「這一戶自己的」樓層＋主建坪數，給大樓保險機制比對用
    （不是客需的範圍條件，是這一筆候選實際的值）。

    2026-08-01 實測卡片 text 長相：
    「...4樓/共20樓 總 56.26坪 主 40.44坪 地 4.64坪 36.6年 約1989 4房2廳2衛 大樓,住宅」
    樓層格式跟 i智慧 的「樓層」欄位一樣，直接沿用 `buyer_match._parse_floors`。
    抓不到就回 None——不確定的候選不參與保險比對（呼叫端只在至少一項有值時才建 hint）。"""
    lo, _hi, _total = buyer_match._parse_floors(text)
    m = re.search(r"主\s*([\d.]+)\s*坪", text)
    main_ping = float(m.group(1)) if m else None
    return lo, main_ping


def _derive_districts_from_candidates(raw_cards: list[dict]) -> list[str]:
    """框選模式的摘要沒有區名可解析，改從候選清單的 subtitle（例："高雄市 苓雅區 林泉街"）
    反推這個多邊形實際涵蓋哪些行政區——出現次數最多的前 `_MAX_DISTRICTS` 個區，
    這樣 i智慧 那邊才能加掛跟房地一樣的地理範圍限制，不是只靠社區/路名關鍵字間接narrow down。"""
    counter: Counter[str] = Counter()
    for c in raw_cards:
        subtitle = (c.get("subtitle") or "").strip()
        parts = subtitle.split()
        if len(parts) >= 2 and parts[1].endswith(("區", "鎮", "鄉", "市")):
            counter[parts[1]] += 1
    return [name for name, _ in counter.most_common(_MAX_DISTRICTS)]


async def load_customer_need(ctx, customer: str, need: Optional[str] = None) -> FoundiNeed:
    """主入口：給客戶名字（+可選子條件名），回傳可以直接餵給 buyer_match.match_areas 的
    FoundiNeed（社區/路名關鍵字清單 + 價格/房數/用途篩選）。"""
    page = await get_or_open_foundi_page(ctx)
    await _open_customer_need_sidebar(page)
    picked_need = await _select_customer_need(page, customer, need)
    await _switch_to_list_view(page)

    filter_summary = ""
    try:
        filter_summary = (
            await page.locator("div.text-body-s.filter-preview").first.text_content(timeout=5000)
        ) or ""
    except Exception as e:
        print(f"[WARN] 抓不到篩選摘要文字（不影響社區清單）：{e}", file=sys.stderr)

    raw_cards = await _load_all_cards(page)

    areas: list[str] = []
    seen = set()
    fallback_hints: dict[str, list[tuple[str, Optional[int], Optional[float]]]] = {}
    for c in raw_cards:
        community = (c.get("community") or "").strip()
        # 沒有社區名就退而求其次用路名（subtitle 最後一段，例："高雄市 苓雅區 光華一路" → 光華一路）
        subtitle = (c.get("subtitle") or "").strip()
        parts = subtitle.split()
        road = parts[-1] if parts else ""
        name = community or road
        if name and name not in seen:
            seen.add(name)
            areas.append(name)
        # 主關鍵字是社區名、而且路名抓得到又跟社區名不同 → 記一筆保險 hint
        # （社區名在 i智慧 搜 0 筆時，改搜路名 + 這一戶自己的樓層/坪數去對，見 match_areas）
        if community and road and road != community:
            floor, main_ping = _parse_candidate_specs(c.get("text") or "")
            if floor is not None or main_ping is not None:
                fallback_hints.setdefault(community, []).append((road, floor, main_ping))

    parsed = _parse_filter_summary(filter_summary)

    districts = parsed["districts"]
    if not districts:
        # 框選（多邊形）模式摘要沒有區名可解析，從候選清單反推涵蓋哪些區
        districts = _derive_districts_from_candidates(raw_cards)

    # i智慧 的「縣市區域」下拉最多勾 3 個，房地那邊卻可以設更多（賴秀真那筆設了 6 個區）。
    # 硬截斷會靜靜漏掉一半範圍，寧可整個不篩行政區、退回只靠社區/路名關鍵字narrow down
    # ——關鍵字本來就是從候選清單抽的，範圍不會超出房地圈的那塊，只是少一層保險。
    if len(districts) > _MAX_DISTRICTS:
        print(
            f"[WARN] 房地設了 {len(districts)} 個行政區（{'、'.join(districts)}），"
            f"超過 i智慧 下拉上限 {_MAX_DISTRICTS} 個 → 這次不篩行政區，"
            "改為只靠社區/路名關鍵字限制範圍",
            file=sys.stderr,
        )
        districts = []

    print(
        f"[INFO] 房地客需「{customer}/{picked_need}」讀到 {len(raw_cards)} 筆候選，"
        f"社區/路名去重後 {len(areas)} 個關鍵字，涵蓋行政區：{'、'.join(districts) or '(無法判斷)'}"
    )
    if filter_summary:
        print(f"[INFO] 房地篩選摘要：{filter_summary}")

    return FoundiNeed(
        customer=customer,
        need_name=picked_need,
        areas=areas,
        fallback_hints=fallback_hints,
        districts=districts,
        filter_summary=filter_summary,
        price_min=parsed["price_min"],
        price_max=parsed["price_max"],
        rooms_min=parsed["rooms_min"],
        usage_words=parsed["usage_words"],
        age_min=parsed["age_min"],
        age_max=parsed["age_max"],
        main_area_ping_min=parsed["main_area_ping_min"],
        main_area_ping_max=parsed["main_area_ping_max"],
        land_ping_min=parsed["land_ping_min"],
        land_ping_max=parsed["land_ping_max"],
        baths_min=parsed["baths_min"],
        floor_min=parsed["floor_min"],
        floor_max=parsed["floor_max"],
        unit_price_min=parsed["unit_price_min"],
        unit_price_max=parsed["unit_price_max"],
        exclude_top_floor=parsed["exclude_top_floor"],
        require_parking=parsed["require_parking"],
        candidate_count=len(raw_cards),
    )
