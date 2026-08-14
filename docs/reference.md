# 參考資料（查表用）

> 這份放「不太會變、但要查的時候一定要查對」的東西：入口網址、credential、Notion 欄位、
> LINE 指令、架構圖、桌面工具清單。
> 現況與待辦看 `STATUS.md`；事故血淚史看 `incidents.md`；線上真正在跑什麼看 `n8n-live.md`。

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
| Notion 搶單名單 DB | `4f28b915…`（KEIS 待聯絡提醒用）|
| 薛力瑜 LINE userId | `Ufab42c56b2eb9b9a9ff18c367b85a6dd`（下架偵測 Push 用）|
| Drive 物件資料夾父層 | `1pn-tXugI8hlmVZJf2amWs9gnrj9-YhqC`（建檔器比對用）|
| FB 粉專 | 買房不費力,賣房好給力（`FB_PAGE_ID=1041868522352339`）|
| KEIS 廣告追蹤 | `https://keis.kshouse.com.tw/ad-tracker` |
| 展售系統 | `https://es.houseol.com.tw` |

### Railway 環境變數（動之前先看 incidents.md）

`EXECUTIONS_DATA_PRUNE=true` / `MAX_AGE=336`（14 天自動清）/ volume 5GB（Hobby **鎖死加不了**）。
🔴 **`EXECUTIONS_DATA_SAVE_ON_SUCCESS` 一律保持 `all`**，改 `none` 會讓所有 Wait 節點無聲死掉。
空間真的不夠時正確做法是調降 `MAX_AGE`（336 → 168），絕不是關掉紀錄。

**單支 workflow 太肥時**：改它自己的 `saveDataSuccessExecution: none`（workflow 層級，
不動全域）。`靜默失敗巡邏` 已經這樣設——它會抓別人的完整執行資料，不關掉會每 30 分鐘
把 50MB 複製一份進資料庫（2026-08-09 就是這樣撐爆的）。

🔴 **清執行紀錄一律 `TRUNCATE`，絕不用 API 批次 DELETE**。DELETE 會先寫 WAL 才釋放空間，
在快滿的磁碟上會當場撐爆、Postgres 停機。

**Postgres 撐爆了怎麼救**（完整步驟見 `incidents.md` 2026-08-09）：
Custom Start Command 暫改 `sleep infinity` → `railway ssh --service Postgres` →
`pg_wal` 搬到容器暫存碟 + symlink → 用 5433 埠啟動 → TRUNCATE → 搬回 → 才還原啟動指令。
原始啟動指令：`/bin/sh -c "unset PGPORT; docker-entrypoint.sh postgres --port=5432"`
⚠️ Hobby 方案**備份與還原是 Pro 限定**，沒有安全網，別指望 Backups 分頁。

---

## Credentials

| 名稱 | n8n ID | 類型 | 用途 |
|---|---|---|---|
| `Notion account` | `T62CHdfWuY9iXKWk` | Notion API | n8n Notion 節點 |
| `Notion API Token` | `edOz4T0LC6EP41Ug` | HTTP Header Auth | HTTP Request 打 Notion API |
| `LINE Channel Access Token` | `OmFzUGgZ1xIpAAP5` | HTTP Header Auth | LINE Reply / Push |
| `Gemini API Key` | `zTIA89pDJJs0Ad29` | HTTP Header Auth | Gemini（Header `x-goog-api-key`）。🔴 **免費方案，每個模型每天只有 20 次**，見下方 |
| `Google Drive account` | `0TSq1oyqs4BHQxWa` | Google Drive OAuth2 | 建檔器列 Drive 子資料夾用 |
| `Google Calendar account` | **待建** | Google Calendar OAuth2 | 行事曆建立器寫 primary 行事曆用 |
| `FB Page Token` | 已建立 | HTTP Header Auth | `Authorization: Bearer <永久粉專權杖>`，發文/刪文用 |
| `KEIS 帳密（自動登入）` | `KPvi4Z4Z8IAhKbdz` | Custom Auth | `{"body":{"username":…,"password":…}}`。線 A/B 每次跑都自己打 `/auth/login` 拿新 token（KEIS 的 JWT 只活 8 小時，靜態 token 撐不過一天）|
| `展售系統帳密（自動登入）` | `ZkOT0wWz3oZTpdME` | Custom Auth | `{"body":{"LoginType","HouseID","MemberID","MemberPW"}}`；本機 `.env` 也有一份（`ES_*`，已 gitignore）|
| `KEIS_LINE_DIRECT_TOKEN` | `scripts/keis/.env` **和桌面 `keis\.env` 兩份都要有** | LINE Messaging API 直推 | grab.py 心跳 + 廣告看門狗繞過 n8n 直推用。⚠️ **改 .env 一律兩邊都改**（2026-08-02 就是因為桌面那份沒有這個 key，防線形同虛設）|

### 🔴 Gemini 配額：免費方案「每個模型每天 20 次」

