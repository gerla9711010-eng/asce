# 永慶博愛凱璿 n8n 廣告系統 — STATUS

> 規則：完成的項目直接刪掉，不留歷史。歷史看 git log。

最後更新：2026-07-23（KEIS 當天砍 API 導致線 A 停擺，晚間改完照片來源與資料補洞並完整跑通一輪；新增數字守門員與 API 體檢。詳見下方「KEIS 砍 API 後的修復」）
使用者：薛力瑜（永慶不動產 博愛凱璿加盟店）

---

## 系統入口

| 項目 | 值 |
|---|---|
| n8n URL | https://primary-production-68428.up.railway.app |
| 託管 | Railway（$5/月，Primary + Worker + Redis + Postgres）|
| LINE Bot | 工作助理 `@435awekw`（Channel ID `2009910157`）|
| LINE Webhook | `…/webhook/766bd943-f56c-4f78-b727-20e0d107d26a` |
| Notion 首頁 | 永慶博愛凱璿（`32ad184ddd7080c8ba7cf732d0747211`）|
| Notion 廣告資料庫 | `07ee845168b64f8a9b5682e5069c733b` |
| Notion 客戶名單 DB | `3eb9902989534654976e2f677b6957b3` |
| 薛力瑜 LINE userId | `Ufab42c56b2eb9b9a9ff18c367b85a6dd`（下架偵測 Push 用）|
| Drive 物件資料夾父層 | `1pn-tXugI8hlmVZJf2amWs9gnrj9-YhqC`（建檔器比對用）|
| FB 粉專 | 買房不費力,賣房好給力（`FB_PAGE_ID=1041868522352339`）|

## Credentials

| 名稱 | n8n ID | 類型 | 用途 |
|---|---|---|---|
| `Notion account` | `T62CHdfWuY9iXKWk` | Notion API | n8n Notion 節點 |
| `Notion API Token` | `edOz4T0LC6EP41Ug` | HTTP Header Auth | HTTP Request 打 Notion API |
| `LINE Channel Access Token` | `OmFzUGgZ1xIpAAP5` | HTTP Header Auth | LINE Reply / Push |
| `Gemini API Key` | `zTIA89pDJJs0Ad29` | HTTP Header Auth | Gemini（Header `x-goog-api-key`）|
| `Google Drive account` | `0TSq1oyqs4BHQxWa` | Google Drive OAuth2 | 建檔器列 Drive 子資料夾用 |
| `Google Calendar account` | **待建** | Google Calendar OAuth2 | 行事曆建立器寫 primary 行事曆用 |
| `FB Page Token` | 已建立 | HTTP Header Auth | `Authorization: Bearer <永久粉專權杖>`，發文/刪文用 |

## LINE 指令一覽

| 指令格式 | 行為 | 下游 workflow |
|---|---|---|
| `已撤除 YCxxx` | 標記該物件「已撤除確認 = true」 | `yc-property-remove` |
| `停` / `停 AGxxx` | 攔截待發廣告 | `yc-v3-stop` |
| `行事曆 <自由描述>` | Gemini 解析時間/地點/說明 → 建到 Google primary 行事曆 | `line-calendar-create` |
| `客戶 <自由描述>` | Gemini 抽姓名/電話/公司/需求 → 寫進 Notion 客戶名單 DB | `line-customer-create` |
| （純圖片，無前綴） | Gemini Vision 自動分類 → 轉發到行事曆或客戶 | `line-image-dispatcher` |
| `戰果` / `今日戰果` | 查 Notion 搶單名單 DB 今天的紀錄 → 回筆數＋名單（reply 不吃 push 額度） | `keis-battle-report`（🟡 待匯入） |
| `天氣` | 目前 router 認得但沒接下游（佔位） | — |

> **2026-07-23 退役**：`建檔 <網址>`、`發 YCxxx`、`生成文案 YCxxx` 三個舊指令已從 router 拔掉（下游 `YC 建檔器 v2` / `YC 發文線` / `文案重產器` 三支 workflow 一併停用）。建檔＋發文改由「廣告v3 掃描發文線」全自動處理，文案改用桌面 `/yc-ad` skill。打這三個指令現在會收到「無效指令」提示。要復原：n8n 把三支 workflow 開回 active，router 的 `解析 LINE 指令` 節點加回 create/publish/rewrite 三行對應（Switch 分支與轉發節點都還在，沒刪）。原始 router JSON 備份在 `backup/n8n-router-v3-before-2026-07-23.json`
>
> `行事曆`/`客戶` 也接受傳圖片（手寫便條、會議截圖、名片）→ 下游一律過 Gemini Vision 抽欄位。直接丟圖片沒前綴 → `line-image-dispatcher` 用 Gemini 分類後再轉發。

