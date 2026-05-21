# KEIS 廣告上架自動化

把粉專已發布的物件自動同步上 KEIS 廣告追蹤平台，取代「貼給 Claude 瀏覽器擴充功能」的手動流程。

## 用法

```bash
cd scripts/keis
python publish.py YC1868650
python publish.py YC1868650 --headed   # 看瀏覽器跑（debug 用）
```

腳本會：
1. 從 Notion 撈該物件的「來源連結」+「粉專貼文連結」
2. 開 Playwright Chromium → 登入 KEIS → 點新增廣告 → 自動填表 → 送出
3. 成功後 PATCH Notion `KEIS同步 = 已同步`
4. 失敗會截圖存 `keis_error_<YCxxx>.png`

## 第一次設定

```bash
cd scripts/keis
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

cp .env.example .env
# 編輯 .env 填 Notion token、KEIS 帳密
```

## 已知會卡的地方

- **KEIS 登入欄位 selector**：用了 `page.get_by_label("帳號")` 通用寫法，跑不起來再用 DevTools 查實際 selector 調
- **「自動填入」按鈕等 3 秒**：寫死 `wait_for_timeout(3000)`，KEIS 慢的話可能要拉長
- **「新上架」確認文字**：腳本用文字 match，若 KEIS UI 字串不同要改

## 之後可以怎麼擴

- 包成 FastAPI webhook 部到 Railway，n8n 從 LINE 觸發 `上架 KEIS YC1868650` 就自動跑
- 或包成 yc-ad skill 內建工具（skill 第 4b 步驟直接 call 腳本，不再產操作指令包）