2026-08-04 實測撞到的硬天花板（錯誤裡的原文：
`quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier`、`quotaValue: 20`、
`model: gemini-2.5-flash-lite`）。

- **是「每天」不是「每分鐘」**，撞到之後要等太平洋時間午夜重置＝**台灣時間下午 3 點**
- **配額是每個模型分開算的**：`gemini-2.5-flash-lite` 用完，`gemini-2.5-flash` 還有自己的 20 次
  （實測 `gemini-2.0-flash` / `gemini-2.0-flash-lite` 一律 429，不能當備援）
- 撞到時 n8n 顯示的訊息是 `The service is receiving too many requests from you`，
  看起來像「打太快」，其實是「今天的份用完了」——**不要傻等一分鐘再重試**

**現在的用量（2026-08-14 起）**：線 A「產文案」已改走 `scripts/codex-copy`（ChatGPT 訂閱額度，
不吃這桶配額），只剩線 C 最多 6 班 + LINE 的行事曆/客戶/圖片分流器隨叫隨用，壓力比之前小很多。
要加任何一個新的 Gemini 呼叫之前還是先算這筆帳，或是**分散到不同模型**，再不然就去 Google Cloud
開帳單轉付費方案。codex-copy 的機制、cloudflared 不穩定的已知問題見 `scripts/codex-copy/README.md`
和 `incidents.md` 2026-08-12～13 那則。

⚠️ 用臨時 workflow 試跑 Gemini 相關的東西**會吃掉正式線的額度**
（2026-08-04 就因此弄掛一班廣告，見 `incidents.md`）。要測就挑非整點、控制次數。

⚠️ FB Page Token **沒有 `pages_read_engagement`**（列不了貼文清單，只能發文／改文）。
要做「掃粉專找爛貼文」得先補權限，見 `docs/fb-token-setup.md` F 步驟。
`GET /me/permissions` 和 `?fields=tasks` 對粉專權杖都問不出東西，別浪費時間。

### n8n 操作方式

n8n 2.x 把登入綁瀏覽器指紋，**用瀏覽器做寫入會 401 並把使用者登出——不要用瀏覽器操作 n8n**。
一律走官方 Public API：金鑰在 `.env`（`N8N_API_KEY`，已 gitignore，永不過期），
端點 `$N8N_URL/api/v1/workflows`，Header `X-N8N-API-KEY`。可讀可寫可刪。

- ⚠️ 改「已啟用」的 workflow 後**一定要 deactivate + activate 一次**，否則排程觸發器還在跑舊版
- ⚠️ 子流程要先自己 activate，主流程才啟用得起來
- ⚠️ 判斷「哪一支在跑」要看 `/api/v1/executions`，不能只看名字（同名/亂名 workflow 很多）
- **試跑手法**：Public API 沒有「執行 workflow」端點。做法是用 API 把要測的節點複製到一支臨時
  webhook workflow（schedule trigger 換成 webhook、砍掉會寫入的節點、尾巴接 Code 節點回報結果），
  打完 webhook 就刪掉。能在不碰真資料的情況下驗證線上邏輯。
- **不要在現有 workflow 裡直接 Import JSON**（會覆蓋），一律開新空白 workflow 再匯入
- 備份 `backup/n8n-2026-07-22/`（清理前 43 支全量匯出）**只存本機、已 gitignore**——
  裡面有兩支舊 workflow 把 token 寫死在 JSON 裡，**不能進 git**

---

## LINE 指令一覽

| 指令格式 | 行為 | 下游 workflow |
|---|---|---|
| `停` / `停 AGxxx` | 攔截待發廣告 | `yc-v3-stop` |
| `行事曆 <自由描述>` | Gemini 解析時間/地點/說明 → 建到 Google primary 行事曆 | `line-calendar-create` |
| `客戶 <自由描述>` | Gemini 抽姓名/電話/公司/需求 → 寫進 Notion 客戶名單 DB | `line-customer-create` |
| （純圖片，無前綴） | Gemini Vision 自動分類 → 轉發到行事曆或客戶 | `line-image-dispatcher` |
| `戰果` / `今日戰果` | 查 Notion 搶單名單今天的紀錄 → 回筆數＋名單（reply 不吃 push 額度） | `keis-battle-report` |
| `情資` | 回本週 KEIS 內部成交週報（快取；桌面 `bdinfo.py` 每週二 09:55 寫入） | `market-report-notify.json` |
| `工作回報` | 查「系統日誌」DB 今天的事件＋廣告 DB 今天異動，組一則文字回覆（2026-08-14 新增，取代原本 11 個主動 push） | `yc-work-report.json`（n8n 內部名「工作回報查詢」）|
| `天氣` | router 認得但沒接下游（佔位） | — |

`行事曆`/`客戶` 也接受傳圖片（手寫便條、會議截圖、名片）→ 下游過 Gemini Vision 抽欄位。