## Notion DB 欄位（`07ee845168b64f8a9b5682e5069c733b`）

> 2026-07-23 清掉 10 個舊系統遺留欄位：`公設坪數` `土地坪數` `附屬建物` `單價` `有無車位` `車位類型` `文案風格` `物件照片` `特色說明` `產生的文案`。刪除前的資料快照在 `backup/notion-ad-db-dropped-fields-2026-07-23.md`（只有前 4 筆舊資料有值）。v3 各線不寫這些欄；「單價」在 v3 是內部變數（餵數字守門員），本來就沒寫進 Notion。

| 欄位名 | 型別 | 備註 |
|---|---|---|
| 案名 | title | |
| 案件編號 | rich_text | 永慶兩碼英文 + 數字，例 `YC1835328` / `YE0095535`（前綴依物件不同）|
| 社區名稱 | rich_text | |
| 地址 | rich_text | |
| 建物類型 | select | `電梯大樓` / `華廈` / `公寓` / `透天` / `套房` / `店面` / `其他` |
| 格局 | rich_text | |
| 樓層 | rich_text | |
| 屋齡 | number | 單位：年 |
| 總價 | rich_text | 含「萬」字串，例 `338 萬` |
| 建物坪數 / 主建物坪數 | number | 單位：坪 |
| 粉專文案 | rich_text | yc-ad skill 寫入：粉專詳細版（200-300 字） |
| 社團文案 | rich_text | yc-ad skill 寫入：社團簡短版（50-80 字） |
| 粉專貼文連結 | url | yc-ad skill 寫入：使用者發完粉專回報後存進來 |
| 廣告貼文紀錄 | rich_text | yc-ad skill append：社團名 / 日期，多行 |
| KEIS同步 | select | `未同步`(預設) / `已同步`，KEIS 上架完成後 yc-ad skill 標 |
| 文案版本 | number | 每次重產 +1 |
| 來源連結 | url | 建檔器用這個判重 |
| 狀態 | select | `草稿` / `待發` / `已發布` / `下架` / `取消`（下架偵測 / v3 各線會 PATCH） |
| KEIS廣告ID | number | 線 D 寫入：KEIS `ad-tracker` 的 `adcase_id`，線 B 靠它關閉廣告 |
| 永慶官網連結 | url | 線 D 寫入：反查出來的 `buy.yungching.com.tw/house/{id}` |
| 專員 | rich_text | 線 A 寫入：KEIS `sales_agent_name`，帶看前要找誰就看這欄 |
| 所屬門市 | rich_text | 線 A 寫入：KEIS `store_name`（加盟體系各店）|
| 專員電話 | phone_number | ⚠️ **沒有任何 workflow 在寫這欄**（2026-07-23 全 n8n 掃過確認）。KEIS API 沒有（探過 14 個端點）；真來源是展售系統，見下方「專員電話來源」，登入已打通但**還沒接進線 A**。目前 5 筆是手動補的 |
| 要重發 | checkbox | **線 C 的名單就是這一欄**：打勾＝排隊等重發，**重發完系統自動取消勾**（一次性） |
| 最後重發時間 | date | 線 C 寫入：這次重發的日期。空的＝沒重發過，排最前面 |
| 重發次數 | number | 線 C 每重發一次 +1 |
| KEIS物件ID | number | 線 A 建列時寫入（KEIS `property-management` 的 `id`）。線 C 靠它回頭抓照片，**沒有這欄的舊資料不會被重發** |
| 已撤除確認 | checkbox | 撤除回報器標 true |
| 下架偵測時間 | date | |

## Notion 客戶名單 DB 欄位（`3eb9902989534654976e2f677b6957b3`）

