# 永慶博愛凱璿 n8n 廣告系統 — STATUS

> 規則：完成的項目直接刪掉，不留歷史。歷史看 git log。

最後更新：2026-07-14（公買搶單監控起跑 07:30→06:00，接住早釋出並讓上架偵測量得到真實釋出時刻；待今晚重啟 watch 生效）
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

## 售屋表自動填寫工具（`scripts/sale-form/`）

桌面 GUI 工具（與 n8n 無關，獨立執行）：謄本 PDF → 自動查 104 社區 + 高雄市使用分區 → 確認視窗逐項核對 → 產出售屋表 Excel。

- 檔案：`gui_main.py`（GUI＋填表）、`bot_104.py`（104 自動登入＋使用分區查詢）、`confirm_wizard.py`（確認視窗）
- **本機才有、未進版控**（在使用者本機資料夾）：`parser.py`、`template/sale_template.xltx`、`output/`、`啟動工具.vbs`；套件 `selenium`/`openpyxl` + Chrome
- 104 登入帳密寫死在 `bot_104.py`（`ACCOUNT`/`PASSWORD`）→ 已進 git 歷史，要公開或換密碼時注意
- **⚠️ 實際運行版在本機 `OneDrive\桌面\不動產售屋表工具_v3.4\zipinspect\`，git 這份只是副本**。改 git 不會影響本機在跑的工具，兩邊要同步改。
- **`fill_excel()` 存檔前必須 `wb.template = False`**：範本是 `.xltx`，openpyxl 讀進來會記住範本旗標，不關掉存出的 `.xlsx` 內部類型會是 `template.main+xml`，嚴格版 Excel（別台電腦）直接拒開。已修（git + 本機兩份都改）。
- 狀態：全流程已實測通過（左營/三民多筆）。未驗證的座標：工業區 K42「乙種工」寫法、車位多層細項（地上/地下、平面/機械、上中下橫移、入口）——需使用者拿對應案件實際開 Excel 確認

## 自動簽到工具（`scripts/clockin/`）

每天 9:00–10:00 之間不規則時間，自動到 houseol 房管系統差勤面板簽到，完成後推 LINE 回報。

- 檔案：`clockin.py`（Playwright；**自動登入**：讀 `.env` 店代號/帳號/密碼登入，登入頁無驗證碼）、`install-task.ps1`（Windows 工作排程 09:00 觸發 + RandomDelay 1h）、`workflows/clockin-notify.json`（webhook `clockin-report` → LINE Push 薛力瑜）
- 登入表單（es.houseol.com.tw/login.aspx，ASP.NET）：`#HouseID`(店代號 H888) `#MemberID`(帳號 03039) `#MemberPW`(密碼) `#LinkButton1`(登入)；帳密放 `.env`（HOUSEOL_STORE/USER/PASS），只有密碼是機密
- **⚠️ 差勤面板預設選【簽退】(LoginType value=1)，簽到是 value=0**；腳本一定先勾簽到再按確認，別手殘直接按確認會簽退
- 驗證：登入 5 個 selector + 確認鈕 xpath + 簽到 radio 全對著 live DOM 命中；**dry-run 真實自動登入成功**（進到簽到頁、已勾簽到、找到確認鈕，未送出）；**尚未做過真實「送出」**（避免非時段留錯時間紀錄），第一次真送是排程隔天早上，靠 LINE 看成敗
- 部署要跑在上班時段會開機的電腦（同 keis 那台門市電腦即可）

## 接下來要做

