# 買方配案

依條件（行政區/社區/路名 + 總價 + 房數等）掃 i智慧Pro 流通物件，逐筆取出物件規格、
承辦專員姓名/電話/店別，並點「分享」拿到 i智慧 公開分享網頁連結（免登入、客戶可直接開），
整理成一段文字，複製貼上就能傳給客戶。

啟動模式：**CDP attach**（跟桌面「自動比對專約」工具同一套手法）——`open_real_chrome.bat`
帶 `--remote-debugging-port=9223` 開一個獨立 profile 的 Chrome，第一次手動登入 i智慧一次，
之後這支腳本用 `connect_over_cdp` 連進去操作、不存帳密、不用處理登入流程。

## 第一次設定（3 步）

1. **裝套件**（只需一次）：
   ```powershell
   cd scripts/buyer-match
   py -m pip install -r requirements.txt
   ```
   不需要 `playwright install chromium`——CDP attach 用的是你電腦上真的 Chrome，
   不是 Playwright 自帶的瀏覽器。

2. **開 Chrome 登入**：雙擊 `open_real_chrome.bat` → 開出來的 Chrome 視窗用你自己的
   帳號登入 i智慧（is.ycut.com.tw）。登入態存在 `chrome_profile/`（自動產生，不要外流、
   已 gitignore），之後不用再登，除非 session 過期。

3. **跑腳本**：
   ```powershell
   python buyer_match.py --area 苓雅區 --price-min 300 --price-max 500
   ```

## 用法

```powershell
# 苓雅區、300~500萬，最多處理 15 筆（預設）
python buyer_match.py --area 苓雅區 --price-min 300 --price-max 500

# 社區/路名關鍵字也可以（--area 其實就是丟進 i智慧 那個「編號、案名、社區、部份地址」搜尋欄）
python buyer_match.py --area 三多商圈 --price-max 800 --rooms-min 2 --limit 10

# 只想先看有幾筆符合、不逐筆開詳情頁抓專員/分享連結（快很多，適合先確認條件抓得對不對）
python buyer_match.py --area 苓雅區 --price-max 500 --list-only

# 除錯：開詳情頁但不點分享（不會跳確認視窗、不產生分享連結）
python buyer_match.py --area 苓雅區 --price-max 500 --dry-run --limit 3
```

| 參數 | 預設 | 說明 |
|---|---|---|
| `--area` | 必填 | 行政區/社區/路名關鍵字 |
| `--price-min` / `--price-max` | 不限 | 總價區間（萬） |
| `--rooms-min` | 不限 | 至少幾房（讀「格局」欄位，如「2房」） |
| `--usage` | 不限 | 用途關鍵字，例 `住宅`（可排除店面/透天等） |
| `--limit` | 15 | 最多處理幾筆詳情頁（每筆要開新分頁+點分享，筆數越多越久） |
| `--list-only` | off | 只列篩選後清單，不開詳情頁 |
| `--dry-run` | off | 開詳情頁抓專員資訊但不點分享 |

i智慧 預設就是總價由低到高排序，`--limit` 會拿排序後前 N 筆命中的（等於先給便宜的）。

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

## 之後可以怎麼擴

- 目前物件來源只走文字關鍵字（行政區/社區/路名），沒有直接操作「行政區」下拉選單——
  這個 Angular 自訂元件比較難自動化，用關鍵字搜尋 + Python 端二次過濾已經夠準、也更穩。
- 客戶名單目前是使用者自己看 Notion 手動決定要推給誰、手動貼過去，這支只負責「產出
  配對好的物件清單文字」。如果之後想要「輸入客戶名字 → 自動帶出他的需求條件」，
  可以加一段讀 Notion 客戶名單 DB（`3eb9902989534654976e2f677b6957b3`）撈備註欄位。