| 欄位名 | 型別 | 備註 |
|---|---|---|
| 客戶姓名 | title | 建檔器**必填** |
| 電話 | phone_number | |
| 公司 | rich_text | |
| LINE / 通訊軟體 | rich_text | 注意欄位名含空格與斜線 |
| 來源 | select | `591` / `來電` / `介紹` / `路過/踩線` / `社群` / `其他`（預設 `其他`）|
| 狀態 | select | `新名單` / `已聯絡` / `可帶看` / `斡旋中` / `已成交` / `暫緩/無效` / `委託中屋主`（預設 `新名單`）|
| 標籤 | multi_select | `買方` / `賣方` / `租方` / `出租` / `急` / `預算已確認` |
| 備註 | rich_text | 建檔器會把抽到的「地址、職稱、需求、預算」全塞這（地址欄是 place 特殊型別，n8n 寫不進去）|
| 下次追蹤日 | date | YYYY-MM-DD |
| 地址 | place | **建檔器不寫**，改寫到備註 |
| 建立時間 / 最後更新 | 自動 | |
| 關聯物件 / 關聯募集線 | relation | 建檔器不寫 |

## 現有架構

```
LINE Webhook (/766bd943-…)                  ← 行動 / 手機場景
   ↓
LINE 指令分流 (Switch by command / message type)
   ├── remove   → 撤除回報器       (/yc-property-remove)
   ├── stop     → 廣告v3 煞車      (/yc-v3-stop)
   ├── calendar → 行事曆建立器     (/line-calendar-create)
   ├── customer → 客戶建檔器       (/line-customer-create)
   ├── battle   → KEIS 戰果查詢    (/keis-battle-report)
   └── image    → 圖片分流器       (/line-image-dispatcher)
                       └─ Gemini Vision 分類 → calendar 或 customer

   ✂️ 2026-07-23 拔掉：create（物件建檔器）/ rewrite（文案重產器）/ publish（YC 發文線）
      三支下游 workflow 已停用；Switch 分支與轉發節點保留但永遠不會被觸發

殭屍（active 但 10 天 0 執行，功能已被 yc-v3-removal 取代，暫留未刪）
   ├── YC 下架偵測線（yc-removal-detector）
   └── 撤除回報器（仍掛在 LINE「已撤除」指令上，會被觸發）

Claude Code Skill (.claude/skills/yc-ad/)    ← 桌面 / 深度操作場景
   /yc-ad 或自然語言「發 YCxxx」「同步 KEIS」等
       ↓
   讀 Notion 廣告 DB → 產粉專詳細版 + 社團簡短版 → 寫回 Notion
       ├── 後續對話：粉專連結回報 → PATCH 粉專貼文連結
       ├── 後續對話：「同步 KEIS」 → 產 KEIS 操作指令包讓使用者貼給瀏覽器擴充功能執行
       ├── 後續對話：「發到 X 社團」→ append 廣告貼文紀錄
       └── 後續對話：「已撤除 YCxxx」→ 標下架 + 附粉專連結提示手動刪 FB
```

## KEIS 廣告追蹤平台（凱璿業務系統）

- 網址：`https://keis.kshouse.com.tw/ad-tracker`
- **有內部 API**，n8n 線 D 已全自動同步（新增/關閉），不需要 UI 自動化。端點與欄位見 `docs/v3-ad-auto-workorder.md` §15
- **它自己就是下架偵測器**：新增廣告後 15～20 秒、之後每天凌晨會去抓 `adcase_url`，死了就標 `url_invalid=true` + `status_tags:['案件下架']`，活著就把官網現價填進 `url_price`
- 線 B 的下架判定**主要就是讀這個**（詳見工單 §17）。但 KEIS 只標記不會自動關閉，`is_expired` 要我們自己送

## KEIS 砍 API 後的修復（2026-07-23 晚間，線 A/C 都已改完）

**事故**：KEIS 當天下午把兩支 API 砍瘦——列表 40→18 欄、詳情 149→61 欄，**照片網址 `images` 整組消失**，連帶掉了 `official_url`／`age`／`school_info`／`layout`／`floor_info`（`seller_*` 屋主個資也一起被砍，研判是刻意收緊）。線 A 因此連續兩班空轉。

**修法（六項，都已上線並試跑驗過）**

