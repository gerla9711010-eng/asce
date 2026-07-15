# 不動產售屋表自動填寫工具

> 狀態：🟢 全流程已實測通過（左營／三民多筆）。桌面 GUI 工具，與 n8n 無關、獨立執行。
> 未驗證的座標：工業區 K42「乙種工」寫法、車位多層細項（地上/地下、平面/機械、上中下橫移、入口）——需拿對應案件實際開 Excel 確認。

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

## 第一次設定
```
cp .env.example .env
# 編輯 .env 填入 104woo 登入帳密（WOO104_ACCOUNT / WOO104_PASSWORD）
```

## 本機相依（未進版控，在使用者本機 zip 內）
- `parser.py`：謄本 PDF 解析（`parse_land` / `parse_building` / `merge`）
- `template/sale_template.xltx`：售屋表 Excel 範本
- `output/`：產出資料夾
- 套件：`selenium`、`openpyxl`、`python-dotenv`、Chrome + chromedriver

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
- 104 登入帳密改放 `.env`（`WOO104_ACCOUNT` / `WOO104_PASSWORD`，已 gitignore）。⚠️ **舊版帳密曾寫死在 `bot_104.py` 並進了 git 歷史**（repo 是 public，等於已外洩）——2026-07-15 已改用 `.env`，但舊密碼本身務必去 104woo 換掉，改 code 救不回已外洩的舊密碼。
- 謄本門牌須為含「縣市＋行政區」的完整格式；舊版謄本若門牌缺縣市區，地址會不完整。
- **⚠️ 實際運行版在本機 `OneDrive\桌面\不動產售屋表工具_v3.4\zipinspect\`，git 這份只是副本**。改 git 不會影響本機在跑的工具，兩邊要同步改。
- **`fill_excel()` 存檔前必須 `wb.template = False`**：範本是 `.xltx`，openpyxl 讀進來會記住範本旗標，不關掉存出的 `.xlsx` 內部類型會是 `template.main+xml`，嚴格版 Excel（別台電腦）直接拒開。已修（git + 本機兩份都改）。
