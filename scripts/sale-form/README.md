# 不動產售屋表自動填寫工具

謄本 PDF → 自動查 104 社區資料 + 高雄市使用分區 → 跳確認視窗逐項核對 → 產出售屋表 Excel。

## 檔案
- `gui_main.py`：主程式（tkinter GUI）+ 填表邏輯（`fill_excel`）
- `bot_104.py`：Selenium 駕駛 104woo（自動登入、搜社區）+ 高雄市使用分區查詢（`fetch_zoning`）
- `confirm_wizard.py`：開始產出前的逐項確認視窗

## 執行
```
python gui_main.py
```
（Windows 可雙擊 `啟動工具.vbs`）

## 本機相依（未進版控，在使用者本機 zip 內）
- `parser.py`：謄本 PDF 解析（`parse_land` / `parse_building` / `merge`）
- `template/sale_template.xltx`：售屋表 Excel 範本
- `output/`：產出資料夾
- 套件：`selenium`、`openpyxl`、Chrome + chromedriver

## 流程
1. 選土地 + 建物謄本 PDF
2. 「開啟 104（自動登入）」→ 自動帶入帳密登入
3. 「完成登入，自動產出」→ 解析謄本 → 搜 104 社區 → 查使用分區 → 確認視窗 → 產出
   （或不用 104，直接「開始產出售屋表」走純謄本路徑）

## 使用分區填表規則
- 住宅區 → 勾 B42（黃）+ E42 填種別國字（三、四…）
- 商業區 → 勾 B44（黃）+ E44 填種別國字
- 工業區 → 勾 G42（黃）+ K42 填「乙種工」之類
- 其他（市場用地等）→ G44 填整串文字並塗黃

## 注意
- 104 登入帳密寫死在 `bot_104.py`（`ACCOUNT` / `PASSWORD`）。
- 謄本門牌須為含「縣市＋行政區」的完整格式；舊版謄本若門牌缺縣市區，地址會不完整。
