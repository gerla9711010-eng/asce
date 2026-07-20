# 永慶博愛凱璿 n8n 廣告系統 — STATUS

> 規則：完成的項目直接刪掉，不留歷史。歷史看 git log。

最後更新：2026-07-20（新增動態物件資料源 `yc-feed.json`：GET `/webhook/yc-feed` 回 Notion 已發布物件的乾淨 JSON，供外部系統即時讀；🟡 待使用者匯入。v2 發文線/下架線/router v2 三支 JSON 已就緒待匯入測試，見 `docs/v2-handoff.md`）
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
| 動態物件 feed | `…/webhook/yc-feed`（GET，回已發布物件 JSON；`?status=已發布/all`、`?case=YCxxx`）🟡 待匯入 |

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
| `建檔 <永慶網址>` | 抓 HTML → AI 解析 → 寫進 Notion（新建或 PATCH，文案版本 +1） | `yc-property-create` |
| `已撤除 YCxxx` | 標記該物件「已撤除確認 = true」 | `yc-property-remove` |
| `生成文案 YCxxx <風格描述>` | 用 Notion 既有資料 + 自由風格描述，AI 重產文案（版本 +1） | `yc-rewrite-copy`（**桌面端改用 `/yc-ad` skill**，本指令暫保留） |
| `發 YCxxx` | 缺文案先 Gemini 產粉專+社團版 → 抓照片 → FB Graph API 發多圖粉專貼文 → 回寫 permalink/狀態=已發布/KEIS同步=未同步 → LINE Reply 帶社團版 | `yc-fb-publish`（🟡 待匯入測試） |
| `行事曆 <自由描述>` | Gemini 解析時間/地點/說明 → 建到 Google primary 行事曆 | `line-calendar-create` |
| `客戶 <自由描述>` | Gemini 抽姓名/電話/公司/需求 → 寫進 Notion 客戶名單 DB | `line-customer-create` |
| （純圖片，無前綴） | Gemini Vision 自動分類 → 轉發到行事曆或客戶 | `line-image-dispatcher` |
| `戰果` / `今日戰果` | 查 Notion 搶單名單 DB 今天的紀錄 → 回筆數＋名單（reply 不吃 push 額度） | `keis-battle-report`（🟡 待匯入） |
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
- **KEIS 待聯絡提醒**（`workflows/keis-contact-reminder.json`，🟢 已上線）：每天 09:00 查搶單名單（`4f28b915…`）→ 挑出「聯絡狀態=未聯絡 且 搶到滿 7 天剩≤2 天(含當天/已過期)」→ 有的話推一則 LINE 給薛力瑜，沒有就不推。判定 trunc 與 Notion「倒數天數」欄位一致（🟡剩2/1天/今天、🔴已過期）。搭配 Notion 視圖「🔔 待聯絡」
- **動態物件資料源**（`workflows/yc-feed.json`，🟡 待匯入）：GET `/webhook/yc-feed`（webhook 直接回應，非 LINE）→ 查 Notion 廣告資料庫 → 攤平成乾淨 JSON feed 給外部系統（FB/官網/591）即時讀。5 節點：webhook→組查詢→查 Notion（`Notion API Token` cred）→整理→回 JSON。query 參數 `?status=已發布`(預設)/`all`、`?case=YCxxx` 取單筆；單頁上限 100，超過看回應的 `has_more`。欄位對齊 Notion DB（案名/編號/社區/地址/類型/格局/樓層/屋齡/總價/單價/各坪數/車位/特色/粉專文案/粉專貼文連結/來源連結/物件照片[]/狀態/最後更新）。🟡 **格式與消費端未定**：目前只吐 JSON，若要接 FB 動態廣告 catalog 需再加 CSV/XML feed 格式（待使用者確認消費端）
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
| **公買搶單** `scripts/keis/grab.py` | 🟢 已上線（門市電腦），全天分層輪詢 | `scripts/keis/README.md` |
| **KEIS 廣告上架** `scripts/keis/publish.py` | 🟡 待第一次實跑驗 selector，見下方待辦 | `scripts/keis/README.md` |
| **自動簽到** `scripts/clockin/` | 🟢 已上線，2026-07-14 首跑成功 | `scripts/clockin/README.md` |
| **售屋表填寫** `scripts/sale-form/` | 🟢 2026-07-20 第4輪修完（PR#76，桌面已同步）：數字欄位全形→半形正規化（解決中文輸入法打不進小數點）、精靈加←→方向鍵導航、拿掉貸款三步確認視窗改回謄本全自動、租賃案 W3 單價改顯示「元/坪」。清單：桌面 `售屋表v3.6實測清單.md`。⚠️ 待門市拿真實案件實測；塗銷防護只用模擬文字驗過，遇真實含塗銷謄本要核對 log | `scripts/sale-form/README.md` |

## 廣告系統 v2 改造計畫（2026-07-15 拍板，取代所有舊的廣告流程待辦）

