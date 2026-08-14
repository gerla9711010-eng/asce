# 買方配案

## ⚠️ 2026-08-14：i智慧 那條主流程已刪除

原本這裡是「房地存客需（含畫多邊形）→ 回頭去 i智慧 現查即時案源 → 去重 → 輸出/看板」，
i智慧 查詢/配對/看板整批（連同帳密設定範例、GUI、排程安裝腳本、桌面捷徑）**已刪除**，
不是搬去別的資料夾。**目前查詢功能是空的**，等找到替代資料源再重建。

舊實作想找回來查參考：`git log --diff-filter=D --summary -- scripts/buyer-match/`
（或直接 `git log -p -- scripts/buyer-match/buyer_match.py` 看某一支的完整歷史），
git 歷史都還在，只是工作目錄不留著。

已經一併處理的：
- Windows 排程 `buyer-match-daily`（每天早上跑整組配對）：已停用
- Windows 排程 `buyer-match-webview`（localhost:5001 看板）：**待手動停用**——這次改動
  嘗試用 `Disable-ScheduledTask` 停用被拒（Access is denied），要在門市電腦手動跑
  `Disable-ScheduledTask -TaskName 'buyer-match-webview'`（或工作排程器 GUI 右鍵停用）
- 手機看板 `yc-tools.pages.dev/buyer-match/`：資料不會再更新，是最後一次排程留下的舊資料，
  之後可以直接下架這個頁面或等接新資料源再重新部署

## 現在留著的東西

只剩 `foundi_need.py`：讀房地（agent.foundi.info）客需條件（客戶存好的圈選範圍/篩選
條件），轉成關鍵字清單＋篩選參數。這支**跟 i智慧 無關**，只是單純的「房地讀取」——
現在沒有任何東西在呼叫它（下游查詢還沒接新資料源），留著是因為這塊邏輯之後接新資料源
時大機率還用得到（DOM 選擇器、條件解析、大樓保險機制等，見檔案內註解）。

```powershell
cd scripts/buyer-match
py -m pip install -r requirements.txt   # 目前只需要 playwright
```

## 之後要怎麼接新資料源

1. 找到替代的即時案源（能查、能篩、有專員聯絡方式/分享連結，或至少有其中幾項）
2. 用 `git log -p -- scripts/buyer-match/buyer_match.py` 找回舊版介面設計
   （`match_areas()` 吃關鍵字清單+篩選參數、回傳 `Card` 清單）當參考，寫一支新的查詢腳本
3. `foundi_need.py` 的輸出（`FoundiNeed`）不用大改，本來就是設計成跟資料源無關的
   「條件」中介格式
4. 看板/去重/排程那幾支（`manifest.py`／`build_static_view.py`／`webview_server.py`／
   `seen_store.py`／`daily_run.py`）架構可以照抄舊版（同樣用 `git log -p` 找回來看），
   換掉呼叫查詢那一行就好，不用重新設計

## 檔案

| 檔 | 用途 |
|---|---|
| `foundi_need.py` | 讀房地客需條件（唯一還在用的模組，見上面說明） |
| `requirements.txt` | 目前只需要 playwright（給 `foundi_need.py`） |
| `output/`／`state/` | 舊排程留下的查詢結果/去重記憶（已 gitignore），保留給之後對照參考 |