> **2026-07-23 退役**：`建檔 <網址>`、`發 YCxxx`、`生成文案 YCxxx` 已從 router 拔掉
> （下游 `YC 建檔器 v2` / `YC 發文線` / `文案重產器` 三支 workflow 一併停用）。
> 要復原：三支開回 active，router 的 `解析 LINE 指令` 節點加回 create/publish/rewrite 三行對應
> （Switch 分支與轉發節點都還在）。原始 router JSON 備份在 `backup/n8n-router-v3-before-2026-07-23.json`。
> ⚠️「戰果」是搶單專用關鍵字，廣告不要用。

---

## 現有架構

```
LINE Webhook (/766bd943-…)                  ← 行動 / 手機場景
   ↓
LINE 指令分流 (Switch by command / message type)
   ├── stop     → 廣告v3 煞車      (/yc-v3-stop)
   ├── calendar → 行事曆建立器     (/line-calendar-create)
   ├── customer → 客戶建檔器       (/line-customer-create)
   ├── battle   → KEIS 戰果查詢    (/keis-battle-report)
   ├── workreport → 工作回報查詢   (/yc-work-report)    ← 2026-08-14 新增
   └── image    → 圖片分流器       (/line-image-dispatcher)
                       └─ Gemini Vision 分類 → calendar 或 customer

Claude Code Skill (.claude/skills/yc-ad/)    ← 桌面 / 深度操作場景
   /yc-ad 或自然語言「發 YCxxx」
       ↓
   讀 Notion 廣告 DB → 產粉專詳細版 + 社團簡短版 → 寫回 Notion
       ├── 粉專連結回報 → PATCH 粉專貼文連結 + 狀態=已發布
       ├── 「同步 KEIS」 → 產操作指令包貼給瀏覽器擴充功能執行
       ├── 「發到 X 社團」→ append 廣告貼文紀錄
       └── 「已撤除 YCxxx」→ 標下架 + 附粉專連結提示手動刪 FB
```

文案規格見 `.claude/skills/yc-ad/SKILL.md`：粉專 200-300 字、社團 50-80 字（不放連結，引導留言區），
兩版下方都帶法規必填「凱璿誼峰不動產有限公司 + 字號」footer，
聯絡人固定「薛先生 0912877583（同 LINE）+ `https://line.me/ti/p/kg1pMk4vX8`」，不放 YC 編號 hashtag。

### 其他 workflow 行為

- **行事曆建立器**：`行事曆 ...` 文字或圖片 → Gemini 抽 `{title,start,end,location,description}` → Google Calendar primary 建 event → LINE 回覆
- **客戶建檔器**：`客戶 ...` 文字或圖片（名片）→ Gemini 抽欄位 → Notion 客戶名單 DB 新增 → LINE 回覆（失敗會帶 Notion API 原始錯誤）
- **圖片分流器**：純圖片無前綴 → 下載 → Gemini Vision 分類 → 轉發（分不出時預設客戶）
- **KEIS 待聯絡提醒**：每天 09:00 查搶單名單 → 挑「未聯絡 且 搶到滿 7 天剩≤2 天」→ 有才推 LINE。搭配 Notion 視圖「🔔 待聯絡」
  ⚠️ **在 Notion 手動刪名單是沒用的**：`audit_notion` 拿 `grabbed.csv` 當唯一真相，刪掉＝它眼中的缺漏 → 補回來。**要讓一筆退場一律改「聯絡狀態」**
- ~~物件建檔器 / 文案重產器 / YC 發文線~~：2026-07-23 停用，功能由線 A + `/yc-ad` skill 取代
- ~~撤除回報器 / YC 下架偵測線（舊）~~：2026-07-23 刪除，功能由線 B 取代。JSON 備份在 `backup/n8n-deleted-2026-07-23/`

---

## Notion 廣告 DB 欄位（`07ee845168b64f8a9b5682e5069c733b`）

| 欄位名 | 型別 | 備註 |
|---|---|---|
| 案名 | title | |
| 案件編號 | rich_text | 永慶兩碼英文 + 數字，例 `YC1835328` / `YE0095535` |
| 社區名稱 | rich_text | |
| 地址 | rich_text | |
| 建物類型 | select | `電梯大樓`/`華廈`/`公寓`/`透天`/`套房`/`店面`/`其他` |
| 格局 | rich_text | |
| 樓層 | rich_text | |
| 屋齡 | number | 年 |
| 總價 | rich_text | 含「萬」字串，例 `338 萬` |
| 建物坪數 / 主建物坪數 | number | 坪 |
| 粉專文案 | rich_text | 粉專詳細版（200-300 字）|
| 社團文案 | rich_text | 社團簡短版（50-80 字）|
| 粉專貼文連結 | url | |
| 廣告貼文紀錄 | rich_text | append：社團名 / 日期，多行 |
| KEIS同步 | select | `未同步`(預設) / `已同步` |
| 文案版本 | number | 每次重產 +1 |
| 狀態 | select | `草稿`/`待發`/`已發布`/`下架`/`取消` |
| KEIS廣告ID | number | 線 D 寫入：`ad-tracker` 的 `adcase_id`，線 B 靠它關廣告 |
| 永慶官網連結 | url | 線 D 寫入：反查出來的 `buy.yungching.com.tw/house/{id}`。**全系統唯一的物件官網連結**：KEIS `adcase_url`、線 B 舊資料二次確認、`publish.py` 手動上架都用它 |