> **▶ 執行入口：`docs/v2-handoff.md`**——建置步驟、規格、驗收全在那，照著跑，不要重新討論架構。FB 金鑰教學在 `docs/fb-token-setup.md`。本節只留設計依據。

**背景**：使用者實際用過 v1（yc-ad skill 對話式流程）後結論：人工介入太多太雜（一物件 11+ 次）。拍板重造，目標「上架 3 次接觸、下架 0~1 次，全部在 LINE 完成」。

**目標流程**：
1. LINE 傳「建檔 <永慶連結>」→ n8n 解析 + 產文案（粉專版+社團版）→ LINE 推預覽
2. 使用者回「發」→ n8n 走 FB Graph API 自動發粉專文（自動附物件照片）→ permalink 存回 Notion、狀態=已發布 → LINE 推社團版文案
3. 社團分層：重點 2-3 團手動貼原生文（效果），其餘社團用 FB「分享」功能撒網（分享自動帶原文照片文案；粉專原文刪除時分享全部自動失效）
4. KEIS：門市電腦駐守腳本（同 grab.py 模式）輪詢 Notion「已發布且未同步」→ 自動上架 → 標已同步。無人工
5. 下架：n8n cron 偵測永慶連結失效 → FB API 自動刪粉專文（分享連帶全滅）→ Notion 標下架 → LINE 通知 + 原生文手刪清單

**建置順序**（每步獨立可用）：
1. ~~FB 永久 token~~ **已完成**（2026-07-16）：粉專「買房不費力,賣房好給力」，App `kaixuan-ad-bot`、系統使用者 `n8n-bot`（Employee，僅指派此粉專內容權限+此 App），權杖存進 n8n Credential `FB Page Token`
2. n8n 發文線（**下一步**）：建檔 workflow 接「文案 → LINE 預覽 → 回『發』→ Graph API 發文（多照片）→ 存 permalink」
3. 下架線：`yc-removal-detector` 接「Graph API 刪 post」+ 重新啟用 cron（舊的「等 6/1 額度」理由早已過期）
4. KEIS 駐守：先驗證 `scripts/keis/publish.py` 能跑（`--login` 一次 → `publish.py YC1868650`，YC1868650 尚未上架），再改成輪詢模式駐店電腦
5. 清舊：砍 `yc-rewrite-copy` workflow + router `生成文案` 出口；yc-ad skill 降級為維修工具（調文案/查狀態），改寫 SKILL.md

**設計原則**：Notion 仍是唯一真相中心；「發」的人工確認保留（廣告法規責任，穩定後可拿掉）；FB 社團不做任何自動化（Groups API 已被 Meta 移除，瀏覽器機器人=封號風險，使用者已同意不碰）；社團記錄只記原生文（分享文隨原文自動失效，不用記）。

**LINE 額度控管（拍板：不升付費方案；2026-07-15 補充調整：非急迫，隨發文線順做）**：
- 適用範圍縮小：三級制**只套用廣告系統新訊息**，現有其他工具通知使用者要求原樣保留，不動
- 廣告系統訊息設計：使用者觸發的對話（建檔預覽、發布確認、社團記錄）一律 Reply（免費）；成功不推播只寫 Notion；主動推播只剩下架+故障（月估 10-15 則）
- 守門員（隨建置發文線順手做）：推播前查 LINE quota consumption API，>160 則擋非緊急、>190 則只留故障+下架。保證零付費
- **搶單通知瘦身另場討論**（使用者反映自動配送通知太多，是最大額度來源）；討論前請使用者先看 LINE OA Manager 本月推播用量，>150 則就提前談
- 退路（真不夠再啟用，零元）：非緊急通知改走 Notion @mention（Notion App 免費推播）

## 其他待辦（非廣告系統）

- **LINE 訊息瘦身案收尾（2026-07-16 已全部部署）**：3 支 workflow（心跳檢查/戰果查詢/router 加「戰果」）已由 Claude 直接操作瀏覽器匯入 n8n 並發布，webhook 外部實測全過（「戰果」路由 200、心跳 200）。grab.py 已上線（16:30 重啟，心跳每 10 分鐘一跳）。剩兩件：①使用者拿手機 LINE 打「戰果」做最終驗收（需真實 replyToken，模擬不了）②n8n 裡有兩個同名「LINE 指令分流器」，舊的已停用未刪，新版跑幾天沒問題後刪掉舊的。教訓：在 Windows 終端機用 curl 直接帶中文測 webhook 會被 cp950 弄壞字元造成假故障，測中文 payload 一律用 python httpx。
- **公買搶單 — 收斂分層時段邊界**（機制全在 `scripts/keis/README.md`）：連看幾天 `logs/` + `page1_track.csv` + `appearances.csv`，確認熱門時段（06:00-10:00／18:00-24:00）邊界抓得對不對，樣本夠了再跟使用者一起調窄/調寬。
  - 未驗的另一半：07-14 對帳時薛力瑜 7 筆已在 KEIS 頁面逐號驗過；**周珈伊 7 筆需登入她帳號才能核**（密碼類使用者自己登入）。
