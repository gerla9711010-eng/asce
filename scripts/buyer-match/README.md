# 買方配案

## 現況（2026-08-17）

從 foundi（`agent.foundi.info`）的「客需條件」候選卡片，逐筆展開查「本次銷售刊登」清單，
抓 host 是 `buy.yungching.com.tw` 的永慶官網連結。沒有公開 JSON API 可以直接查（試過
`/dataapi/property/get/<id>/`，前端帶的 authorization token 不在 cookie/localStorage
裡，重放會 403），只能逐筆點卡片展開，細節見 `yc_link.py` 開頭註解。

跑完會：
1. 存成 `output/*.txt`（單一子條件一份）
2. 用 `seen_store.py` 記住每個客戶/子條件之前看過哪些連結，這次新出現的標🆕
3. 整輪結果寫成 `output/latest_run.json`
4. 呼叫 `build_static_view.py` 重產 `output/配案看板.html`
5. 預設自動部署到 Cloudflare Pages（`https://yc-tools.pages.dev/buyer-match/`，
   `robots.txt` 擋收錄但沒有帳密保護）——`--no-publish` 可以只留本機檔案不部署

看板功能：
- 按群組（A買／B買／C買／其他⋯）分頁籤切換，不是一頁塞所有客戶
- 單筆／整批（該子條件）／複製全部（目前分頁籤那組）三種一鍵複製
  （`navigator.clipboard`，失敗會退回長按選字框）
- 複製內容是「標題＋開價＋連結」三行一筆，不是裸連結；多筆一起複製時筆與筆之間空一行
- 新出現的案子標🆕（`seen_store.py` 判斷，同一個連結對同一個客戶/子條件不會重複標）

⚠️ **刻意沒做**：LINE 推播、排程自動跑。現在是手動跑指令，要接排程/通知是另一輪的事。

## 用法

```powershell
cd scripts/buyer-match
py -m pip install -r requirements.txt

# 第一次用之前：雙擊桌面「買方配案」開真 Chrome 的捷徑（沒有就讓腳本自己開一個），
# 登入 agent.foundi.info 一次——CDP port 9223 專屬 profile，跟平常用的 Chrome 是分開的

python run_yc_links.py A買                          # 整組全部跑，跑完自動部署
python run_yc_links.py A買 --customer 采儒            # 只跑這組裡的某個客戶
python run_yc_links.py A買 --customer 采儒 --need 美術館   # 只跑單一子條件
python run_yc_links.py A買 --limit 10                # 每個子條件最多查前 10 筆候選（預設 15）
python run_yc_links.py A買 --no-publish              # 只重產看板 HTML，不部署
```

## 部署機制

`update.py`（`~/kh-market-tool/`）統一管 `yc-tools.pages.dev` 這個 Cloudflare Pages
專案的三個站（`/yc-calc/`／`/kh-market/`／`/buyer-match/`），細節見
`docs/reference.md`「公開網頁：Cloudflare Pages 發布鏈路」。`update.py` 的
`BUYER_MATCH_HTML` 常數指到這支 repo 的 `output/配案看板.html`（2026-08-17 改的，
原本指桌面工具，08-14 隨 i智慧 一起刪掉了）。

## 檔案

| 檔 | 用途 |
|---|---|
| `chrome_cdp.py` | CDP port 9223 登入態基礎設施（開/偵測專屬 Chrome） |
| `foundi_need.py` | 讀房地客需條件（客戶存好的圈選範圍/篩選條件），轉成關鍵字+篩選參數 |
| `yc_link.py` | 逐筆展開候選卡片、抓永慶連結的核心邏輯 |
| `run_yc_links.py` | 批次入口：跑群組/客戶/子條件、存檔、產看板、部署 |
| `build_static_view.py` | 把 `output/latest_run.json` 轉成看板 HTML（分頁籤／複製格式） |
| `seen_store.py` | 記住每個客戶/子條件看過哪些連結，標新出現的（🆕） |
| `output/`／`state/` | 查詢結果／去重記憶（已 gitignore） |