> ⚠️ **`來源連結` 已於 2026-08-05 刪除**。它是 v1/v2「LINE 貼永慶網址建檔」時代的輸入兼判重鍵；
> v3 改成掃 KEIS API 後，寫進去的變成 KEIS `official_url`＝houseol 網址，而 houseol 的 `sell_item`
> 頁會過期（刪除前 72 筆全部 404）。所有引用都改指 `永慶官網連結`，理由見 incidents.md。
| 專員 | rich_text | 線 A 寫入：KEIS `sales_agent_name` |
| 所屬門市 | rich_text | 線 A 寫入：KEIS `store_name` |
| 專員電話 | phone_number | 子流程「查專員電話（展售系統）」寫入 |
| 要重發 | checkbox | **線 C 的名單就是這欄**：打勾＝排隊，重發完系統自動取消勾（一次性）|
| 最後重發時間 | date | 空的＝沒重發過，排最前面 |
| 重發次數 | number | |
| KEIS物件ID | number | 線 A 建列時寫入。線 C 靠它回頭抓照片，**沒這欄的舊資料不會被重發** |
| 已撤除確認 | checkbox | |
| 下架偵測時間 | date | |

> 2026-07-23 清掉 10 個舊系統遺留欄位（`公設坪數` `土地坪數` `附屬建物` `單價` `有無車位`
> `車位類型` `文案風格` `物件照片` `特色說明` `產生的文案`）。快照在
> `backup/notion-ad-db-dropped-fields-2026-07-23.md`。「單價」在 v3 是內部變數（餵數字守門員），沒寫進 Notion。

⚠️ **判重只看「案件編號在不在 Notion」，不看狀態**。這條規則衍生出三件事：
- 發文失敗要 archive 那列，否則該物件被永遠跳過
- 卡在「待發」要重新排隊 → **在 Notion 封存那列**即可（可逆，進垃圾桶），封存後自動回到候選池。
  ⚠️ 重發輪替線**接不住**這種——它要求「已發布 ＋ 有粉專連結」而且會先刪舊貼文
- 被紅線擋下的案子不能在 Notion 留列，否則以後條件變了也永遠不會再被抓到

## Notion 客戶名單 DB 欄位（`3eb9902989534654976e2f677b6957b3`）

| 欄位名 | 型別 | 備註 |
|---|---|---|
| 客戶姓名 | title | 建檔器**必填** |
| 電話 | phone_number | |
| 公司 | rich_text | |
| LINE / 通訊軟體 | rich_text | 注意欄位名含空格與斜線 |
| 來源 | select | `591`/`來電`/`介紹`/`路過/踩線`/`社群`/`其他`（預設 `其他`）|
| 狀態 | select | `新名單`/`已聯絡`/`可帶看`/`斡旋中`/`已成交`/`暫緩/無效`/`委託中屋主`（預設 `新名單`）|
| 標籤 | multi_select | `買方`/`賣方`/`租方`/`出租`/`急`/`預算已確認` |
| 備註 | rich_text | 建檔器把「地址、職稱、需求、預算」全塞這（地址欄是 place 特殊型別，n8n 寫不進去）|
| 下次追蹤日 | date | YYYY-MM-DD |
| 地址 | place | **建檔器不寫**，改寫到備註 |
| 建立時間 / 最後更新 | 自動 | |
| 關聯物件 / 關聯募集線 | relation | 建檔器不寫 |

---

## 廣告系統 v3 — workflow 一覽

> **▶ 執行入口：`docs/v3-ad-auto-workorder.md`**（含全部決策、KEIS API 實測、code）。不要重新討論架構。

**一句話**：n8n 定時打 KEIS API 撈整個加盟體系在售案 → Gemini 產文案 → LINE 預告 10 分鐘煞車視窗
→ 沒喊停就自動發粉專多圖文 → 每天偵測 KEIS 下架就自動刪 FB 文。Notion 只當帳本。
**絕不碰屋主個資**（白名單清洗節點強制）。

