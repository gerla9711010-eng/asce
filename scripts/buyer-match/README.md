# 買方配案

依條件（行政區/社區/路名 + 總價 + 房數等）掃 i智慧Pro 流通物件，逐筆取出物件規格、
承辦專員姓名/電話/店別，並點「分享」拿到 i智慧 公開分享網頁連結（免登入、客戶可直接開），
整理成一段文字，複製貼上就能傳給客戶。

啟動模式：**CDP attach**（跟桌面「自動比對專約」工具同一套手法）——開一個獨立 profile 的
Chrome（帶 `--remote-debugging-port=9223`），第一次手動登入 i智慧一次，之後腳本用
`connect_over_cdp` 連進去操作、不存帳密、不用處理登入流程。

## 日常用法（推薦：GUI，雙擊就能用）

雙擊 **啟動工具.vbs**（不會開黑窗，pythonw 背景執行）：

1. 按「啟動 Chrome」→ 第一次要在跳出的 Chrome 視窗手動登入 i智慧（is.ycut.com.tw），
   之後登入態會記住，不用再登
2. 填行政區/總價/房數等條件（只有行政區關鍵字必填）
3. 想先確認條件抓得對不對，先勾「只看筆數」跑一次（快，不開詳情頁）
4. 沒問題再取消勾、按「開始查詢」，跑完結果會顯示在畫面上、**自動複製到剪貼簿**，
   直接 Ctrl+V 貼給客戶

## 第一次設定（一次性，GUI/CLI 共用）

```powershell
cd scripts/buyer-match
py -m pip install -r requirements.txt
```

不需要 `playwright install chromium`——CDP attach 用的是你電腦上真的 Chrome，
不是 Playwright 自帶的瀏覽器。`chrome_profile/`（登入態）、`output/`（每次查詢存檔）都會
在跑的時候自動產生，不要外流／已 gitignore。

### 選填：讓過期自動重新登入（不用手動打帳密）

獨立 Chrome profile 沒有你平常 Chrome 記住的密碼，第一次登入之後 cookie 一般能撐一陣子，
但過期時預設要手動切到 Chrome 視窗重新輸入。想要過期也自動處理：

```powershell
cp .env.example .env
# 編輯 .env，填 ISMART_ACCOUNT / ISMART_PASSWORD
```

填了之後，腳本偵測到被導去登入頁會自動嘗試登入。**沒填也完全能用**，只是過期當下要自己手動登入一次。

⚠️ 這段自動登入用的是「找帳號/密碼欄位＋找登入按鈕」的通用選取器，因為目前還沒機會在不登出你
現有 session 的情況下先看過 i智慧登入頁長什麼樣。**第一次真的觸發、如果自動登入沒成功**，
腳本會印出清楚的訊息、退回原本「請手動登入」的流程，不會卡死——把那時登入頁的樣子（或截圖）
告訴我，我就能把選取器鎖精確，之後就不會再失敗。

## 進階：命令列模式

如果不想開 GUI，先雙擊 `open_real_chrome.bat` 開好 Chrome、登入 i智慧，再直接跑 .py：

```powershell
# 苓雅區、300~500萬，最多處理 15 筆（預設）
python buyer_match.py --district 苓雅區 --price-min 300 --price-max 500

# 多行政區（最多 3 個，逗號分隔）+ 房數 + 車位（有車位、限平面或昇降平面）
python buyer_match.py --district 苓雅區,三民區 --price-max 600 --rooms-min 2 --parking 有 --parking-type 坡道/平面,昇降/平面

# 社區/路名關鍵字（--area）可以單獨用，也可以跟 --district 併用做進一步縮小
python buyer_match.py --area 三多商圈 --price-max 800 --rooms-min 2 --limit 10
python buyer_match.py --district 苓雅區 --area 三多 --price-max 800

# 只想先看有幾筆符合、不逐筆開詳情頁抓專員/分享連結（快很多，適合先確認條件抓得對不對）
python buyer_match.py --district 苓雅區 --price-max 500 --list-only

# 除錯：開詳情頁但不點分享（不會跳確認視窗、不產生分享連結）
python buyer_match.py --district 苓雅區 --price-max 500 --dry-run --limit 3
```

| 參數 | 預設 | 說明 |
|---|---|---|
| `--district` | 不限 | 行政區，逗號分隔最多 3 個，例 `苓雅區,三民區`。走網站真的行政區下拉選單（不是文字比對），2026-07-28 截圖實測過 |
| `--area` | 不限 | 社區/路名關鍵字（丟進「編號、案名、社區、部份地址」搜尋欄），可跟 `--district` 併用；`--district`／`--area` 至少填一個，兩個都空會掃全高雄市 |
| `--price-min` / `--price-max` | 不限 | 總價區間（萬）——Python 端過濾（讀清單卡片文字），不是網站的總價下拉 |
| `--rooms-min` | 不限 | 至少幾房（讀「格局」欄位，如「2房」）——同上，Python 端過濾 |
| `--usage` | 不限 | 用途關鍵字，例 `住宅`（可排除店面/透天等） |
| `--parking` | 不限 | `無` 或 `有`。網站真的「進階搜尋→車位」篩選（不給就不動，維持網站預設「不限」，比較快） |
| `--parking-type` | 不限 | `--parking 有` 才有作用，逗號分隔多選：坡道/平面、坡道/機械、昇降/平面、昇降/機械、庭院、平移/機械、獨立車庫、塔式車位 |
| `--limit` | 15 | 最多處理幾筆詳情頁（每筆要開新分頁+點分享，筆數越多越久） |
| `--list-only` | off | 只列篩選後清單，不開詳情頁 |
| `--dry-run` | off | 開詳情頁抓專員資訊但不點分享 |

