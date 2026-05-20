# 永慶博愛凱璿 n8n 廣告系統 — STATUS

> 規則：完成的項目直接刪掉，不留歷史。歷史看 git log。

最後更新：2026-05-13（新增 yc-ad Claude Code Skill，承接社團廣告 SOP）
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
| `生成文案 YCxxx <風格描述>` | 用 Notion 既有資料 + 自由風格描述，AI 重產文案（版本 +1） | `yc-rewrite-copy`（**桌面端改用 `/yc-ad` skill**，本指令暫保留） |
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
| 文案風格 | select | `首購溫馨` / `投資自用` / `急售吸睛` / `AI判斷`（重產器**不會**改這欄） |
| 產生的文案 | rich_text | 早期單一文案欄（被 `粉專文案`+`社團文案` 取代，新流程不寫這欄） |
| 粉專文案 | rich_text | yc-ad skill 寫入：粉專詳細版（200-300 字） |
| 社團文案 | rich_text | yc-ad skill 寫入：社團簡短版（50-80 字） |
| 粉專貼文連結 | url | yc-ad skill 寫入：使用者發完粉專回報後存進來 |
| 廣告貼文紀錄 | rich_text | yc-ad skill append：社團名 / 日期，多行 |
| KEIS同步 | select | `未同步`(預設) / `已同步`，KEIS 上架完成後 yc-ad skill 標 |
| 文案版本 | number | 每次重產 +1 |
| 來源連結 | url | 建檔器用這個判重 |
| 物件照片 | files | 寫 Drive 資料夾 external URL |
| 狀態 | select | `草稿` / `已發布` / `下架`（下架偵測 / yc-ad 撤除流程會 PATCH） |
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
   ├── create   → 物件建檔器       (/yc-property-create)
   ├── remove   → 撤除回報器       (/yc-property-remove)
   ├── rewrite  → 文案重產器       (/yc-rewrite-copy)  ← 將被 yc-ad skill 取代，暫並存
   ├── calendar → 行事曆建立器     (/line-calendar-create)
   ├── customer → 客戶建檔器       (/line-customer-create)
   └── image    → 圖片分流器       (/line-image-dispatcher)
                       └─ Gemini Vision 分類 → calendar 或 customer

下架偵測 (yc-removal-detector)
   ├── cron 09:00 Asia/Taipei → LINE Push 摘要
   └── 手動 webhook /yc-check-removed → LINE Reply 摘要

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
- 性質：加盟店內網系統，**無 API、無 Webhook、無 LINE 通知設定**
- 偵測邏輯：自家偵測永慶網址失效後自動把廣告移到「已關閉廣告」分頁
- 整合方式：yc-ad skill 產出操作指令包 → 使用者貼給 Claude 瀏覽器擴充功能（Computer Use / Operator）執行 UI 自動化
- 關鍵 UI 技巧：「+ 新增廣告」表單有「自動填入」按鈕，貼永慶網址後按一下會自動抓標題/地址/價格，省去欄位 mapping
- 不靠 KEIS 做下架通知：保留 `yc-removal-detector` 自家 cron，KEIS 純當業務 dashboard

## 各 workflow / skill 行為

- **物件建檔器**：抓 HTML → Gemini 解析 + 文案 → 列 Drive 子資料夾 → 案名正規化比對（只留中英數字）→ 查 Notion 判重（來源連結）→ 新建或 PATCH 更新（`文案版本` +1，`物件照片` 寫 Drive 連結）→ LINE 回覆
- **撤除回報器**：抓 YC 編號 → Notion query → PATCH 已撤除確認 + 下架偵測時間 → LINE 回覆
- **下架偵測**：撈 `已撤除確認=false 且 狀態≠下架` → GET 來源連結 → HTTP ≥400 或關鍵字（已下架/物件不存在/已成交…）→ PATCH 狀態=下架 → Push/Reply 摘要
- **文案重產器**：LINE 指令 `生成文案 YC123 風格描述` → 查 Notion（案件編號）→ Gemini 依自由風格重產 → PATCH `產生的文案` + `文案版本` +1 → LINE 回覆完整新文案。**將被 yc-ad skill 取代**，新流程改用桌面 Claude Code 走 skill；LINE 指令暫保留並存，等 skill 用順手後再砍
- **行事曆建立器**：`行事曆 ...` 文字或圖片 → Gemini 抽 `{title,start,end,location,description}` → Google Calendar primary 建 event → LINE 回覆（含失敗原因）
- **客戶建檔器**：`客戶 ...` 文字或圖片（名片）→ Gemini 抽姓名/電話/公司/LINE/來源/狀態/標籤/備註/追蹤日 → Notion 客戶名單 DB 新增 → LINE 回覆（失敗會帶 Notion API 原始錯誤）
- **圖片分流器**：純圖片無前綴 → 下載 → Gemini Vision 分類 → 轉發到行事曆建立器或客戶建檔器（分不出時預設客戶）
- **yc-ad skill**（`.claude/skills/yc-ad/SKILL.md`）：桌面 Claude Code 用。一個指令 `/yc-ad YCxxx` 或自然語言「發 YCxxx」即啟動全流程：產粉專+社團兩版文案 → 寫 Notion → 對話式接收後續粉專連結 / KEIS 同步指令 / 社團發文紀錄 / 撤除。文案規格詳見 SKILL.md（粉專 200-300 字含 `#YCxxx` hashtag、社團 50-80 字不放連結引導留言區）

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

## 接下來要做

- 下架偵測 cron 目前在 n8n 上 disabled，等 6/1 LINE 月額度重置後手動打開（手動 webhook `/yc-check-removed` 不吃 push 額度，現在就能測）
- yc-ad skill 跑第一個真實物件後，回頭調 SKILL.md 的文案 prompt 規格（粉專口氣、社團排版變化度）
- 等 yc-ad skill 用順手後，砍掉 n8n 的 `yc-rewrite-copy` workflow + router 的 `生成文案` 出口
- **KEIS 自動化改用腳本**（Playwright/Selenium + Python）取代 Claude 瀏覽器擴充功能，理由：擴充功能太燒 token。輸入：永慶網址 + FB 貼文連結 + 案件編號 → 自動填表送出。完成後 SKILL.md 4b 改為呼叫腳本（n8n webhook 或 LINE 指令觸發），不再產操作指令包
- **FB 粉專自動排程（B 路線）**：Graph API + n8n workflow，產文案後直接寫 Notion「排程時間」欄 → cron 到時間自動 PO 文 → 拿回貼文連結 → 標已發布。前置：開 Meta for Developers App、拿粉專長效 Page Access Token、加 Notion「排程時間」欄。本次使用者暫採 A 路線（Meta Business Suite 手動排程），等順手後再做 B
  - **2026-05-20 設定進度**：建了 Meta App `1464556941566881`（YC粉專自動發文，消費者類型），加了「管理粉絲專頁所有內容」use case，建了 FB Login for Business 組態 `1001789349267297`（含 4 個 pages_* 權限）。OAuth URL 跑出來一直跳「Sorry, something went wrong」原因待查
  - **下次接續**：先試 Graph API Explorer 拿 token（新 app 已有 4 個 pages_* 權限預設可選），URL `https://developers.facebook.com/tools/explorer/` → 選 `YC粉專自動發文` app → Generate Access Token 看權限選單。如果 Explorer 也不行，研究 FBL4B 文件看 OAuth URL 缺什麼參數
  - 舊 App `1950187462277347`（YC博愛凱璿廣告，事業類型）已棄置，不用
