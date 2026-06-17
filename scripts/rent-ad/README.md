# 租屋廣告 LINE 文案產生器

用表單填入物件資訊 →「產生 LINE 文字」→「複製」貼到 LINE。
基於公版 `🌏廣告資訊公版🌏` 設計。

## 執行

只用 Python 內建 `tkinter`，免安裝任何套件：

```bash
python rent_ad_gui.py
```

Windows 可直接雙擊 `rent_ad_gui.py`（用 python.org 安裝的 Python 內建 tkinter）。

## 功能

- 分區塊填欄位：廣告資訊 / A.物件資訊 / B.物件內容 / C.物件設備 / D.案件備註 / E.創意
- 下拉、單選、勾選、文字框，對應公版的各種選項
- 空欄位自動略過，不會印出空白行
- C.物件設備用勾選，只有勾的才會出現
- 「複製」一鍵複製整段到剪貼簿，直接貼到 LINE
- 「清空表單」重來

## 改公版欄位

選項清單在 `RentAdApp` 類別最上面（`BUILDING_TYPES` / `FURNITURE` / `EQUIPMENT` / `OTHER`），
輸出格式在 `generate()` 方法，要調文字直接改那裡。