| workflow | 用途 | 排程 |
|---|---|---|
| `yc-v3-scan-publish.json`「廣告v3 掃描發文線」（線 A）| 掃描+發文+同步 KEIS 廣告追蹤 | 09/11/13/15/17/19，每次 1 件 |
| `yc-v3-removal.json`「廣告v3 下架偵測線」（線 B）| 下架偵測+刪 FB 文+關 KEIS 廣告 | 每天 08:00 + 22:00 |
| `yc-v3-repost.json`「廣告v3 重發輪替線」（線 C）| 防貼文沉底：重產文案→發新文→刪舊文 | 09:30/11:30/…/19:30，每班 1 件 |
| `yc-v3-stop.json`「廣告v3 煞車（停）」| 煞車 webhook | 觸發式 |
| `line-command-router.json`「LINE 指令分流器 v3」| 指令分流 | 觸發式 |
| `系統錯誤-LINE-告警.json` | **全域**：任何 workflow 執行失敗 → 推 LINE | Error Trigger。⚠️ 必須保持 active，inactive 時完全不觸發 |
| `靜默失敗巡邏.json` | 掃成功執行裡被吞掉的節點錯誤 → 推 LINE | 每 30 分鐘 |

### 線 A 篩選規則（2026-07-23 定案）

在售 + 有照片 + **總價 ≥ 800 萬** + `show_in_web === true`（🔴 紅線）+ 官網上架 **30 天內優先**
（`houseol_created_at` 新到舊；30 天內的都發過了才往下墊較舊的，避免整條線空轉）。
面議價 9999 萬排除。常數在「篩選候選」Code 節點：`MIN_PRICE` / `FRESH_DAYS`。

- **判重整批一次**：「查 Notion 是否已建」設 `executeOnce`，body 用 `or` 把 40 個案件編號一次送出
- **候補接棒**：候選被守門員擋下不會整班空轉，`取候補 3 件` + `逐件嘗試` 迴圈，最多試 3 件。被擋的建 Notion 草稿列（備註寫原因），下一班才不會抓到同一件再擋
- **賣點預過濾**：算出最終學區/屋齡後，先把 KEIS 賣點原文裡命中「學區/國小/國中/屋齡/年新/新成屋/中古」的子句砍掉才餵 Gemini（賣點常寫「近學區」但官網沒登記，硬留著會被守門員判腦補整篇擋掉）
- **數字守門員**：文案裡每個數字都要在官方事實裡找得到，對不上就不建 Notion、不發文，改推 LINE。另擋「官方沒這筆資料就不准提」（屋齡/學區/格局/樓層）。⚠️ 比對前會先把網址拿掉（LINE 短網址裡有數字）。⚠️ 2026-08-03 加了第 (3) 項出貨前形狀檢查
- **Gemini prompt 收緊**：粉專文案只准四塊（標題／規格區／✨亮點 3-5 條／footer），**禁止自由描述段落**，亮點每條必須改寫自 `feature_1~5`

### 線 C 重發規則（2026-07-23 定案）

名單＝Notion `要重發` 打勾的（使用者自己勾）。**一次性不是循環**：重發完系統自己取消勾。
每班挑 `最後重發時間` 最舊（或空的）一筆 → 打 KEIS 抓最新照片 → Gemini 換角度重寫 →
發新粉專文 → **成功後才刪舊文** → Notion 換新連結、`最後重發時間`=今天、取消勾、`重發次數`+1 → LINE 推一則。
⚠️ **不碰 KEIS 廣告追蹤**（KEIS 擋重複 `adcase_url`）。⚠️ 舊文一刪社團分享會失效，要重按新文的「分享」。

### 線 B 通知規則

正常日子**一則都不推**。只有「粉專貼文刪除失敗」（附連結讓你手刪）和「KEIS 撈不到資料」才推。
社團是用粉專分享出去的，粉專文一刪分享自動失效，所以下架成功不需要通知。

### 推播 → 系統日誌（2026-08-14）

線 A/B/C 原本共 11 個 LINE push 節點，全部拔掉（額度考量，改用「工作回報」關鍵字查詢，見上方
LINE 指令一覽）。Notion 本來就查得到的（守門員擋下的草稿列、已發布狀態、重發完成、被停確認）
直接刪節點；完全沒地方存的（API 體檢告警、跳過摘要、線 A 發文失敗、線 B 刪文失敗／KEIS 故障、
線 C 守門員擋下、系統錯誤告警）改寫進新 DB **系統日誌**（`0df73bdfe72b4451bb841ebc151aecc9`，
`永慶博愛凱璿` 首頁下）：

| 欄位 | 型別 |
|---|---|
| 標題 | title |
| 內容 | rich_text |
| 來源 | select：`線A`/`線B`/`線C`/`系統錯誤` |

⚠️ 這個 DB 是用 Claude 的 Notion 連接器建的，**跟 n8n 自己的 Notion integration（叫「n8n 廣告系統」）
是兩個不同的存取權限**，要手動到 Notion 該頁 `Connections` 加一次才會通。以後要幫 n8n 建新 Notion
資料庫，改用 n8n 自己的憑證跑一次臨時 workflow（見下方「試跑手法」），不要用 Claude 自己的連接器建，
省得又要手動分享一次。

