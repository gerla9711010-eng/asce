# 永慶博愛凱璿 — n8n 廣告系統

此 repo 收錄薛力瑜（永慶博愛凱璿加盟店）所使用的 n8n workflow JSON，
以及 LINE Bot × Notion 廣告資料庫整合的設計文件。
n8n 本體部署於 Railway，這裡只放 **可匯入的工作流定義** 與設計筆記。

## 目錄結構

```
workflows/
  ad-listing-create-or-update.json   # 廣告物件建檔（防重複版本）
  ad-listing-mark-removed.json       # 「已撤除 YCxxx」LINE 指令處理
  ad-listing-removal-detector.json   # 廣告下架偵測（每日 cron）
  ad-listing-generate-copy.json      # AI 文案生成（Claude）
docs/
  handover-2026-05-04.md             # 交接單副本
```

## 廣告物件建檔 workflow

### 設計重點
- **判重 key**：`來源連結`（`https://buy.yungching.com.tw/house/<caseId>`）。
  這是交接單明確指定的唯一穩定 key —— 「案件編號」格式不一致，「案名」會撞名。
- **正規化**：`Normalize URL` 節點移除 query string / hash、強制 https、
  小寫 host，並把案件編號統一成 `YC` + 數字寫進 `案件編號` 欄。
  網址路徑保留原始前綴（永慶頁面同時支援 `7271623` 與 `YC7271623`），
  避免規範後反而 404。
- **存在則更新、不存在則新增**：`Notion: Lookup by 來源連結` 用 url equals 過濾，
  搭配 `IF existing?` 分流到 `Notion: Update Page` 或 `Notion: Create Page`，
  最後在 `Merge` 收合，由 `Build LINE Reply` 產生回覆字串。

### 節點圖
```
Sub-workflow Trigger
  → Normalize URL
  → Fetch 永慶 HTML
  → Parse Property HTML
  → Notion: Lookup by 來源連結
  → Attach Lookup Result
  → IF existing?
       ├─ true  → Notion: Update Page ─┐
       └─ false → Notion: Create Page ─┤
                                       → Merge → Build LINE Reply
```

### Sub-workflow 輸入
從「LINE 指令分流」呼叫，傳入：
| 欄位 | 型別 | 說明 |
| --- | --- | --- |
| `url` | string | 使用者貼上的永慶網址 |
| `lineUserId` | string | 用於 push message |
| `replyToken` | string | 用於 reply API（30 秒內有效）|

回傳：
```json
{
  "action": "新增" | "更新",
  "notionPageId": "...",
  "notionPageUrl": "...",
  "caseId": "YC7271623",
  "sourceUrl": "https://buy.yungching.com.tw/house/YC7271623",
  "replyText": "✅ 已新增：…",
  "replyToken": "...",
  "lineUserId": "..."
}
```

### 匯入步驟（Railway n8n）
> ⚠️ 交接單規則：**先開新的空白 workflow 再 Import**，
> 絕對不要在現有 workflow 裡 Import，否則會覆蓋舊的。

1. n8n → Workflows → New → 開一個新的空白 workflow。
2. 右上「⋮」→ Import from File，選 `workflows/ad-listing-create-or-update.json`。
3. Credentials 修正：
   - 三個 Notion 節點（Lookup / Update / Create）目前都填 `REPLACE_WITH_NOTION_CREDENTIAL_ID`，
     需於 n8n 建好「**n8n 廣告系統**」這個 Notion API credential（用交接單裡那把 token），
     然後在每個 Notion 節點下拉重新選一次。
4. 在「LINE 指令分流」workflow 中，原本的「建檔 \[永慶網址\]」分支
   改成「Execute Workflow」節點，呼叫此 sub-workflow，把使用者訊息中
   解析出的 URL 與 `replyToken` 一併傳入；把回傳的 `replyText` 接到
   LINE Reply Message 節點即可。
5. 用「Execute workflow」按鈕加 pinned data 試跑一次，確認：
   - 第一次跑 → Notion 出現新頁（狀態=草稿、文案版本=0）。
   - 第二次跑相同 URL → 走 `Notion: Update Page`，**頁面不會重複**。
6. 通過後 **Publish**，並在 Version name 註明「廣告物件建檔 v1（防重複）」。

## 其他 workflow

### 已撤除 YCxxx — `ad-listing-mark-removed.json`
- Sub-workflow，輸入 `{ caseId, lineUserId, replyToken }`。
- 案件編號正規化（接受 `7271623` / `YC7271623`），查 Notion → 找到則
  `已撤除確認 = true`、`狀態 = 下架`、`下架偵測時間 = now`；找不到則回覆提示。
- 在「LINE 指令分流」的「已撤除」分支用 Execute Workflow 接上即可。

### 廣告下架偵測 — `ad-listing-removal-detector.json`
- 每日 09:00 cron，掃描 `已撤除確認 = false` 且 `狀態 ≠ 下架` 的物件。
- 對每筆 GET 來源連結（`neverError: true`，不會把 4xx 當失敗），
  status ≥ 400 或頁面內含「已下架／物件不存在／已成交」即標為下架，
  並更新 `狀態 = 下架`、`下架偵測時間 = now`。
- 最後彙整成單一 LINE push 摘要（要實際送出可在 Build Summary
  後再串一個 LINE Send Message 節點）。

### AI 文案生成 — `ad-listing-generate-copy.json`
- Sub-workflow，輸入 `{ notionPageId, style? }`；style 留空時讀 Notion
  既有的 `文案風格`。
- 用 Anthropic Messages API 直接 HTTP 呼叫（model 預設 `claude-sonnet-4-6`，
  需要時改 Build Prompt / HTTP body 即可換模型）。
- 寫回 `產生的文案`、`文案版本 += 1`、`文案風格`。
- Credential：建一個 **HTTP Header Auth** credential，
  Header name `x-api-key`、value 放 Anthropic API Key，把
  HTTP Request 節點上 `REPLACE_WITH_ANTHROPIC_CREDENTIAL_ID` 換掉。

## 剩下的人工接線（n8n UI）

- [ ] Notion API credential「n8n 廣告系統」建立，並把所有 Notion
      節點上的 `REPLACE_WITH_NOTION_CREDENTIAL_ID` 換掉（共 4 個 workflow）。
- [ ] Anthropic HTTP Header Auth credential 建立，並換掉
      `ad-listing-generate-copy.json` 裡的 `REPLACE_WITH_ANTHROPIC_CREDENTIAL_ID`。
- [ ] 「LINE 指令分流」：
      - 「建檔」分支 → Execute Workflow → `ad-listing-create-or-update`。
      - 「已撤除」分支 → Execute Workflow → `ad-listing-mark-removed`。
      - 各自把回傳的 `replyText` 接到 LINE Reply Message。
- [ ] 「廣告下架偵測」末端串一個 LINE Send（push 給薛力瑜）。
- [ ] 規劃何時觸發 AI 文案生成（建議：建檔成功後自動跑一次，或在
      LINE 加一個 `生成文案 YCxxx` 指令）。

## HTML 解析注意

`Parse Property HTML` 節點優先讀取 `<script id="__NEXT_DATA__">` 的 JSON，
解析失敗才退回 regex。永慶若改版，**只需要改這個節點**，其他流程不動。
若任何欄位拿不到，會以空字串／null 寫入；Notion 端不會因此爆掉。
