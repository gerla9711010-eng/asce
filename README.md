# asce — 永慶博愛凱璿 n8n 廣告系統

> **現況與待辦**：[`docs/STATUS.md`](docs/STATUS.md)（保持 100 行內）
> **查表**：[`docs/reference.md`](docs/reference.md)（系統 ID／credentials／Notion 欄位／指令／工具清單）
> **事故血淚史**：[`docs/incidents.md`](docs/incidents.md)（動紅線之前先看）
> **workflow 真相**：[`workflows/`](workflows/) 與 [`docs/n8n-live.md`](docs/n8n-live.md)（n8n_sync.py 產的）

## 給未來的 AI / 協作者

開新對話請先讀 `docs/STATUS.md`，需要查東西再翻 `reference.md` / `incidents.md`。
**不用再 fetch Notion**，那邊已停止維護。

## 給薛力瑜

n8n 改完任何 workflow，請：
1. n8n → 該 workflow → ⋮ → Download。
2. 蓋掉 `workflows/<對應檔名>.json`，commit 並 push。

這樣 repo 永遠是最新真相，下次任何人接手都不會誤差。
