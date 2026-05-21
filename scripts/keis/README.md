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