線 A 的「10 分鐘煞車預告」push 也拔了，`煞車 10 分鐘` 那個 Wait 節點沒動，「停」指令的 reply
本來就不吃 push 額度。系統錯誤 LINE 告警（`eTHhmrZVmllk1aUZ`）保持 active，只是輸出從 push
改成寫系統日誌。

### 重試策略

線 A/線 C 的 KEIS、Notion、Gemini、FB 上傳節點全部 `retryOnFail=3 次 / 間隔 5 秒`。
全部啟用中 workflow 的 LINE push 節點也都有重試。

⚠️ **`FB 發貼文`／`Notion 建待發列`／`KEIS 新增廣告`／`刪舊貼文` 刻意不加重試**——
重打會產生重複貼文/重複資料，寧可失敗也不要重複。失敗改走自動撤列 + FB 反查補救機制。

---

## KEIS 廣告追蹤平台

- 網址 `https://keis.kshouse.com.tw/ad-tracker`，**有內部 API**，線 D 已全自動同步。端點與欄位見 `docs/v3-ad-auto-workorder.md` §15
- 新增 `POST /api/v1/adcases`（必填只有 title/url/member）；關閉 `PUT /api/v1/adcases/{id}` body `{"is_expired":true}`
- ⚠️ **`closed_at` 是唯讀**，送了會被無聲忽略
- **它自己就是下架偵測器**：新增廣告後 15～20 秒、之後每天凌晨去抓 `adcase_url`，死了就標
  `url_invalid=true` + `status_tags:['案件下架']`，活著就把官網現價填進 `url_price`。
  線 B 的下架判定主要就是讀這個。但 KEIS 只標記不會自動關閉，`is_expired` 要我們自己送
- ⚠️ 只收永慶/台慶連結，塞 houseol 網址會被 500 打槍
- ⚠️ `show_in_web` **只有列表端點有，詳情端點沒有**。要稽核只能整份撈（`page_size` 上限 100，
  `total_pages` 欄位是 null，要靠 `total` 或「回傳筆數 < page_size」判斷收尾）

### 2026-07-23 被砍的欄位「回來了」——但先別改回去

2026-08-04 實測詳情端點（`GET /api/v1/property-management/{id}`）欄位數 61 → **85**，
當初砍掉的全部又有值了：`images`（含網址）、`age`、`school_info`、`official_url`、
`layout`、`floor_info`。

**不要因為欄位回來就把繞道做法改回去**（照片走 download-images zip、屋齡學區走永慶官網、
格局樓層自己組）。理由：現在這套不依賴 KEIS 給不給，KEIS 砍過一次就會砍第二次，
而繞道做法已經跑順、還多了官網交叉驗證這層。除非現行做法出問題，否則不動。

⚠️ 值得盯的一點：詳情端點的 `image_count` 現在反而是**空的**，而 `API 體檢` 有檢查這個欄位。
體檢讀的是列表端點所以暫時沒事，但 KEIS 顯然還在動欄位。

登入（給本機腳本用，n8n 走 credential）：
```
POST /api/v1/auth/login?device_type=desktop
content-type: application/x-www-form-urlencoded
username=<帳號>&password=<密碼>     → 回 {"access_token":…, "expires_in":28800}
```
賣點是 `feature_1` ~ `feature_5`；車位是 `parking_type`
（⚠️ **「車位」指有產權的登記車位**，大樓那種；透天的「車庫」是空間、不會登記成車位，兩者不同）。

### 永慶官網連結反查（發文前的門檻）

`永慶官網補資料` 之後接 `有永慶連結?`，查不到就跳過換候補下一件。
理由：KEIS 廣告追蹤只收永慶/台慶連結，先發 FB 再建檔的話最後一站失敗就留下
**沒登錄的孤兒廣告（會被開罰）**。別再改回「先發文後建 KEIS」。

**比對＝物件編號對物件編號**：官網物件頁 JSON-LD 有 `"productID"`，
KEIS `PG0092558` → 官網 `YC0092558`、`EG0501408` → `TC0501408`
（YC=永慶、TC=台慶、YE=永義，**字母前綴各家不同、數字部分完全一致**）。

⚠️ **數字一樣不代表同一件**（撞號防線，見 incidents.md）：編號對上只是必要條件，
還要**行政區對得上 + 至少一項佐證**（總價／建物坪／權狀坪／土地案用地坪或地段名），
對不上就記「⚠️編號撞號擋下」跳過，不猜。

⚠️ **不能直接取搜尋結果第一筆**：官網搜尋 JSON-LD 第一筆 url 永遠是壞的
`house/4308114`（台北信義區某物件），而且它的 productID 每次都不同（實測連三次不一樣）。
要逐筆開頁面比 productID。

舊的模糊比對（案名／社區／路名＋總價／坪數）降級成備援，**只在候選頁面全都讀不到 productID 時**
才啟用，備援路徑也一律要求行政區對得上。跳過的件不建 Notion 列，下一班會再試
（新案官網頁面常晚幾小時才上）。

---

## 專員電話來源（展售系統 es.houseol.com.tw）

