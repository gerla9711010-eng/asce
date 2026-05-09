# 永慶博愛凱璿 n8n 廣告系統 — STATUS

> 這份是**唯一交接單**。Notion 那份請封存或刪掉，不再維護。
> 規則：未完成的事寫在這裡；workflow 真相 = `workflows/*.json`（從 n8n 匯出）。

最後更新：2026-05-09
使用者：薛力瑜（永慶不動產 博愛凱璿加盟店）

---

## 系統入口

| 項目 | 值 |
|---|---|
| n8n URL | https://primary-production-68428.up.railway.app |
| 託管 | Railway（$5/月，Primary + Worker + Redis + Postgres）|
| LINE Bot | 工作助理 `@435awekw`（Channel ID `2009910157`，Provider「大王」）|
| LINE Webhook | `…/webhook/766bd943-f56c-4f78-b727-20e0d107d26a` |
| Notion 首頁 | 永慶博愛凱璿（page id `32ad184ddd7080c8ba7cf732d0747211`）|
| Notion 廣告資料庫 | `07ee845168b64f8a9b5682e5069c733b`（data source `bcf8f493-4aac-45bf-8223-9b49f29aff63`）|
| Google OAuth 專案 | xueliyu-realestate（client id `937623665731-5on2s6ecqplbh59fb35e4n3sqa50i66i.apps.googleusercontent.com`）|
| 薛力瑜 LINE userId | `Ufab42c56b2eb9b9a9ff18c367b85a6dd`（用於 cron Push） |

## n8n Credentials（重要：兩個 Notion credential 不一樣）

| Credential 名稱 | n8n ID | 類型 | 用途 |
|---|---|---|---|
| `Notion account` | `T62CHdfWuY9iXKWk` | Notion API（n8n native）| 給 n8n Notion 節點用 |
| `Notion API Token` | `edOz4T0LC6EP41Ug` | HTTP Header Auth | 給 HTTP Request 直接打 Notion API 用 |
| `LINE Channel Access Token` | `OmFzUGgZ1xIpAAP5` | HTTP Header Auth | LINE Reply / Push |

> 寫新節點時，**走 n8n Notion 節點 → 用前者；走 HTTP Request → 用後者**。混用會踩雷。

---

## 現有架構

```
LINE Webhook (/766bd943-…)
   ↓
LINE 指令分流 (Switch by command)
   ├── create  ─HTTP POST→  物件建檔器 (/yc-property-create)
   ├── remove  ─HTTP POST→  撤除回報器 (/yc-property-remove)
   └── 其他    →            未知指令處理 → LINE 回覆
```

- **物件建檔器**：抓永慶 HTML → 清理 → **Gemini 2.5 Flash Lite** 解析 + 生成文案 → 寫 Notion → LINE 回覆。
- **撤除回報器**：抓 YC 編號 → Notion query by 案件編號 → PATCH `已撤除確認 + 下架偵測時間` → LINE 回覆。
- 兩條子流程都靠**內部 webhook 轉發**串接（不是 Execute Workflow）。

## Notion 廣告資料庫欄位（速查）

`案名`(title) / `案件編號` / `社區名稱` / `地址` / `建物類型`(select: 公寓/華廈/電梯大樓/透天/套房/店面/其他) / `格局` / `樓層` / `屋齡`(number) / `總價` / `單價` / `主建物坪數` / `公設坪數` / `建物坪數` / `土地坪數` / `附屬建物` / `特色說明` / `有無車位`(checkbox) / `車位類型`(select: 坡道平面/機械/法定/無) / `來源連結`(url) / `狀態`(select: 草稿/已發布/下架) / `已撤除確認`(checkbox) / `下架偵測時間`(date) / `文案風格`(select) / `產生的文案` / `文案版本`(number) / `物件照片`(file) / `廣告貼文紀錄` / `建立日期`(created_time)。

---

## 重要規則（不能忘）

1. **匯入 JSON 前一定先開新的空白 workflow**，絕不在現有 workflow 裡 Import，否則會覆蓋。
2. **廣告判重 key = 來源連結**（`buy.yungching.com.tw/house/{案件編號}`）。
   不要用「案件編號」（YC 前綴格式不一致）；不要用「案名」（會撞名）。
3. 所有新 Notion 資料庫一律放在「永慶博愛凱璿」首頁底下並嵌入。
4. 修改 Published workflow 後要重新 Publish，Version name 寫清楚。

---

## 未完成項目

### 🔴 高優先：物件建檔器加「防重複」
**問題**：同一網址貼第 2 次會在 Notion 開新一筆。
**作法**：在「解析 AI 輸出」和「寫入 Notion」之間插 3 個節點：
1. **HTTP Request — 查 Notion 是否已存在**
   - POST `https://api.notion.com/v1/databases/07ee845168b64f8a9b5682e5069c733b/query`
   - Credential: `Notion API Token`
   - Body: `{"filter":{"property":"來源連結","url":{"equals":"{{ $json.targetUrl }}"}},"page_size":1}`
2. **Code — 取出 existingPageId**
   ```js
   const ai = $('解析 AI 輸出').first().json;
   const existing = ($json.results || [])[0] || null;
   return [{ json: { ...ai,
     existingPageId: existing?.id || null,
     existingVersion: existing?.properties?.['文案版本']?.number ?? 0,
     action: existing ? '更新' : '建檔'
   }}];
   ```
3. **IF — `{{ $json.existingPageId }}` is not empty**
   - **True** → 新增一個 **HTTP PATCH** `https://api.notion.com/v1/pages/{{ $json.existingPageId }}`（同 credential），body 帶 properties；不要動「來源連結」「狀態」；`文案版本` 設 `existingVersion + 1`。
   - **False** → 接到原本的「寫入 Notion」（不動）。
4. 兩條都接到「組 LINE 回覆訊息」；訊息開頭改用 `{{ $('Code').first().json.action }}` 區分「建檔完成 / 更新完成」。

### ✅ 廣告下架偵測（每日 cron）— 已建置，待 LINE 額度重置後驗證
- workflow 邏輯已跑通（2026-05-09 測試：檢查 3 筆，全部在線，摘要組成正確）
- **唯一問題**：LINE 免費方案月額度（200 則）已用完，Push 節點 429 失敗；6/1 自動重置
- Push userId 已記錄：`Ufab42c56b2eb9b9a9ff18c367b85a6dd`
- 記得從 n8n 匯出 JSON 蓋到 `workflows/yc-removal-detector.json`

### 🟡 中優先：安全清理
- **Gemini API key** 寫死在物件建檔器「Gemini AI 解析 + 產文案」節點 URL：改成 Header Auth credential。
- **LINE token** 寫死在物件建檔器「LINE 回覆」Authorization header：改用既有 `LINE Channel Access Token` credential（指令分流和撤除回報器已經這樣用了，照抄）。

### 🟢 低優先 / 想到再做
- AI 文案重產（獨立 sub-workflow，輸入 `notionPageId` + 想要的 `文案風格`，更新 `產生的文案` 並 `文案版本 +1`）。
- LINE 加 `生成文案 YCxxx` 指令觸發上面的重產流程。
- `物件照片` 欄位目前沒寫入；如要支援要在建檔器抓 `og:image` / 永慶圖庫 URL 寫進去。

---

## 給下一個 AI 的話

1. 開工前先讀這份 `docs/STATUS.md` 和 `workflows/` 目錄。
2. 改動 workflow 後，請使用者從 n8n 匯出 JSON 蓋掉 `workflows/` 對應檔案，再 commit。這樣 repo 永遠是真相。
3. 不要再 fetch Notion 來確認狀態 —— 那邊已停止維護。