| 改動 | 內容 |
|---|---|
| 照片改走 zip | `GET /api/v1/property-management/{id}/download-images` → 回 zip（實測 17 張 800KB）→ n8n `解壓照片`（Compression）→ `照片分筆`（拆成一筆一張、最多 10 張）→ `FB 上傳照片` 改 **multipart 傳檔案**（原本是給網址）。用現有 KEIS 自動登入 credential，不需新帳密 |
| official_url | 詳情沒了，改從**列表**帶進 `白名單清洗` |
| 格局／樓層 | 自己組：房廳衛只寫有數字的、土地類留白；樓層起訖不同寫 `1-4/4`、地下室寫 `B1`、缺總樓層就留白。拿 100 筆實測 vs KEIS 原本的字串：格局 91%、樓層 99% 一致，不一致的全是土地/廠房那類（我們留白，不亂寫）|
| 屋齡／學區 | KEIS 沒了 → 新節點 **`永慶官網補資料`**：沿用線 D 反查邏輯拿到 `buy.yungching.com.tw/house/{id}`，解析屋齡、學區，**並用官網公開版本交叉驗證格局樓層，不一致就留白＋記註記**。查不到就整個留白（不影響發文）|
| **數字守門員** | 新節點：文案裡每個數字都要在官方事實裡找得到（總價/坪數/樓層/賣點原文/footer），對不上就**不建 Notion、不發文**，改推 LINE。另擋「官方沒這筆資料就不准提」（屋齡/學區/格局/樓層），防 AI 腦補。⚠️ 比對前會先把網址拿掉（LINE 短網址裡有數字）|
| **API 體檢** | 撈完列表先檢查 `contract_no/case_price/image_count/official_url/is_active/houseol_created_at` 還在不在，缺了就**停這一輪 + LINE 告警**，不要再靜悄悄失敗 |

**Gemini prompt 也收緊了**：粉專文案只准四塊（標題／規格區／✨亮點 3-5 條／footer），**禁止自由描述段落**，亮點每條都必須改寫自 `feature_1~5`。原因：實測時它會自己從「全新未住」腦補出「屋齡 1 年」「前後陽台」。

**線 C 重發輪替同步改完**（吃同一套詳情 API 和照片來源），節點數 23。

## 專員電話來源（展售系統 es.houseol.com.tw）

KEIS 沒有專員電話，展售系統有。UI 路徑：關鍵字搜「物件編號純數字」→ 結果列「經紀員(聯絡資訊)」那格點下去 → 彈出「詳細聯絡資訊」。

**彈窗背後是一個乾淨的端點**（同源 GET，靠登入 cookie）：

```
GET https://es.houseol.com.tw/Function/FancyWindows.aspx?job=ContactDetails&HID=H888&MainID=<物件編號>
```

- `HID=H888` 固定（三個不同加盟店的案子都通）；`MainID` 直接用 KEIS 的 `contract_no`（例 `AG1927880`）
- 回傳一小段 HTML（約 4KB），文字長這樣：`詳細聯絡資訊 分店 分店十全博愛店/07-3131888 經紀人 經紀人詹屏/ 分店 … 經紀人2 經紀人2林源稐/0976205053 …`，最多四位經紀人，解析 `經紀人{n}<姓名>/<手機>` 即可
- ⚠️ 有些經紀人沒留手機（例：詹屏），那就退而用分店電話
**登入已打通（2026-07-23 實測成功）**：

```
1) GET  /login.aspx                → 撈 __VIEWSTATE / __VIEWSTATEGENERATOR / __EVENTVALIDATION
2) POST /login.aspx (form-urlencoded)
   __EVENTTARGET=LinkButton1  ←★ 關鍵，登入鈕是 ASP.NET LinkButton，少了它會靜靜退回登入頁
   __EVENTARGUMENT= / 三個 hidden 原樣帶回
   LoginType=4  HouseID=<店號>  MemberID=<帳號>  MemberPW=<密碼>
3) 帶著 cookie GET /Function/FancyWindows.aspx?job=ContactDetails&HID=H888&MainID=<編號>
```

- 登入成功會轉到 `/index.aspx`（頁面上那句 `請先輸入資料！` 是首頁的正常提示，不是登入失敗）
- credential 已建好：**`展售系統帳密（自動登入）`（id `ZkOT0wWz3oZTpdME`，Custom Auth）**，內容是 `{"body":{"LoginType","HouseID","MemberID","MemberPW"}}`，n8n 節點會自動併進 POST body
- 帳密同時也在本機 `.env`（`ES_HOUSE_ID` / `ES_MEMBER_ID` / `ES_MEMBER_PW`，已 gitignore）
- ⚠️ 還沒接進線 A（線 A 目前停用中）。要接的位置：`白名單清洗` 之後、`Notion 建待發列` 之前
- ⚠️ 照片不在型錄頁的原始 HTML 裡（raw HTML 只有 5 張店招/logo），是 JS 另外載的——想拿展售系統當照片來源還要再挖一層

## 各 workflow / skill 行為

