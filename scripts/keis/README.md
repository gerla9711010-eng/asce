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

掃「查詢公買 → 買屋需求列表」，把還能申請（`status=Available`）且符合條件的最新名單自動
申請私買，搶到後拿到**沒遮罩的真實姓名＋電話**，推一筆到 LINE。**純 HTTP，不需要瀏覽器。**

## ⚠️ 必須跑在門市網路（店裡電腦）

KEIS 公買功能**「僅限門市內使用」，伺服器擋 IP** — 雲端、家裡、手機都用不了，只有門市網路能用。
所以這支腳本要放在**店裡、連門市網路、且一直開著的電腦**上跑（例如公司電腦不關機）。
腳本啟動會先打 `check-ip` 確認；不在門市網路會直接 LINE 告訴你、不會空跑。

## 用法

```bash
python grab.py                  # 單次 dry-run：列出「這次會搶誰」，不送出
python grab.py --apply          # 單次實搶
python grab.py --watch          # 常駐監控(dry-run)：早上時段高頻掃，只印不搶
python grab.py --watch --apply  # 常駐監控 + 實搶（正式用這個）
```

帳密放 `.env`（`KEIS_USERNAME` / `KEIS_PASSWORD`），腳本用 API 登入拿 JWT、過期自動重登。
**第一次先 dry-run**（`python grab.py`），確認列出的名單符合預期（縣市、類型對不對），再開 `--apply`。

## 搶快：watch 常駐監控

觀察到的節奏：名單**每天早上批次釋出**，~08:19 起全店一群同事集中搶，**前 10 分鐘掃掉一大半**，一小時內收尾（爛名單才留到最後）。所以 watch 模式只在早上時段火力全開：

- 監控時段內 → 每 ~20 秒（帶隨機抖動）掃一次，逮到符合條件的新名單**立刻搶 + 推 LINE**
- 時段外 → 睡到下一個窗口，不狂打
- 配額用完 → 當天收工（只想要新名單，配額滿就沒得搶了）
- IP 被擋（離開門市網路）→ 推 LINE 提醒並停下

監控時段／頻率改 `grab.py` 的 `WATCH_WINDOWS`（預設 `[("07:50","09:30")]`，本機時間）、`POLL_INTERVAL_SEC`。

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

## 讓它在公司電腦「開機就自動監控」（門市網路）

目標：電腦一開著就自己盯，天天如此，不用手動開。用附的 `run.bat`：

1. 把 `grab.py`、`run.bat`、`.env` 三個放同一個資料夾（例如桌面 `keis`）。
2. **雙擊 `run.bat`** 就會開始監控（黑視窗會顯示 `👁 watch 啟動...`，時段外顯示閒置）。
3. 開機自動跑：`Win + R` → 打 `shell:startup` → Enter 開啟「啟動」資料夾 →
   把 `run.bat` **用右鍵拖進去 → 選「在此建立捷徑」**。以後開機/登入就自動啟動。

`run.bat` 會在 grab.py 意外結束（斷網、當機）時 **60 秒後自動重開**；grab.py 自己遇到
暫時性錯誤也會重試不死。運作紀錄寫在同資料夾 `watch.log`（可事後查發生什麼事）。

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

警示（IP 被擋等）：
```json
{ "event": "alert", "text": "⚠ KEIS 搶單：這台機器 IP ... 不在門市網路..." }
```

n8n 端最小設定：**Webhook 節點**（path `keis-grab`）→ 依 `event` 分流 → **HTTP Request 打 LINE Push**
（用既有 `LINE Channel Access Token` 憑證，to = 薛力瑜 userId `Ufab42c56b2eb9b9a9ff18c367b85a6dd`），
把 `grabbed[]` 或 `text` 組成訊息推出去。要的話我可以幫你產這支 workflow JSON。

## 注意

- **每小時大概率撈到的都已被同事秒搶**（新名單幾分鐘內就鎖定）。所以才用 watch 在早上時段每 20–30 秒掃。
- 配額一天 7 筆（六個月內案源），盲搶最新會把配額花在不想要的名單上 → 善用 `CITIES`/`PROPERTY_TYPES`/預算篩選。
- **不能放雲端**：公買功能鎖門市 IP，雲端 / 家裡 / 手機都被擋，只能跑在門市網路的電腦上。
- 帳密只進本機 `.env`（已 gitignore，不進 git）。目前 KEIS 密碼偏弱，可考慮換強一點。
- 這是跟同事搶共用名單，節奏／時段自己拿捏。
