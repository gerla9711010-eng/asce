# 永慶博愛凱璿 n8n 廣告系統 — STATUS

> 規則：完成的項目直接刪掉，不留歷史。歷史看 git log。

最後更新：2026-05-12（新增行事曆/客戶建檔 + 圖片分流）
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

## Credentials

| 名稱 | n8n ID | 類型 | 用途 |
|---|---|---|---|
| `Notion account` | `T62CHdfWuY9iXKWk` | Notion API | n8n Notion 節點 |
| `Notion API Token` | `edOz4T0LC6EP41Ug` | HTTP Header Auth | HTTP Request 打 Notion API |
| `LINE Channel Access Token` | `OmFzUGgZ1xIpAAP5` | HTTP Header Auth | LINE Reply / Push |
| `Gemini API Key` | `zTIA89pDJJs0Ad29` | HTTP Header Auth | Gemini（Header `x-goog-api-key`）|
| `Google Drive account` | `0TSq1oyqs4BHQxWa` | Google Drive OAuth2 | 建檔器列 Drive 子資料夾用 |
| `Google Calendar account` | **待建** | Google Calendar OAuth2 | 行事曆建立器寫 primary 行事曆用 |

## LINE 指令一覽

| 指令格式 | 行為 | 下游 workflow |
|---|---|---|
| `建檔 <永慶網址>` | 抓 HTML → AI 解析 → 寫進 Notion（新建或 PATCH，文案版本 +1） | `yc-property-create` |
| `已撤除 YCxxx` | 標記該物件「已撤除確認 = true」 | `yc-property-remove` |
| `生成文案 YCxxx <風格描述>` | 用 Notion 既有資料 + 自由風格描述，AI 重產文案（版本 +1） | `yc-rewrite-copy` |
| `行事曆 <自由描述>` | Gemini 解析時間/地點/說明 → 建到 Google primary 行事曆 | `line-calendar-create` |
| `客戶 <自由描述>` | Gemini 抽姓名/電話/公司/需求 → 寫進 Notion 客戶名單 DB | `line-customer-create` |
| （純圖片，無前綴） | Gemini Vision 自動分類 → 轉發到行事曆或客戶 | `line-image-dispatcher` |
| `天氣` | 目前 router 認得但沒接下游（佔位） | — |

> 風格描述可以是任意自由文字，例如「精簡」、「投資客口吻強調學區」。`生成文案` 跟 `YC` 之間空白可省略，全形/半形空白都接受。
>
> `行事曆`/`客戶` 也接受傳圖片（手寫便條、會議截圖、名片）→ 下游一律過 Gemini Vision 抽欄位。直接丟圖片沒前綴 → `line-image-dispatcher` 用 Gemini 分類後再轉發。

## Notion DB 欄位（`07ee845168b64f8a9b5682e5069c733b`）

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
| 單價 | rich_text | |
| 建物坪數 / 主建物坪數 / 公設坪數 / 土地坪數 | number | 單位：坪 |
| 附屬建物 | rich_text | |
| 有無車位 | checkbox | |
| 車位類型 | select | `坡道平面` / `機械` / `法定` / `無` |
| 特色說明 | rich_text | |
| 文案風格 | select | `首購溫馨` / `投資自用`（重產器**不會**改這欄） |
| 產生的文案 | rich_text | |
| 文案版本 | number | 每次更新 +1 |
| 來源連結 | url | 建檔器用這個判重 |
| 物件照片 | files | 寫 Drive 資料夾 external URL |
| 狀態 | select | `草稿` / `下架` …（下架偵測會 PATCH 成 `下架`） |
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
LINE Webhook (/766bd943-…)
   ↓
LINE 指令分流 (Switch by command / message type)
   ├── create   → 物件建檔器       (/yc-property-create)
   ├── remove   → 撤除回報器       (/yc-property-remove)
   ├── rewrite  → 文案重產器       (/yc-rewrite-copy)
   ├── calendar → 行事曆建立器     (/line-calendar-create)
   ├── customer → 客戶建檔器       (/line-customer-create)
   └── image    → 圖片分流器       (/line-image-dispatcher)
                       └─ Gemini Vision 分類 → calendar 或 customer

下架偵測 (yc-removal-detector)
   ├── cron 09:00 Asia/Taipei → LINE Push 摘要
   └── 手動 webhook /yc-check-removed → LINE Reply 摘要
```

- **物件建檔器**：抓 HTML → Gemini 解析 + 文案 → 列 Drive 子資料夾 → 案名正規化比對（只留中英數字）→ 查 Notion 判重（來源連結）→ 新建或 PATCH 更新（`文案版本` +1，`物件照片` 寫 Drive 連結）→ LINE 回覆
- **撤除回報器**：抓 YC 編號 → Notion query → PATCH 已撤除確認 + 下架偵測時間 → LINE 回覆
- **下架偵測**：撈 `已撤除確認=false 且 狀態≠下架` → GET 來源連結 → HTTP ≥400 或關鍵字（已下架/物件不存在/已成交…）→ PATCH 狀態=下架 → Push/Reply 摘要
- **文案重產器**：LINE 指令 `生成文案 YC123 風格描述` → 查 Notion（案件編號）→ Gemini 依自由風格重產 → PATCH `產生的文案` + `文案版本` +1 → LINE 回覆完整新文案
- **行事曆建立器**：`行事曆 ...` 文字或圖片 → Gemini 抽 `{title,start,end,location,description}` → Google Calendar primary 建 event → LINE 回覆（含失敗原因）
- **客戶建檔器**：`客戶 ...` 文字或圖片（名片）→ Gemini 抽姓名/電話/公司/LINE/來源/狀態/標籤/備註/追蹤日 → Notion 客戶名單 DB 新增 → LINE 回覆（失敗會帶 Notion API 原始錯誤）
- **圖片分流器**：純圖片無前綴 → 下載 → Gemini Vision 分類 → 轉發到行事曆建立器或客戶建檔器（分不出時預設客戶）

## 接下來要做

> 下架偵測 cron 目前在 n8n 上 disabled，等 6/1 LINE 月額度重置後手動打開即可（手動 webhook 不吃 push 額度，現在就能測）。

### 行事曆 / 客戶建檔上線前要做（使用者操作）

1. **在 n8n 匯入 4 個 workflow**（一律「開新空白 workflow → import JSON」，不要蓋舊的）：
   - `workflows/line-calendar-create.json`
   - `workflows/line-customer-create.json`
   - `workflows/line-image-dispatcher.json`
   - `workflows/line-command-router.json`（**蓋掉**舊的，因為 Switch 多了 3 個出口）
2. **建 Google Calendar OAuth2 credential**（n8n → Credentials → New → "Google Calendar OAuth2 API"），命名 `Google Calendar account`，授權 calendar scope。
3. **回到 `line-calendar-create` workflow，把「Google Calendar 建立事件」節點的 credential 改成上面建好的那個**（JSON 裡是 placeholder `REPLACE_ME`）。
4. **把 Notion 客戶名單 DB 分享給 Notion integration**（Notion DB 頁面右上 ⋯ → Connections → 加你的 integration），不然 Notion API 會回 `object_not_found`。
5. **4 個 workflow 一律按 Active 開**。
6. 測試：
   - 文字：傳 `行事曆 明天下午2點 王先生看屋 三民區建工路123號 帶權狀`
   - 文字：傳 `客戶 王大明 0912345678 找三民3房預算1500 介紹`
   - 圖片：傳一張名片照片（應自動進客戶建檔）
   - 圖片：傳一張寫日期+事件的便條（應自動進行事曆）
