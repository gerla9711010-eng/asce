# FB 權杖輪替（一次性任務，做完刪此檔）

**為什麼要做**：2026-07-16 建置步驟 1 時，系統使用者權杖和粉專權杖都曾貼進 AI 對話記錄，且瀏覽器歷史留有含權杖的網址。兩把都永久有效，需作廢重發。

**給執行的 AI**：全程權杖不能進對話——不要截圖權杖畫面、不要請使用者貼權杖給你、不要代貼權杖進任何欄位。你負責開頁面、指路；產生/複製/貼上一律使用者自己做。

## 既有資訊（不用重查）

| 項目 | 值 |
|---|---|
| 企業帳號 | 力瑜（`business_id=2155382731345675`）|
| 系統使用者 | `n8n-bot`（編號 `61591623195825`，Employee）|
| App | `kaixuan-ad-bot`（編號 `1291803849699074`，開發模式）|
| 粉專 | 買房不費力,賣房好給力（`FB_PAGE_ID=1041868522352339`）|
| n8n | https://primary-production-68428.up.railway.app → Credentials → `FB Page Token`（Header Auth）|

## 流程

1. **撤銷舊權杖**：開
   `https://business.facebook.com/latest/settings/system_users?business_id=2155382731345675&selected_user_id=61591623195825`
   → 按「**撤銷權杖**」把現有權杖作廢（⚠️ 只按「產生權杖」不會讓舊的失效，必須先撤銷）。
2. **產生新權杖**：同頁「產生權杖」→ App 選 `kaixuan-ad-bot` → 效期選「**永不**」→ 權限勾 4 個：`pages_show_list`、`pages_read_engagement`、`pages_manage_posts`、`business_management` → 產生 → **使用者自己複製**，暫存記事本。
3. **換粉專權杖**（使用者自己在瀏覽器網址列操作，權杖代入時**不要保留大括號**）：
   ```
   https://graph.facebook.com/v21.0/1041868522352339?fields=access_token&access_token=<步驟2的權杖>
   ```
   回傳 JSON 裡的 `access_token` = 新粉專權杖，複製暫存。
4. **驗證**（一樣使用者自己開）：
   - 讀取：`https://graph.facebook.com/v21.0/1041868522352339?fields=name&access_token=<新粉專權杖>` → 回粉專名稱即通。
   - 永久性：`https://graph.facebook.com/debug_token?input_token=<新粉專權杖>&access_token=<新粉專權杖>` → 確認 `expires_at` 為 `0`。
5. **更新 n8n**：Credentials → 打開 `FB Page Token` → Value 整欄清掉重填 `Bearer <新粉專權杖>`（Bearer 後面有一個空格）→ Save。
6. **收尾**：刪記事本暫存；清瀏覽器歷史中 `graph.facebook.com` 相關網址；刪掉本檔案並更新 STATUS.md 拿掉對應待辦，commit。

## 順帶待驗（步驟 2 發文線第一次測試時）

- 發文權限鏈路（`pages_manage_posts` + 粉專「內容」權限）尚未實測，讀取驗證不算數。
- App 在開發模式，第一篇真實貼文發出後，用**無痕視窗（未登入 FB）**確認路人看得到；看不到就把 App 切上線模式（自有資產不需送審）。
