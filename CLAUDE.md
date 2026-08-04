# 永慶博愛凱璿 n8n 廣告系統

## ⚠️ 開工前第一步（必做，否則你看到的是舊版本）

```bash
git fetch origin main && git rebase origin/main
```

Claude Code 每次開 session 會自動建新 branch，基礎點不一定是最新的 main。
不做這步，STATUS.md 和 workflows/ 都會是舊的，你會重做別人已經完成的事。

## 開工前必讀
1. 跑 `python scripts/n8n_sync.py --check`（10 秒，看 git 跟 n8n 有沒有分岔）
2. 讀 `docs/n8n-live.md`（**線上真正在跑什麼，以這份為準**）
3. 讀 `docs/STATUS.md`（現況＋接下來要做什麼，**控制在 ~120 行**）

另外兩份用到才讀，不要一開場就整份吞：
- `docs/reference.md`：查表用（系統入口、credentials、Notion 欄位、LINE 指令、架構、桌面工具）
- `docs/incidents.md`：事故完整經過。動到紅線相關的東西之前一定要看

⚠️ STATUS.md 記的是「當時的計畫」，`n8n-live.md` 記的是「現在的事實」。兩邊打架時信後者，
並且**當場把 STATUS.md 改對**——2026-07-23 就是因為沒人回頭驗證，「專員電話卡在帳密」這句
錯了好幾天沒被發現。

## 交接規則（每個 session 結束前必做）
1. **跑 `python scripts/n8n_sync.py`**：把 n8n 上的 workflow 全部拉回 `workflows/`，
   並重產 `docs/n8n-live.md`。不管這次是誰改的、改在哪邊，跑完 git 就等於 n8n。
   輸出裡的「分岔檢查」有 ⚠️ 就當場處理掉，不要留給下一個 session。
2. **更新 `docs/STATUS.md`**：只保留「現在的狀態」和「接下來要做的事」，**控制在 ~120 行**。
   完成的項目直接刪掉。事故經過寫進 `docs/incidents.md`（新的加最上面）、
   查表類的東西寫進 `docs/reference.md`，STATUS.md 只留一行連結過去。
3. **commit 訊息**：一行說明做了什麼就好。
4. **分支策略**：harness 會把 Claude 綁在 `claude/...` 分支上，直接 push main 會被 403 擋。流程是：push feature branch → 開 PR 合 main → merge。不要再嘗試直接 push main。

## 禁止事項
- 不要讓 STATUS.md 越來越長（超過 ~120 行就檢查有沒有東西該往 incidents.md / reference.md 搬）
- 不要從 Notion 讀取狀態，那邊已停止維護
- 不要在現有 workflow 裡直接 Import JSON，會覆蓋；一律開新空白 workflow 再匯入
- 不要手改 `docs/n8n-live.md` 和 `workflows/_map.json`，那是 n8n_sync.py 產的
- 用 Public API 改「已啟用」的 workflow 後，**一定要 deactivate + activate 一次**，否則排程觸發器還在跑舊版（2026-07-25 踩過：節點接好了但整班跳過）。
  另外子流程要先自己 activate，主流程才啟用得起來（否則報 `references workflow ... which is not published`）