i智慧 預設就是總價由低到高排序，`--limit` 會拿排序後前 N 筆命中的（等於先給便宜的）。

⚠️ **`--price-min`/`--price-max`/`--rooms-min` 不是網站篩選，是 Python 讀清單資料後自己過濾**——
好處是不用碰更多 Angular 元件、夠準也夠穩；代價是掃描量沒有先被總價/房數縮小。單一行政區
（如苓雅區）整區筆數可能上千筆，`--list-only` 掃卡片有 15 頁（450 筆）的安全上限，超過會印
`翻頁達上限` 警告——這種情況建議加 `--district` 縮小（比純文字 `--area` 搜整區準且快，因為
是網站真的伺服器端行政區過濾，不是掃完全部再比對文字）。

## 跑完會怎樣

- 每筆物件整理成一段：標題／地址／用途格局屋齡坪數／總價＋編號／專員姓名電話／店別／
  i智慧公開分享連結。
- 全部結果印在畫面上、存成 `output/<時間戳>_<area>.txt`（已 gitignore）、
  **同時複製到剪貼簿**，直接 Ctrl+V 貼給客戶。

## 常見狀況

**「連不到 http://localhost:9223」**
`open_real_chrome.bat` 沒開，或背景還有沒關乾淨的 chrome.exe 把這次啟動併走了。
工作管理員砍掉全部 chrome.exe 再重跑 `open_real_chrome.bat`。

**「i智慧登入態過期」**
腳本會直接報錯提示。切到 `open_real_chrome.bat` 開的那個 Chrome 視窗重新登入 i智慧，
不用重開腳本、重跑一次指令即可。

**分享連結抓不到某幾筆**
`open_detail_and_fetch` 抓不到「分享」按鈕或跳出來的分頁逾時，會印 WARN 但不中斷整批，
那幾筆就只有規格+專員資訊、沒有連結。

## 檔案

| 檔 | 用途 |
|---|---|
| `啟動工具.vbs` | **推薦入口**（雙擊開 GUI、無 console 黑窗） |
| `gui_main.py` | GUI 主程式（Tkinter，黑底風格，內建啟動 Chrome / 查詢 / log / 複製） |
| `buyer_match.py` | 主邏輯（CLI 也可以直接跑這支，見上面「進階：命令列模式」） |
| `open_real_chrome.bat` | CLI 模式專用：開 Chrome（帶 CDP port）讓你手動登入。GUI 模式不用點這個，GUI 裡「啟動 Chrome」按鈕做一樣的事 |
| `chrome_profile/` | 登入態（自動產生、不要外流、已 gitignore） |
| `output/` | 每次查詢的結果存檔（已 gitignore） |
| `requirements.txt` | Python 依賴（playwright、pyperclip） |

## 之後可以怎麼擴

- 總價/房數/屋齡目前都是 Python 端過濾，沒有走網站的下拉/自訂範圍輸入框（那幾個要嘛是
  預設區間單選、要嘛是位置不好定位的自訂輸入框）。想要更快（先在伺服器端縮小掃描量）
  可以之後把這幾個也接上真的篩選欄位，做法跟 `--district`/`--parking` 一樣（開下拉→點選項/填輸入框）。
- 客戶名單目前是使用者自己看 Notion 手動決定要推給誰、手動貼過去，這支只負責「產出
  配對好的物件清單文字」。如果之後想要「輸入客戶名字 → 自動帶出他的需求條件」，
  可以加一段讀 Notion 客戶名單 DB（`3eb9902989534654976e2f677b6957b3`）撈備註欄位。
- **第二資料源候補：foundi**（agent.foundi.info，2026-07-28 瀏覽器實測過能力）——沒有公開 API，
  純伺服器渲染 HTML，要接的話得比照現在這支的 CDP attach 手法（不能用乾淨的 HTTP 呼叫）。
  優點：有地圖模式（區域均價/一週內上架篩選）、每筆物件有首刊上架時間+開價變動歷史；
  缺點：清單只給「行政區+路名」沒有門牌，門牌是靠總價/坪數/建築日期/樓層反查比對出「可能地址」
  （標「很吻合/部分吻合」，非保證正確），拿來給客戶前這欄要能過濾掉「部分吻合」或人工再確認。
