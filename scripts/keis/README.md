# KEIS 廣告上架自動化

把粉專已發布的物件自動同步上 KEIS 廣告追蹤平台。**不存帳密在程式裡** — 你手動登入一次，session 寫進 `profile/` 資料夾，之後跑就自動帶。

## 用法

```bash
# 第一次（或 session 過期）— 開瀏覽器手動登入一次
python publish.py --login

# 之後每次上架
python publish.py YC1868650
python publish.py YC1868650 --headed   # 看瀏覽器跑（debug 用）
```

## 第一次設定

```bash
cd scripts/keis
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# 編輯 .env 填 Notion token（KEIS 帳密不用填，下一步手動登入）

python publish.py --login
# 瀏覽器跳出 KEIS 登入頁 → 你手動登入 → 關掉瀏覽器 → session 存好
```

## 之後跑

```bash
python publish.py YC1868650
```

腳本會：
1. 從 Notion 撈該物件的「來源連結」+「粉專貼文連結」
2. 開無頭瀏覽器（用 `profile/` 內 session 自動登入 KEIS）
3. 點新增廣告 → 自動填表 → 送出
4. 成功 PATCH Notion `KEIS同步 = 已同步`
5. 失敗截圖存 `keis_error_<YCxxx>.png`

session 過期會提示你重跑 `--login`。

## 已知會卡的地方

- **欄位 selector**：用了 `get_by_label("帳號")` 這種通用寫法，跑不準再用 DevTools 查實際 selector 調
- **「自動填入」按鈕等 3 秒**：寫死 `wait_for_timeout(3000)`，KEIS 慢的話可能要拉長
- **「新上架」確認文字**：腳本用文字 match，若 KEIS UI 字串不同要改

## 之後可以怎麼擴

- 包成 FastAPI webhook 部到 Railway，n8n 從 LINE 觸發 `上架 KEIS YC1868650` 就自動跑
  - 雲端跑的話 session 持久化會比較複雜（要把 profile/ 上傳到雲端 / 用 cookies 匯出匯入）
- 或包成 yc-ad skill 內建工具，skill 第 4b 步驟直接 call 腳本，不再產操作指令包

---

# 公買搶單 grab.py

掃「查詢公買 → 買屋需求列表」，把還能申請（`status=Available`）且符合條件的最新名單自動按
「申請私買」，搶到後拿到**沒遮罩的真實姓名＋電話**，推一筆到 LINE。跟 `publish.py` 共用
同一個 `profile/` 登入 session（登入一次兩支都能用）。

## 用法

```bash
python grab.py --login                  # 第一次：手動登入一次，session 存進 profile/
python grab.py                          # 單次 dry-run：列出「這次會搶誰」，不送出
python grab.py --apply                  # 單次實搶
python grab.py --watch                  # 常駐監控(dry-run)：早上時段高頻掃，只印不搶
python grab.py --watch --apply          # 常駐監控 + 實搶（正式用這個）
python grab.py --watch --apply --headed # debug：顯示瀏覽器
```

**第一次務必先 dry-run**（`python grab.py` 或 `python grab.py --watch`），確認列出的名單符合預期（縣市、類型對不對），再開 `--apply` 實搶。

## 搶快：watch 常駐監控

觀察到的節奏：名單**每天早上批次釋出**，~08:19 起全店一群同事集中搶，**前 10 分鐘掃掉一大半**，一小時內收尾（爛名單才留到最後）。所以 watch 模式只在早上時段火力全開：

- 監控時段內 → 每 ~20 秒（帶隨機抖動）掃一次，逮到符合條件的新名單**立刻搶 + 推 LINE**
- 時段外 → 睡到下一個窗口，不狂打
- 配額用完 → 當天收工（只想要新名單，配額滿就沒得搶了）
- session 過期 → 推 LINE 提醒並停下，重跑 `--login` 後再啟動

監控時段／頻率改 `grab.py` 的 `WATCH_WINDOWS`（預設 `[("07:50","09:30")]`，本機時間）、`POLL_INTERVAL_SEC`。
常駐跑法：開一個終端機跑 `python grab.py --watch --apply` 讓它一直開著，或用排程器/服務管理(Windows 工作排程器設「登入時啟動」、Linux systemd/supervisor)讓它開機自動跑。

## 設定（改 `grab.py` 最上面的 CONFIG 區塊）

| 變數 | 預設 | 說明 |
|---|---|---|
| `CITIES` | `["高雄市"]` | 只搶這些縣市；`[]` = 不限 |
| `PROPERTY_TYPES` | `[]` | 物件類型白名單，例 `["透天","大樓"]`；`[]` = 全收 |
| `MIN_BUDGET` / `MAX_BUDGET` | `None` | 預算(萬)範圍；只比對有填預算的名單 |
| `MAX_APPLY_PER_RUN` | `None` | 每次最多搶幾筆；`None` = 搶到當日配額用完為止 |
| `DRY_RUN` | `True` | 預設只預覽不送出；`--apply` 會關掉它 |

