# 永慶博愛凱璿 n8n 廣告系統 — STATUS

> 規則：完成的項目直接刪掉，不留歷史。歷史看 git log。

最後更新：2026-05-06
使用者：薛力瑜（永慶不動產 博愛凱璿加盟店）

---

## 系統入口

| 項目 | 值 |
|---|---|
| n8n URL | https://primary-production-68428.up.railway.app |
| 託管 | Railway（$5/月，Primary + Worker + Redis + Postgres）|
| LINE Bot | 工作助理 `@435awekw`（Channel ID `2009910157`，Provider「大王」）|
| LINE Webhook | `…/webhook/766bd943-f56c-4f78-b727-20e0d107d26a` |
| Notion 廣告資料庫 | `07ee845168b64f8a9b5682e5069c733b` |

## Credentials

| 名稱 | n8n ID | 類型 | 用途 |
|---|---|---|---|
| `Notion account` | `T62CHdfWuY9iXKWk` | Notion API | n8n Notion 節點 |
| `Notion API Token` | `edOz4T0LC6EP41Ug` | HTTP Header Auth | HTTP Request 打 Notion API |
| `LINE Channel Access Token` | `OmFzUGgZ1xIpAAP5` | HTTP Header Auth | LINE Reply / Push |
| `Gemini API Key` | `GEMINI_CREDENTIAL_ID` | HTTP Header Auth | Gemini（Header: `x-goog-api-key`）|

> **Gemini credential 尚未建立**：到 n8n → Settings → Credentials → New → HTTP Header Auth，Header 名 `x-goog-api-key`，值填 Gemini API key，建好後把 ID 填進 `yc-property-create.json` 的 `GEMINI_CREDENTIAL_ID` 再重新匯入。

## 現有架構

```
LINE Webhook (/766bd943-…)
   ↓
LINE 指令分流 (Switch by command)
   ├── create  → 物件建檔器 (/yc-property-create)
   └── remove  → 撤除回報器 (/yc-property-remove)
```

- **物件建檔器**：抓 HTML → Gemini 解析 + 文案 → 查 Notion 判重（來源連結）→ 新建或 PATCH 更新 → LINE 回覆
- **撤除回報器**：抓 YC 編號 → Notion query → PATCH 已撤除確認 + 下架偵測時間 → LINE 回覆

## 接下來要做

### 🟡 廣告下架偵測（每日 cron）
- Schedule Trigger 09:00 Asia/Taipei
- query Notion：`已撤除確認 = false` 且 `狀態 ≠ 下架`
- 每筆 GET 來源連結（neverError: true）；status ≥ 400 或含「已下架／物件不存在／已成交」→ PATCH `狀態 = 下架`、`下架偵測時間 = now`
- LINE Push 摘要（需要薛力瑜的 LINE userId）

### 🟢 低優先
- AI 文案重產：sub-workflow，輸入 notionPageId + 文案風格，更新文案並版本 +1
- LINE 加 `生成文案 YCxxx` 指令觸發重產
- 物件照片：建檔器抓 og:image 寫進 Notion
