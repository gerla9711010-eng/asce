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

### 3. 裝 cloudflared 並開通道

```
winget install --source winget --id Cloudflare.cloudflared
cloudflared tunnel login                          # 會開瀏覽器，選你的網域
cloudflared tunnel create codex-copy
cloudflared tunnel route dns codex-copy codex.<你的網域>
```

然後把設定寫進 `%USERPROFILE%\.cloudflared\config.yml`：

```yaml
tunnel: codex-copy
credentials-file: C:\Users\user\.cloudflared\<通道ID>.json
ingress:
  - hostname: codex.<你的網域>
    service: http://127.0.0.1:8787
  - service: http_status:404
```

裝成開機服務：

```
cloudflared service install
```

### 4. 開機自動啟動這支服務

`Win+R` → 貼 `shell:startup` → Enter → 把 `啟動.vbs` 的捷徑丟進去。

### 5. 改 n8n

`廣告v3 掃描發文線` → `Gemini 產文案` 節點：

| 欄位 | 改成 |
|---|---|
| URL | `https://codex.<你的網域>` |
| Timeout | `120000`（原本 60000，codex 比 Gemini 慢）|
| Header | 加一個 `X-Codex-Token` = 你的 `CODEX_COPY_TOKEN` |

⚠️ **改完一定要 deactivate + activate 一次**，否則排程觸發器還在跑舊版（2026-07-25 踩過）。

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
| **電腦沒開／店裡斷網** | 那班失敗並告警，兩小時後下一班會再試 |
| 訂閱額度用完 | codex 會失敗 → 自動走 Gemini 退路 |

⚠️ 這支**不做任何內容檢查**。產出的文案照樣要過 `數字守門員`，
寧可讓守門員擋下，也不要在這裡自作聰明修文案。

## 要退回 Gemini

把 n8n `Gemini 產文案` 節點的 URL 改回：

```
https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent
```

然後 deactivate + activate。這台電腦的服務可以繼續開著，不影響。
