# Codex 文案服務

把 **ChatGPT 訂閱額度**接進 n8n 的廣告產文案，取代吃免費配額的 Gemini。

## 這是什麼

n8n（Railway 雲端）打不到店裡這台電腦，所以流程是：

```
n8n 產文案節點  ──→  Cloudflare Tunnel  ──→  這台電腦的 server.py  ──→  codex exec
                                                      │
                                                      └─ codex 掛了就自動改打 Gemini
```

服務**假裝自己是 Gemini**（收 Gemini 格式的請求、回 Gemini 格式的回應），
所以 n8n 那邊只改一個節點的 URL，workflow 結構完全不動。改壞了把 URL 改回去就復原。

## 已經驗證過的

| 項目 | 結果 |
|---|---|
| codex 產文案品質 | 一次就過 `數字守門員`，零查無出處數字 |
| 字數 | 粉專 178 字（要 150-260）／社團 73 字（要 50-80）|
| 速度 | 15～23 秒（n8n 節點逾時要調到 120 秒）|
| 用量 | 約 4,400 tokens／篇，一天 36 篇約 16 萬 tokens |
| 遵守數字規則 | 全形「Ｃ３６」「９＊９」原樣保留，沒自作主張改半形 |

## 安裝（一次就好）

### 1. 建 `.env`

```
CODEX_COPY_TOKEN=<自己隨便設一串長密碼>
GEMINI_API_KEY=<可選；codex 掛掉時的退路，不填就是少一層保險>
```

`CODEX_COPY_TOKEN` 一定要設——這個網址對外開放，沒密鑰任何人都能燒你的訂閱額度。

### 2. 確認 codex 能用

```
python server.py --self-test
```

看到 `✅ codex 正常` 才往下走。失敗的話先確認 `codex --version` 有反應、而且已登入 ChatGPT 訂閱。

### 3. 裝 cloudflared

```
winget install --source winget --id Cloudflare.cloudflared
```

**不用登入、不用網域。** 這個帳號的 Cloudflare 裡沒有自己的網域（查過，0 個 zone），
開不了「具名通道」那種固定網址，所以走**快速通道**：不需登入，但每次重開網址都會變。

網址會變沒關係——`--tunnel` 模式會**自己把新網址 PATCH 回 n8n**，並自動 deactivate + activate。
你完全不用碰 n8n。

### 4. 開機自動啟動

`Win+R` → 貼 `shell:startup` → Enter → 把 `啟動.vbs` 的捷徑丟進去。

`啟動.vbs` 跑的是 `--tunnel` 模式，開機後會自動：開服務 → 開通道 → 把網址寫回 n8n。

### 5. n8n 不用手動改

`--tunnel` 模式全包了。要自己確認的話，看 `廣告v3 掃描發文線` → `Gemini 產文案` 節點，
URL 應該長得像 `https://xxxx-xxxx.trycloudflare.com`。

## 日常

```
python server.py                 # 前景跑，看得到即時輸出
python server.py --self-test     # 只測 codex，不開服務
```

- 健康檢查：http://127.0.0.1:8787/health
- 紀錄：`logs/codex-copy.log`，每篇都會記是 codex 產的還是走了 Gemini 退路

## 會怎麼壞、壞了會怎樣

| 狀況 | 結果 |
|---|---|
| codex 逾時／吐不出 JSON | 自動改打 Gemini，n8n 無感 |
| codex 和 Gemini 都掛 | 回 502 → 那班失敗 → 觸發「系統錯誤 LINE 告警」 |
| 通道自己斷掉 | 每 5 秒偵測，自動重開並重新註冊新網址 |
| **正常關機／Ctrl+C** | **自動把 n8n 改回 Gemini**，電腦沒開的時段廣告線照樣發得出去 |
| **斷電（來不及善後）** | n8n 指著死掉的通道，那一班失敗並告警。開機後服務會自己接回來；
急著救就跑 `python server.py --revert` |
| 訂閱額度用完 | codex 會失敗 → 自動走 Gemini 退路 |

⚠️ **不要在整點～整點過 10 分之間手動改 n8n**（09/11/13/15/17/19 的 :00～:10）。
那是掃描發文線的煞車窗口，執行還在跑，deactivate + activate 有可能把它打斷。
2026-08-10 收工時差 7 秒就撞到。`--tunnel` 模式開機時註冊（約 07:30）不會撞到這個窗口。

⚠️ 這支**不做任何內容檢查**。產出的文案照樣要過 `數字守門員`，
寧可讓守門員擋下，也不要在這裡自作聰明修文案。

## 要退回 Gemini

把 n8n `Gemini 產文案` 節點的 URL 改回：

```
https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent
```

然後 deactivate + activate。這台電腦的服務可以繼續開著，不影響。