- **撤除回報器**：抓 YC 編號 → Notion query → PATCH 已撤除確認 + 下架偵測時間 → LINE 回覆（仍在線，LINE「已撤除 YCxxx」會用到）
- **下架偵測（舊，yc-removal-detector）**：撈 `已撤除確認=false 且 狀態≠下架` → GET 來源連結 → 死了就 PATCH 狀態=下架 → Push/Reply 摘要。⚠️ active 但近 10 天 0 執行，功能已被線 B（yc-v3-removal）取代，可考慮停用
- ~~物件建檔器 / 文案重產器 / YC 發文線~~：**2026-07-23 已停用**，功能由「廣告v3 掃描發文線」+ 桌面 `/yc-ad` skill 取代
- **行事曆建立器**：`行事曆 ...` 文字或圖片 → Gemini 抽 `{title,start,end,location,description}` → Google Calendar primary 建 event → LINE 回覆（含失敗原因）
- **客戶建檔器**：`客戶 ...` 文字或圖片（名片）→ Gemini 抽姓名/電話/公司/LINE/來源/狀態/標籤/備註/追蹤日 → Notion 客戶名單 DB 新增 → LINE 回覆（失敗會帶 Notion API 原始錯誤）
- **圖片分流器**：純圖片無前綴 → 下載 → Gemini Vision 分類 → 轉發到行事曆建立器或客戶建檔器（分不出時預設客戶）
- **KEIS 待聯絡提醒**（`workflows/keis-contact-reminder.json`，🟢 已上線）：每天 09:00 查搶單名單（`4f28b915…`）→ 挑出「聯絡狀態=未聯絡 且 搶到滿 7 天剩≤2 天(含當天/已過期)」→ 有的話推一則 LINE 給薛力瑜，沒有就不推。判定 trunc 與 Notion「倒數天數」欄位一致（🟡剩2/1天/今天、🔴已過期）。搭配 Notion 視圖「🔔 待聯絡」
- **yc-ad skill**（`.claude/skills/yc-ad/SKILL.md`）：桌面 Claude Code 用。一個指令 `/yc-ad YCxxx` 或自然語言「發 YCxxx」即啟動全流程：產粉專+社團兩版文案 → 寫 Notion → 對話式接收後續粉專連結 / KEIS 同步指令 / 社團發文紀錄 / 撤除。文案規格詳見 SKILL.md：粉專 200-300 字，社團 50-80 字不放連結引導留言區，兩版下方都帶法規必填「凱璿誼峰不動產有限公司 + 字號」footer，聯絡人固定「薛先生 0912877583（同 LINE）+ LINE 連結 `https://line.me/ti/p/kg1pMk4vX8`」，不放 YC 編號 hashtag

## yc-ad skill 使用方式（桌面 Claude Code）

repo 根目錄開 Claude Code 後輸入：

```
/yc-ad YC1835328
```

或自然語言：「幫我發 YC1835328 的廣告」。

Skill 會自動：
1. 用 Notion MCP 查物件（Notion MCP 已配好 `mcp__3176f6b5-9ef6-46d2-817e-d3f5d081fd0f__notion-*`）
2. 產粉專詳細版 + 社團簡短版兩段文案，寫進 Notion `粉專文案` / `社團文案` / `文案版本` +1
3. 對話式接後續：
   - 你回粉專連結 → PATCH `粉專貼文連結` + `狀態` = 已發布
   - 你說「同步 KEIS」→ 吐操作指令包，貼給 Claude 瀏覽器擴充功能執行 → 回「KEIS 上架成功」→ PATCH `KEIS同步` = 已同步
   - 你說「發到 X 社團」→ append `廣告貼文紀錄`
   - 你說「已撤除」→ 標下架 + 附粉專連結提示手動刪 FB

## 獨立桌面工具（深度細節見各自 README）

跑在門市電腦、與 n8n 無關的獨立工具。這裡只記狀態，機制/gotcha/用法一律看各資料夾 README：