KEIS 沒有專員電話，展售系統有。已做成子流程 **`查專員電話（展售系統）`**（id `GGguwcmUhpRXXcBu`），
線 A / 線 C 都接上了。輸入 `contract_no` + `專員`，輸出加 `專員電話` 與 `電話來源`。

**端點**（同源 GET，靠登入 cookie）：
```
GET https://es.houseol.com.tw/Function/FancyWindows.aspx?job=ContactDetails&HID=H888&MainID=<物件編號>
```
- `HID=H888` 固定；`MainID` 直接用 KEIS 的 `contract_no`（例 `AG1927880`）
- 回傳約 4KB HTML，解析 `經紀人{n}<姓名>/<手機>`，最多四位
- 挑號規則：姓名對得上就用本人手機 → 否則用同案其他經紀人 → 都沒手機就退分店電話，`電話來源` 會寫是哪一種
- **查不到絕不擋廣告**：每個 HTTP 節點都 `neverError + continueRegularOutput`，最壞是電話留白

**登入流程**：
```
1) GET  /login.aspx                → 撈 __VIEWSTATE / __VIEWSTATEGENERATOR / __EVENTVALIDATION
2) POST /login.aspx (form-urlencoded)
   __EVENTTARGET=LinkButton1  ←★ 關鍵，登入鈕是 ASP.NET LinkButton，少了它會靜靜退回登入頁
   __EVENTARGUMENT= / 三個 hidden 原樣帶回
   LoginType=4  HouseID=<店號>  MemberID=<帳號>  MemberPW=<密碼>
3) 帶 cookie GET /Function/FancyWindows.aspx?job=ContactDetails&HID=H888&MainID=<編號>
```
登入成功會轉到 `/index.aspx`（頁面上那句 `請先輸入資料！` 是首頁正常提示，不是登入失敗）。

⚠️ 子流程只處理第一筆 item（線 A/C 都只有一筆，夠用；要批次得改）。
⚠️ 照片不在型錄頁的原始 HTML 裡（raw HTML 只有 5 張店招/logo），是 JS 另外載的——
想拿展售系統當照片來源還要再挖一層。

---

## 廣告發文看門狗（刻意住在 n8n 外面）

`scripts/keis/ad_watchdog.py`（桌面同步一份在 `桌面\keis\`）。
**不碰 n8n、不讀執行紀錄，只問 Notion「廣告有沒有真的發出去」，走繞過 n8n 的直推 LINE。
n8n 整台燒掉它照樣會叫。**

| 項目 | 值 |
|---|---|
| 排程 | Windows 工作排程器「KEIS廣告看門狗」，08:05 起每小時一次（`pythonw`，不跳黑視窗）|
| 判斷一 | 有「待發」卡超過 **30 分鐘** → 告警（煞車窗口 10 分鐘，留緩衝）。每筆每天最多一次 |
| 判斷二 | 過了 **14:00** 還沒有任何一筆「今天已發布」→ 告警。每天一次 |
| 判斷三 | 最近 30 筆「已發布」的文案裡有 `"粉專主體"`／字面 `\n`／``` ``` ``` → 告警。每筆每天一次 |
| 防吵 | 判斷一有推就不推判斷二（同一件事）；判斷三獨立跑 |
| 出口 | `KEIS_LINE_DIRECT_TOKEN` 直推，**完全不經過 n8n** |
| log | `桌面\keis\logs\ad-watchdog.log`；狀態 `ad_watchdog_state.json` |
| 測試 | `python ad_watchdog.py --dry`（只印不推、**不寫狀態檔**）|

---

## 獨立桌面工具（深度細節見各自 README）

跑在門市電腦、與 n8n 無關。這裡只記狀態，機制/gotcha/用法一律看各資料夾 README。