### 立刻能做
- **自動簽到（🟡 排程已裝，跑在門市電腦=本機，等首跑）** — .env 密碼已填、Playwright/chromium 已裝、dry-run（真實自動登入未送出）已過、工作排程 `houseol-auto-clockin` 已註冊（每天 09:00 觸發 + `--jitter 3600` 隨機 0-60 分 → 落 9:00-10:00）。**剩兩件**：① 把桌面 `json/clockin-notify.json` 匯入 n8n 成新 workflow 並 Activate（不然簽到成功但收不到 LINE）② 隔天(7/14)早上看 LINE 有沒有「✅ 已自動簽到 09:xx」，沒有就查 `scripts/clockin/clockin.log`
- **公買搶單系統（🟢 已上線，跑在門市電腦）** — `scripts/keis/grab.py` + `run.bat`（開機自動啟動、掛掉自動重開）。細節見 `scripts/keis/README.md` 及記憶 keis-grab-notion-sync。
  - 邏輯：06:00–09:30 每 ~5s 掃公買買屋清單，篩「高雄市 + Available」由新到舊搶。（**2026-07-14 起跑點 07:30→06:00**：07-14 名單在 07:30 前就進池，害上架偵測 `appearances.csv` 整批漏記；起點提前讓基準在釋出前建好、量得到真實釋出時刻，也接得住早釋出。純觀測不吃配額。**改動需重啟 watch 進程才生效**。）**雙帳號分工**（薛力瑜＋周珈伊，各 7 配額共 14、不撞單）。搶到拿真實姓名+電話 → 存 `grabbed.csv`＋推 LINE＋寫 Notion「KEIS 搶單名單」DB（`4f28b91531594c618725afc3ecc36e2f`）。市話自動補 07。開盤逾時漏記的靠收盤回查 `my-applications` 自救補回。**收盤時一定推一則今日戰果保底通知**（掛 0 那天也有訊息，分辨貨少 vs 搶輸 vs 系統掛掉）；搶到通知帶今日累計。
  - API（HAR 逆出）：`POST /auth/login?device_type=desktop`（form 帳密→JWT 8h）、`GET /call-purchase/check-ip`（`{allowed,ip}`）、`GET /call-purchase/query`（`only_my_applications=true` = 我的申請，滾動 7 天）、`POST /call-purchase/apply/{id}`。純 httpx 無瀏覽器。
  - **⚠️ 公買鎖門市 IP**（雲端/家裡/手機都被擋）→ 只能跑店裡門市網路電腦（IP 60.248.248.217），不能上 Railway；grab.py 啟動先 `check-ip` 守門。
  - 部署：桌面 `C:\Users\user\OneDrive\桌面\keis`（grab.py 與 repo 一致、`.env` 含帳密+LINE webhook+Notion token+DB id、run.bat 跑 `--watch --apply` 進「啟動」）。KEIS 密碼偏弱(7碼)建議換強的（換了要更新桌面 .env）。
  - **🟡 待驗證（06:00 起跑）**：① 今晚重啟一次 watch 讓 06:00 生效（現跑的那支載入的還是舊 07:30）②連看幾天 `appearances.csv` 的 07-15、07-16… 時間戳＝真實釋出時刻，確認釋出到底幾點、穩不穩，穩定後可把起點收窄回去。釋出規律目前看是「建檔+7天、原本壓 ~08:00」，07-14 異常提前到 07:30 前。
- **使用者裝 Python 跑 `scripts/keis/publish.py` 驗證 KEIS 上架腳本**：照 `scripts/keis/README.md` 設定 → 跑 `python publish.py --login` 手動登入一次 → 跑 `python publish.py YC1868650` 看能不能自動上架。selector 大機率第一次跑會錯（用通用 `get_by_label` 寫法），失敗會截圖 `keis_error_*.png`，下次 session 拿截圖調 selector。**YC1868650 KEIS 還沒上架**，跑通就順便補上
- 下架偵測 cron 目前在 n8n 上 disabled，等 6/1 LINE 月額度重置後手動打開（手動 webhook `/yc-check-removed` 不吃 push 額度，現在就能測）

### 中期
- yc-ad skill 跑幾個物件後微調 SKILL.md 文案 prompt（口氣、社團排版變化度）
- KEIS 腳本驗證能跑後，包成 FastAPI webhook 部到 Railway，串進 yc-ad skill 4b 步驟取代「貼操作指令包」
- 等 yc-ad skill 用順手後，砍掉 n8n 的 `yc-rewrite-copy` workflow + router 的 `生成文案` 出口

### 暫不做
- **FB Graph API 自動排程粉專**：兩輪嘗試（2026-05-20 + 2026-05-21）都卡在 redirect URI host whitelist。詳細 debug 過程看 git log（搜 `FBL4B`）。粉專繼續用 Meta Business Suite 手動排程。要再戰可考慮：(a) 真實擁有的網域 + HTTPS server 當 redirect_uri；(b) Meta Business Manager System User 跳過 OAuth dialog；(c) app 翻 Live mode 看限制是否放寬
- 留存的 FB Apps（都是棄置狀態，要重戰直接重建）：`1950187462277347`（事業類型）、`1532682778272952`（消費者類型 + FBL4B 組態 `2054313972110634`）