| 工具 | 狀態 | 深度文件 |
|---|---|---|
| **公買搶單** `scripts/keis/grab.py` | 🟢 已上線（門市電腦）。**搶單規則（2026-07-23 定案，別再改）**：只看編號最大的前 40 筆窗口（`WINDOW_SIZE`）＋建檔超過 10 天不搶（`MAX_AGE_DAYS`）＋二手回鍋不搶。窗口本身就是新舊把關，**拉大窗口＝拆掉把關**（當天試過，10 分鐘誤搶一筆建檔半年前的老案，已回退）。全池掃描每小時一次、輪流換帳號，**只寫 `inventory.csv` 稽核總帳，不進搶單流程**。篩選：只搶手機／排除公寓／預算上限<1000萬不搶／記行政區。分層時段 07:30-10:00／10:00-17:30／17:30-24:00／00:00-07:30(等同停止)。細節一律看 README | `scripts/keis/README.md`、`docs/keis-grab-hardening-and-filters.md` |
| ~~**KEIS 廣告上架** `scripts/keis/publish.py`~~ | ⚫ **已作廢**（2026-07-23）。它是用 Playwright 跑 KEIS UI 上架廣告，現在線 D 直接打 `POST /api/v1/adcases` 全自動做完，這支從沒實跑過就退場。桌面沒有這支，不用同步 | — |
| **自動簽到** `scripts/clockin/` | 🟢 已上線，2026-07-14 首跑成功 | `scripts/clockin/README.md` |
| **售屋表填寫** `scripts/sale-form/` | 🟢 2026-07-20 第4輪修完（PR#76，桌面已同步）：數字欄位全形→半形正規化（解決中文輸入法打不進小數點）、精靈加←→方向鍵導航、拿掉貸款三步確認視窗改回謄本全自動、租賃案 W3 單價改顯示「元/坪」。清單：桌面 `售屋表v3.6實測清單.md`。⚠️ 待門市拿真實案件實測；塗銷防護只用模擬文字驗過，遇真實含塗銷謄本要核對 log | `scripts/sale-form/README.md` |

## 廣告系統 v3（2026-07-21 拍板，取代 v2 的「LINE 手動建檔→發」流程）

> **▶ 執行入口：`docs/v3-ad-auto-workorder.md`**（含全部決策、KEIS API 實測、code）。不要重新討論架構。

**一句話**：n8n 定時打 KEIS API 撈整個加盟體系在售案 → Gemini 產文案 → LINE 預告 10 分鐘煞車視窗 → 沒喊停就自動發粉專多圖文 → 每天偵測 KEIS 下架就自動刪 FB 文。Notion 只當帳本。**絕不碰屋主個資**（白名單清洗節點強制）。

| 檔案 / n8n workflow | 用途 | 狀態 |
|---|---|---|
| `yc-v3-scan-publish.json`「廣告v3 掃描發文線」 | 線 A 掃描+發文+**同步 KEIS 廣告追蹤**（cron 09/11/13/15/17/19，每次 1 件） | 🟢 active（2026-07-23 晚間大改後重新啟用，見下方「KEIS 砍 API 後的修復」）|

**線 A 篩選規則（2026-07-23 使用者定案）**：在售 + 有照片 + **總價 ≥ 800 萬** + 官網上架 **30 天內優先**（`houseol_created_at` 新到舊排序；30 天內的都發過了才會往下墊較舊的案子，避免某天沒新案就整條線空轉）。面議價 9999 萬仍照舊排除。改在「篩選候選」Code 節點，常數 `MIN_PRICE` / `FRESH_DAYS`。
**線 C 重發規則（2026-07-23 定案）**：名單＝Notion `要重發` 打勾的那些（使用者自己勾）。**一次性，不是循環**：重發完系統自己把勾拿掉，要再發就再勾一次（使用者明講不想回頭手動清）。時段跟線 A 一樣六班但各晚 30 分（09:30/11:30/13:30/15:30/17:30/19:30），每班 1 件，所以勾 3 件當天就發完。每班挑 `最後重發時間` 最舊（或空的）一筆，重新打 KEIS 抓最新照片 → Gemini **換角度重寫**文案 → 發新粉專文 → **成功後才刪舊文** → Notion 換上新連結、`最後重發時間`=今天、`要重發`取消勾、`重發次數`+1 → LINE 推一則。⚠️ **不碰 KEIS 廣告追蹤**（KEIS 擋重複 `adcase_url`，工單 §15.1）。⚠️ 舊文一刪，社團的分享會失效，要重按新文的「分享」——LINE 通知裡有提醒。
**判重已改成整批一次**（2026-07-23，原本每個候選打一次 Notion＝40 次）：「查 Notion 是否已建」設 `executeOnce`，body 用 `or` 條件把 40 個案件編號一次送出；「標記是否已存在」改成用回傳結果建 Set 比對。只讀試跑驗過：1 次呼叫、40 候選、2 筆已建、38 筆待發。
| `yc-v3-removal.json`「廣告v3 下架偵測線」 | 線 B 下架偵測+刪 FB 文+**關閉 KEIS 廣告**（每天 08:00） | 🟢 active；判定段與關閉段都試跑驗過（見工單 §17）；只剩「真的有物件下架時刪 FB 文」那一步沒遇過 |
| `yc-v3-repost.json`「廣告v3 重發輪替線」 | 線 C 防貼文沉底：重產文案→發新粉專文→刪舊文→更新 Notion（09:30/11:30/13:30/15:30/17:30/19:30，每班 1 件） | 🟢 active；只讀試跑驗過（撈名單→挑件→KEIS詳情→產文案正常）。**FB 發/刪那段還沒真的跑過** |
| `yc-v3-stop.json`「廣告v3 煞車（停）」 | 煞車 webhook | 🟢 已啟用、實測攔截成功 |
| `line-command-router.json`「LINE 指令分流器 v3」 | 加「停」出口 | 🟢 已啟用（舊 router 已 Unpublish） |