搶單會自動受**今日配額**（API 回傳的 `new_case_quota_remaining`）夾住，配額用完就停手。
搶到的名單會 append 到 `grabbed.csv`（已 gitignore，含真實個資不會進版控）。

## 背後 API（從 HAR 逆出來的）

```
GET  /api/v1/call-purchase/query?inquiry_type=1&page=1&page_size=20&start_date=...&end_date=...
     → data[].status: "Available"=可申請 / "CoolingDown"=已被申請(7天)
     → meta.new_case_quota_remaining = 今日剩餘配額
POST /api/v1/call-purchase/apply/{summary_id}   （無 body）
     → {"success":true,"data":{"display_name":"賴先生","phone_number":"2852068"}}
```

## 每小時自動跑

**先用本機排程器跑通**（電腦要開著）：
- Windows 工作排程器 → 每小時執行 `python <路徑>\grab.py --apply`
- Mac/Linux crontab → `0 * * * * cd /path/scripts/keis && .venv/bin/python grab.py --apply`

## 搶到推 LINE（接 n8n）

`.env` 設 `KEIS_NOTIFY_WEBHOOK` 後，腳本會 POST 到 n8n。兩種 `event`：

搶到名單：
```json
{ "event": "grabbed",
  "grabbed": [ { "summary_id": 62867, "name": "賴先生", "phone": "2852068",
                 "city": "高雄市", "category": "店面", "budget": "380萬",
                 "start_time": "2026-06-22T13:10", "grabbed_at": "..." } ],
  "quota_left": 5 }
```

警示（session 過期等）：
```json
{ "event": "alert", "text": "⚠ KEIS 公買搶單監控停止：登入 session 過期，請重新登入並重啟。" }
```

n8n 端最小設定：**Webhook 節點**（path `keis-grab`）→ 依 `event` 分流 → **HTTP Request 打 LINE Push**
（用既有 `LINE Channel Access Token` 憑證，to = 薛力瑜 userId `Ufab42c56b2eb9b9a9ff18c367b85a6dd`），
把 `grabbed[]` 或 `text` 組成訊息推出去。要的話我可以幫你產這支 workflow JSON。

## 注意

- **每小時大概率撈到的都已被同事秒搶**（新名單幾分鐘內就鎖定）。要搶快得縮短間隔，但那比較吃配額、在內網也較敏感，節奏自己拿捏。
- 配額一天 7 筆（六個月內案源），盲搶最新會把配額花在不想要的名單上 → 善用 `CITIES`/`PROPERTY_TYPES`/預算篩選。

---

# 雲端全自動版（n8n，不用開電腦）

`grab.py --watch` 要電腦一直開著；搶單時段你還在睡 → 改跑在 Railway 上的 n8n。
因為 KEIS 有乾淨的 JSON API + JWT 登入，**n8n 用 Code 節點就能全自動跑，不需要瀏覽器**。

workflow 檔：`workflows/keis-grab-watch.json`

## 認證（從登入 HAR 逆出來）

```
POST /api/v1/auth/login?device_type=desktop   （form: username, password）
→ {"access_token":"<JWT>", "token_type":"bearer", "expires_in":28800}   # 8 小時
後續：GET query / POST apply 帶 Authorization: Bearer <access_token>
```

workflow 的 Code 節點會自己登入拿 token、快取 8 小時、過期自動重登。

## 上線步驟

1. **Railway 設兩個環境變數**（n8n 服務的 Variables）：`KEIS_USERNAME`、`KEIS_PASSWORD`。
   帳密只放這裡，**不寫進 workflow JSON、不進 git**。
   （n8n 若設了 `N8N_BLOCK_ENV_ACCESS_IN_NODE=true` 要拿掉，否則 Code 節點讀不到 `$env`。）
2. n8n **開一個新的空白 workflow** → 匯入 `workflows/keis-grab-watch.json`（依專案慣例：不要在既有 workflow 上 import 覆蓋）。
3. LINE 推播沿用既有 `LINE Channel Access Token` 憑證（已綁在節點上），推給薛力瑜 userId。
4. **先手動 Execute 一次測**：確認登入成功、能撈到清單。若 query/apply 回 401，代表這站不是吃 Bearer 而是 cookie，回報我改。
5. 確認沒問題 → workflow 設 **Active**，它每 30 秒觸發、自己卡 07:50–09:30（台北時間）才動作，搶到推 LINE。

## 設定都在 Code 節點最上面

`CITIES`（預設 `["高雄市"]`）、`PROPERTY_TYPES`、`INQUIRY_TYPE`、`WINDOWS`（預設 `07:50–09:30`）。
搶單受當日配額夾住，配額用完當天就不再搶。

## ⚠️ 安全

- 帳密只進 Railway 環境變數。登入 HAR（含明碼密碼）別流出；目前 KEIS 密碼偏弱，可考慮換強一點（換了記得更新 Railway 環境變數）。
- 這是跟同事搶共用名單，節奏／時段自己拿捏。
