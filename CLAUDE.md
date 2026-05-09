# 永慶博愛凱璿 n8n 廣告系統

## ⚠️ 開工前第一步（必做，否則你看到的是舊版本）

```bash
git fetch origin main && git rebase origin/main
```

Claude Code 每次開 session 會自動建新 branch，基礎點不一定是最新的 main。
不做這步，STATUS.md 和 workflows/ 都會是舊的，你會重做別人已經完成的事。

## 開工前必讀
1. 讀 `docs/STATUS.md`（系統入口、credentials、接下來要做什麼）
2. 讀 `workflows/` 目錄（workflow 真相在這裡，不在 Notion）

## 交接規則（每個 session 結束前必做）
1. **更新 `docs/STATUS.md`**：只保留「現在的狀態」和「接下來要做的事」。完成的項目直接刪掉，不留歷史，歷史留給 git log。
2. **workflow 有改動**：請使用者從 n8n 匯出 JSON 蓋掉 `workflows/` 對應檔案，再 commit。
3. **commit 訊息**：一行說明做了什麼就好。
4. **永遠推到 main**：不需要開 feature branch。

## 禁止事項
- 不要讓 STATUS.md 越來越長，完成的細節刪掉
- 不要從 Notion 讀取狀態，那邊已停止維護
- 不要在現有 workflow 裡直接 Import JSON，會覆蓋；一律開新空白 workflow 再匯入