**credential**：`KEIS 帳密（自動登入）`（id `KPvi4Z4Z8IAhKbdz`，**Custom Auth**，內容 `{"body":{"username":…,"password":…}}`）。線 A/B 每次跑都先自己打 `/auth/login` 拿新 token，**不需要再手動貼 token**。原因：KEIS 的 JWT 只活 8 小時，靜態 token 撐不過一天（詳見工單 §16）。舊的 `KEIS API Token`（`EaVn8LzS7lT5tW10`）已停用不再參考。

**2026-07-22 實測結果**：LINE「停」→ 攔截成功；線 A 手動跑 → KEIS 撈案、Gemini 產文案、Notion 建列、LINE 預告、10 分鐘後自動發粉專多圖文全部正常，第一篇真實廣告已上線（YG0158419）。過程修掉三個 bug：面議價 9999 萬會被當真實價（已加價格過濾）、完成通知抓錯欄位、FB permalink 格式。Notion「狀態」已加 `待發` / `取消` 兩個選項（select 選項不存在會讓 Notion query 直接回 400）。

**⚠️ n8n 操作方式**：n8n 2.x 把登入綁瀏覽器指紋，Claude 用**瀏覽器**做寫入會 401 並把使用者登出——不要再用瀏覽器操作 n8n。改走 **官方 Public API**：金鑰放 `.env`（`N8N_API_KEY`，已 gitignore，永不過期），端點 `$N8N_URL/api/v1/workflows`，Header `X-N8N-API-KEY`。可讀可寫可刪，Claude 現在能自己匯入/更新/清理 workflow。
備份：`backup/n8n-2026-07-22/`（清理前 43 支全量匯出，**只存本機、已 gitignore**——裡面有兩支舊 workflow 把 token 寫死在 JSON 裡，不能進 git）。2026-07-22 清掉 23 支停用舊複本，剩 20 支。
⚠️ 教訓：n8n 裡同名/亂名 workflow 很多，**判斷「哪一支在跑」要看 `/api/v1/executions`，不能只看名字**。例：真正在處理 LINE 圖片的是原本叫「My workflow 4」那支（已改名「圖片分流器（LINE 傳圖自動分類）」），同名的舊「圖片分流器」才是停用複本。

**線 D（KEIS 廣告追蹤同步）已完成**：規格與實作細節全在 `docs/v3-ad-auto-workorder.md` **§15**（API 端點、永慶連結反查法、節點接線）。重點三句：
- KEIS 廣告追蹤 API：新增 `POST /api/v1/adcases`（必填只有 title/url/member）、關閉 `PUT /api/v1/adcases/{id}` body `{"is_expired":true}`。**`closed_at` 是唯讀，送了會被無聲忽略**。
- 永慶官網連結 KEIS 完全沒存，只能反查 `buy.yungching.com.tw/list/{城市}-_c/{編號數字}_kw` 讀 JSON-LD。⚠️ **第一個候選永遠是假 id `4308114`，一定要開頁面驗證**。⚠️ **驗證條件是「路名 + 總價（或坪數±0.5）」，不要用案名**——各加盟店案名寫法太自由（例「三多商圈/正街上雙主臥/R8捷運樓店」而路名其實是永樂街），用案名比對會大量失敗。比價格前記得去掉千分位逗號（官網寫「1,150 萬」）。**反查失敗就留空，不要拿 houseol 網址頂替**：KEIS 廣告追蹤只收永慶/台慶連結，頂替會被 500 打槍，結果是廣告沒登記到 KEIS。
- Notion 廣告 DB 加了 `KEIS廣告ID`(number) 和 `永慶官網連結`(url) 兩欄。

