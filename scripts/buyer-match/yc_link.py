"""從房地（agent.foundi.info）候選物件卡片裡，抓「本次銷售刊登」清單中連到永慶房屋
官網（buy.yungching.com.tw）的連結——給買方配案批次流程用。不是每一戶都有永慶在賣，
沒有就回 None，呼叫端自己決定要不要略過。

⚠️ 沒有公開 JSON API 可以直接查：試過 `/dataapi/property/get/<id>/`（點卡片展開時
瀏覽器實際打的那條），直接用 fetch() 重放回 403 "No token to authenticate"——前端
帶了一個不在 cookie/localStorage 裡的 authorization token（Angular in-memory，沒有
window.ng 全域可以挖，production build 拿不到 DI），只能走點卡片展開這條路（詳見
2026-08-16 對話紀錄）。逐筆點開很慢，這是取捨後的結果，見 `run_yc_links.py` 的
`--limit`。

DOM 結構是 2026-08-16 用瀏覽器實測 agent.foundi.info/tool/property/list 挖出來的：
- 候選卡片：`div.panel-heading-container`（跟 `foundi_need.py` 用同一顆選擇器，
  2026-08-08 改版後的 class，見該檔案開頭說明）
- 點卡片的 `.title` 展開／收合（純 CSS 狀態切換，不會離開頁面、不是連結）
- 「本次銷售刊登」清單的區塊標題文字是「本次銷售刊登共有 N 筆」，這段文字所在的
  `.section-header` 的 parentElement 就是整個清單（標題＋架上/架下切換＋刊登項目＋分頁）
- 清單預設篩「架上」（`mat-radio-button` 文字含「架上」要是 `.mat-radio-checked`）。
  ⚠️ 這個一定要確認，抓到「架下」的連結等於帶看撲空——2026-08-16 討論時特別提醒的坑。
- 每筆刊登項目是一個 `<a href>`，判斷是不是永慶用 host 是不是 `buy.yungching.com.tw`
  （比認中文徽章「永慶」穩：徽章文字之後改版可能換位置/換 class，host 不會變，而且
  同一個徽章「591」底下可能混著永慶加盟店刊登在 591、不是永慶官網直連，容易誤判）
- 每筆刊登項目是一個 `fd-listing-info` 元素（連結就在裡面），完整標題在
  `.list-title-text`、開價在 `.list-price-title .highlight-text`——這兩個從候選卡片
  的 `.title`（會截斷）拿不到，但反正要點開卡片才找得到連結，順便一起抓，不用多打
  一次網路請求（2026-08-17 加，給看板複製用）
- 清單本身會分頁（`mat-paginator`），永慶那筆不一定在第一頁，翻頁上限見
  `MAX_PAGES_PER_CANDIDATE`（試過這個分頁沒有「每頁顯示數量」下拉可以加大，
  只能翻頁）
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import Page

# 一個客需可能有幾十到幾百筆候選（房地圈選範圍大的話），逐筆點開查很慢，只查前
# N 筆——跟舊版 i智慧 那條 `--limit 15` 同樣的取捨（見 `git log -p -- run_group_match.py`）。
DEFAULT_MAX_CANDIDATES = 15

# 「本次銷售刊登」清單分頁，一頁看起來固定 5 筆，翻到第 5 頁已經涵蓋 25 筆刊登
# 紀錄，這個規模的重複刊登很少見，翻不完就當作「這戶目前沒有永慶在賣」。
MAX_PAGES_PER_CANDIDATE = 5


@dataclass
class YcLinkResult:
    index: int
    title: str
    subtitle: str
    yc_link: Optional[str]
    note: str = ""  # 抓不到的原因，成功就是空字串
    full_title: str = ""  # 完整（不截斷）標題，只有 yc_link 有值時才有
    price: str = ""  # 開價，例："3,700萬"，只有 yc_link 有值時才有


_FIND_YC_LINK_JS = """
async (cardEl, maxPages) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // ⚠️ 一定要把搜尋範圍鎖在這張卡片自己的 mat-expansion-panel 裡，不能查整份文件：
  // 展開過的卡片內容不會從 DOM 移除（mat-expansion-panel 用動畫隱藏，不是真的拔掉），
  // 用 document.querySelectorAll 永遠只抓得到第一張展開過的卡片（2026-08-17 實測踩過：
  // 3 筆不同候選全部回傳同一個連結，都是卡片 0 的舊資料）。
  const panel = cardEl.closest('mat-expansion-panel');
  if (!panel) return {status: 'no_panel'};

  // ⚠️ 點卡片收合（Playwright 端做的事）只是動畫藏起來，Angular Material 的
  // mat-expansion-panel 內容第一次渲染後永遠留在 DOM 裡（官方行為，省下次展開的
  // 重新渲染成本）。逐筆查完就把這張卡的內容 DOM 挖掉，不然掃一整個群組（幾十位
  // 客戶、每人可能十幾筆候選）DOM 會一直長，長到把渲染拖垮、CDP 連線斷掉
  // （2026-08-17 實測踩過：跑到第 8 位客戶斷線）。查完不管有沒有找到都要挖，
  // 所以包一層 finish() 統一在回傳前處理。
  const finish = (result) => {
    const body = panel.querySelector('.mat-expansion-panel-body');
    if (body) body.remove();
    return result;
  };

  // 卡片點開後 Angular 要跑一輪 change detection 才會把清單渲染出來，
  // 立刻查詢常常撲空——重試幾次，不要一次就判定「沒有刊登清單」。
  let section = null;
  for (let attempt = 0; attempt < 8 && !section; attempt++) {
    for (const el of panel.querySelectorAll('.section-header')) {
      if ([...el.childNodes].some(
        n => n.nodeType === 3 && n.textContent.includes('本次銷售刊登共有')
      )) {
        section = el.parentElement;
        break;
      }
    }
    if (!section) await sleep(400);
  }
  if (!section) return finish({status: 'no_section'});

  const onMarketBtn = [...section.querySelectorAll('mat-radio-button')]
    .find(b => b.textContent.includes('架上'));
  if (onMarketBtn && !onMarketBtn.classList.contains('mat-radio-checked')) {
    onMarketBtn.querySelector('input,.mdc-radio__native-control')?.click();
    await sleep(500);
  }

  for (let page = 0; page < maxPages; page++) {
    const found = [...section.querySelectorAll('a[href]')]
      .find(a => a.href.includes('yungching.com.tw'));
    if (found) {
      const row = found.closest('fd-listing-info');
      const fullTitle = row?.querySelector('.list-title-text')?.textContent.trim() || '';
      const price = row?.querySelector('.list-price-title .highlight-text')?.textContent.trim() || '';
      return finish({status: 'ok', href: found.href, fullTitle, price});
    }

    const nextBtn = section.querySelector(
      'mat-paginator button.mat-mdc-paginator-navigation-next'
    );
    if (!nextBtn || nextBtn.disabled) break;
    nextBtn.click();
    await sleep(700);
  }
  return finish({status: 'not_found'});
}
"""


async def collect_yc_links(
    page: Page, max_candidates: int = DEFAULT_MAX_CANDIDATES
) -> list[YcLinkResult]:
    """假設 page 是 `foundi_need.load_customer_need()` 跑完之後的畫面（客需已選好、
    候選卡片已經在列表檢視載入好了）。逐筆點開前 max_candidates 筆卡片抓永慶連結。

    一筆卡片失敗（逾時／結構跟預期不一樣）不該讓整批停下來，記下原因繼續下一筆——
    這個 repo 反覆踩過「一筆炸掉、整批空手而歸」的坑（見 `foundi_need.py` 開頭說明）。
    """
    cards = page.locator("div.panel-heading-container")
    total = await cards.count()
    n = min(total, max_candidates)
    results: list[YcLinkResult] = []

    for i in range(n):
        card = cards.nth(i)
        title = (await card.locator(".title").first.text_content() or "").strip()
        subtitle = (await card.locator(".subtitle").first.text_content() or "").strip()

        try:
            await card.locator(".title").first.click(timeout=5000)
        except Exception as e:
            results.append(YcLinkResult(i, title, subtitle, None, f"點卡片失敗：{e}"))
            continue

        try:
            outcome = await card.evaluate(_FIND_YC_LINK_JS, MAX_PAGES_PER_CANDIDATE)
            status = outcome.get("status")
            if status == "ok":
                results.append(YcLinkResult(
                    i, title, subtitle, outcome["href"],
                    full_title=outcome.get("fullTitle", ""), price=outcome.get("price", ""),
                ))
            elif status == "no_section":
                results.append(YcLinkResult(i, title, subtitle, None, "沒有刊登清單"))
            elif status == "no_panel":
                results.append(YcLinkResult(i, title, subtitle, None, "找不到卡片所屬的展開面板"))
            else:
                results.append(
                    YcLinkResult(i, title, subtitle, None, "翻完刊登清單沒找到永慶")
                )
        except Exception as e:
            results.append(YcLinkResult(i, title, subtitle, None, f"讀取刊登清單失敗：{e}"))
            print(f"[WARN] 第 {i} 筆（{title}）讀取失敗：{e}", file=sys.stderr)

        # 收合卡片再進下一筆——同時開好幾張會讓後面筆的畫面位置一直位移。
        try:
            await card.locator(".title").first.click(timeout=3000)
            await page.wait_for_timeout(300)
        except Exception:
            pass  # 收不起來不影響已經抓到的資料，繼續下一筆

    return results