| 工具 | 狀態 | 深度文件 |
|---|---|---|
| **公買搶單** `scripts/keis/grab.py` | 🟢 上線。**搶單規則（2026-07-23 定案，別再改）**：只看編號最大的前 40 筆窗口（`WINDOW_SIZE`）＋建檔超過 10 天不搶（`MAX_AGE_DAYS`）＋二手回鍋不搶。**拉大窗口＝拆掉把關**（試過，10 分鐘誤搶一筆半年前的老案，已回退）。全池掃描每小時一次、輪流換帳號，只寫 `inventory.csv` 稽核總帳。篩選：只搶手機／排除公寓／預算<1000萬不搶／記行政區。分層時段 07:00-10:00／10:00-17:30／17:30-24:00／00:00-07:00(等同停止)——**早上熱門檔起點 07:00 別改回 07:30**（輪詢間隔是睡前算一次不重算，門市網路約 07:22 恢復時若還在深夜檔會睡到 07:52）。回報固定三段式「新名單／符合條件／打中」。**防重複**：寫 Notion 前先查同電話（只留數字比對），來過就打勾 `重複電話`＋`同電話前一筆` relation 連回去、備註寫前幾筆資訊，舊那幾筆也一起打勾 | `scripts/keis/README.md`、`docs/keis-grab-hardening-and-filters.md` |
| **自動簽到** `scripts/clockin/` | 🟢 上線（2026-07-14 首跑）。jitter 0-60 分為常態分佈（中心 30 分）| `scripts/clockin/README.md` |
| **售屋表填寫** `scripts/sale-form/` | 🟢 2026-07-20 第 4 輪修完。**實際執行的是桌面 `工具\不動產售屋表工具_v3.4\zipinspect\`**（資料夾名是舊版號、內容才是新的），改完兩邊要同步。`template/*.xltx` 兩個 Excel 範本非它不可。⚠️ 待門市拿真實案件實測；塗銷防護只用模擬文字驗過 | `scripts/sale-form/README.md`、桌面 `售屋表v3.6實測清單.md` |
| **租屋廣告文案** `scripts/rent-ad/` | 🟢 使用中（社宅／包租代管）。**桌面檔名是 `工具\國城\國城廣告文生產器.py`**，別只找「租屋」| `scripts/rent-ad/README.md` |
| **房地/i智慧配案** `scripts/buyer-match/` | 🟢 2026-07-29 大改完成、真實資料驗過。房地存客需（含畫多邊形）→ 讀出範圍與篩選條件 → 回頭去 i智慧 現查即時案源 → 去重 → 輸出。日常入口雙擊桌面 **`房地i智慧配案.vbs`**；整組批次 `run_group_match.py A買 --newest`。**第一次要在同一個 CDP Chrome 手動登入房地一次** | `scripts/buyer-match/README.md` |
| ~~**KEIS 廣告上架** `scripts/keis/publish.py`~~ | ⚫ 已作廢（2026-07-23），線 D 直接打 API 取代 | — |

---

## 公開網頁：Cloudflare Pages 發布鏈路（2026-08-05 上線）

三個站共用同一個 Cloudflare Pages 專案 `yc-tools.pages.dev`：`/yc-calc/`、`/kh-market/`、
`/buyer-match/`。搬家原因是 GitHub 帳號停權**連 GitHub Pages 一起關掉**，`github.io` 底下
三個站對外全部 404、`git ls-remote` 也 403。當時「情資沒更新」不是 bdinfo 壞掉——每週二
照樣算好寫檔，是推不上去。

**發布鏈路**
1. 週二 09:55 bdinfo 產完 `dist/data/intel/latest.json` → **當場叫 `update.py --deploy-only`**
   （不用等 13:37）
2. 每天 13:37 `KH-Market-AutoUpdate` 再發一次保底
3. 發完**真的去線上抓一次比對**，不符或 404 就推 LINE。同故障 3 天只吵一次，
   狀態存 `publish_state.json`
4. `buyer-match` 的 `daily_run.py` 跑完也會自動呼叫 `kh-market-tool/update.py --deploy-only`

GitHub 仍是次要通道，帳號恢復當天會自動補推積著的 commit。
手動重發：`python update.py --deploy-only`

### 買方配案看板機制（2026-08-05～08-06 定案）

- **三個入口版面統一在 `build_static_view.py`**（localhost:5001／桌面 `配案看板.html`／
  手機網址）。**不要在 `webview_server.py` 裡寫 HTML。**
- **看板資料以排程現查結果為準**：排程現查完直接覆蓋看板的「完整清單」，物件下架／全部歸零
  都會同步反映。（舊行為是只有人工點「完整查詢」才刷新，排程只存「新增/降價」差異，
  所以物件下架後看板一直顯示舊連結。）
- 客戶被移出房地資料夾後，manifest／看板自動清掉舊資料（`manifest.prune_group`）
- **資料瘦身**：`output/` 歷史查詢檔由排程自動清（一次性清過 926K→238K），
  `daily_run.log` 只留最近 7 天
- 電腦端「點連結原地預覽」在 5001 和桌面單檔都有；手機網址是獨立網頁（不在 iframe 裡），
  連結會直接原生開新分頁
- 手機看板含客戶姓名/需求，`robots.txt` 擋 `/buyer-match/` 被搜尋引擎收錄，
  但網址本身沒有帳密保護（使用者已確認接受）。舊的 Claude Artifact `c30bd39a-…` 已棄用

---

## 廣告系統 v2（已被 v3 取代，只留兩件還有效的事）

- **FB 永久權杖**：粉專「買房不費力,賣房好給力」，App `kaixuan-ad-bot`、系統使用者 `n8n-bot`，
  權杖在 n8n credential `FB Page Token`。設定教學 `docs/fb-token-setup.md`
- **社團不做自動化**（Groups API 已被 Meta 移除，瀏覽器機器人＝封號風險，使用者已同意不碰）。
  撒網靠粉專原文「分享」，原文一刪分享自動失效
- 其餘 v2 設計與建置步驟見 `docs/v2-handoff.md` 與 git log
