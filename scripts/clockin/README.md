# houseol 自動簽到（clockin）

每天在 **9:00–10:00 之間的不規則時間**，自動到永慶博愛凱璿房管系統
（hq.houseol.com.tw）的「差勤系統」點【確認】簽到，然後推 LINE 回報。

## 它怎麼運作
- **Windows 工作排程器** 每天 09:00 觸發，設定了「隨機延遲 0~60 分」→ 落在 9:00–10:00 之間，每天時間不一樣。
- `clockin.py` 開差勤頁，**沒登入就用 `.env` 的店代號/帳號/密碼自動登入**（登入頁無驗證碼），
  然後**先勾【簽到】**（⚠️ 頁面預設是【簽退】！），再按【確認】。
- 結果 POST 到 n8n webhook（`workflows/clockin-notify.json`）→ 推 LINE 給薛力瑜。
- 帳密錯或登不進去不會默默失敗，會 LINE 通知你。

## 首次安裝（在那台會一直開機的電腦上）
```bash
cd scripts/clockin
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env          # ★ 打開 .env，把 HOUSEOL_PASS 填成你的密碼（店代號/帳號已預填）

python clockin.py --dry-run   # 演練：自動登入→確認進得到簽到頁、找得到簽到鈕，但不會真的送出

# 沒問題後，註冊每天自動跑的工作排程
powershell -ExecutionPolicy Bypass -File .\install-task.ps1
```
n8n 那邊：把 `workflows/clockin-notify.json` 匯入成一個**新的空白 workflow** 並 Activate。

## 平常用法
| 指令 | 作用 |
|---|---|
| `python clockin.py` | 正式：登入→勾簽到→按確認→推 LINE（排程跑的就是這個） |
| `python clockin.py --dry-run` | 演練，不真的送出 |
| `python clockin.py --login` | 備用：手動登入（萬一改用 LINE 登入 / 出現驗證碼時） |

## 注意
- **密碼只放 `.env`**，別貼進對話或 commit（`.env` 已被 `.gitignore` 擋）。
- 排程預設「使用者登入時才跑」。那台電腦上班時段要開機且維持登入。
- 想看它實際跑的畫面：`.env` 設 `CLOCKIN_HEADLESS=0`。
- log 在 `clockin.log`。
- 移除排程：`Unregister-ScheduledTask -TaskName 'houseol-auto-clockin' -Confirm:$false`