**2026-07-23 補**：線 B 用臨時 webhook 複製節點試跑（只讀，沒動到真資料），修掉兩個會出事的問題——KEIS token 8 小時就過期導致全系統靜默停擺（§16）、以及「KEIS 查無此案」被當成下架會誤刪還在賣的物件的粉專貼文（§17）。線 A 也做了同樣的只讀試跑，自動登入→撈案→判重→洗個資都正常。

**試跑手法備忘**：n8n Public API 沒有「執行 workflow」端點。做法是**用 API 複製要測的節點到一支臨時 webhook workflow**（把 schedule trigger 換成 webhook、砍掉會寫入的節點、尾巴接一個 Code 節點回報結果），打完 webhook 就刪掉。這樣能在不碰真資料的情況下驗證線上邏輯。腳本在對話紀錄裡，要重做直接照這個模式。

**線 B 通知已瘦身（工單 §18）**：正常日子**一則都不推**。只有「粉專貼文刪除失敗」（附連結讓你點進去手刪）和「KEIS 撈不到資料」才推。社團是用粉專分享出去的，粉專文一刪分享自動失效，所以下架成功不需要通知你做任何事。順便修掉舊版會重複推 2～3 則的問題。⚠️「戰果」是搶單專用關鍵字，廣告不要用。

### ▶ 下次開工從這裡接

1. **專員電話接進線 A**：credential `展售系統帳密（自動登入）`（id `ZkOT0wWz3oZTpdME`）已建好、登入流程已實測通過，**但還沒接進線 A**。接點：`白名單清洗` 之後、`Notion 建待發列` 之前，抓到就寫 `專員電話` 欄。做法見上方「專員電話來源」。
2. **線 C 等一次真實驗證**：FB「發新文＋刪舊文」那段還沒實跑過。要測就把任一筆已發布物件的 `要重發` 打勾，下一個半點班次（09:30/11:30/…/19:30）就會跑（跑完 LINE 會推一則、勾勾自動取消）。
3. Notion 裡 4 筆 v2 時期的舊資料（YC1868705 / YC1868650 / YE0095535 / YC1835328）不在 KEIS，線 B 每天都會掃到它們然後略過。其中 YC1835328 已判定下架，明天 08:00 會被標成下架（那筆沒有粉專貼文，不會刪到東西）。

## 廣告系統 v2（已被 v3 取代，只留兩件還有效的事）

- **FB 永久權杖**：粉專「買房不費力,賣房好給力」，App `kaixuan-ad-bot`、系統使用者 `n8n-bot`，權杖在 n8n credential `FB Page Token`。設定教學 `docs/fb-token-setup.md`
- **社團不做自動化**（Groups API 已被 Meta 移除，瀏覽器機器人＝封號風險，使用者已同意不碰）。撒網靠粉專原文「分享」，原文一刪分享自動失效
- 其餘 v2 設計與建置步驟見 `docs/v2-handoff.md` 與 git log

**未來候補**：多開一個 IG 帳號專發廣告。使用者要先自己把新 IG 轉商業帳號、綁粉專＋開權限，之後才接 n8n（IG 是兩段式 container→publish）。目前卡在帳號還沒建，不用主動催。

## 其他待辦（非廣告系統）

- **LINE 訊息瘦身案收尾（2026-07-16 已全部部署）**：3 支 workflow（心跳檢查/戰果查詢/router 加「戰果」）已由 Claude 直接操作瀏覽器匯入 n8n 並發布，webhook 外部實測全過（「戰果」路由 200、心跳 200）。grab.py 已上線（16:30 重啟，心跳每 10 分鐘一跳）。剩兩件：①使用者拿手機 LINE 打「戰果」做最終驗收（需真實 replyToken，模擬不了）②n8n 裡有兩個同名「LINE 指令分流器」，舊的已停用未刪，新版跑幾天沒問題後刪掉舊的。教訓：在 Windows 終端機用 curl 直接帶中文測 webhook 會被 cp950 弄壞字元造成假故障，測中文 payload 一律用 python httpx。
- **公買搶單對帳未驗的一半**：07-14 對帳時薛力瑜 7 筆已在 KEIS 頁面逐號驗過；**周珈伊 7 筆需登入她帳號才能核**（密碼類使用者自己登入）。
