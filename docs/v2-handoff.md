# 廣告系統 v2 建置交接包

> 給接手的 Claude：設計已全部拍板（見 STATUS.md「v2 改造計畫」），**不要重新討論架構**，照本文件順序執行即可。使用者是非工程師，每步先講「現在要做什麼、為什麼」再動手。
>
> 給使用者：開新 session 後貼這句就能開工：
> **「讀 docs/v2-handoff.md，帶我做下一個未完成的步驟」**

## 進度勾選（做完一步就打勾、commit）

- [x] 步驟 1：FB 永久金鑰（已完成：粉專「買房不費力,賣房好給力」FB_PAGE_ID=1041868522352339，FB_PAGE_TOKEN 已存進 n8n Credential「FB Page Token」）
- [x] 步驟 2：n8n 發文線（AI 已寫 `workflows/yc-fb-publish.json` + router 加「發」出口；⏳ 待使用者 import 兩支 JSON、設 FB Page Token credential、挑真實物件測試）
- [x] 步驟 3：下架線（AI 已改好 `yc-removal-detector.json`：網址 404/410 或下架關鍵字→自動刪 FB 貼文→標下架→LINE 通知；含防呆：站掛掉/被擋/逾時不誤刪、刪文失敗不標下架。⏳ 待使用者 import、綁 FB Page Token、開 cron）
  - 附帶修：`yc-property-create.json` 建檔器改抓 JSON-LD 的 `productID`（真物件編號如 YC1868705）當案件編號，取代原本的網址尾號。⏳ 待重匯
- [ ] 步驟 4：KEIS 腳本驗證（使用者在門市電腦跑兩個指令）
- [ ] 步驟 5：KEIS 駐守模式（步驟 4 通過後才做）
- [ ] 步驟 6：清舊（全部通過後才做）

---

## 步驟 1：FB 永久金鑰

**照 `docs/fb-token-setup.md` 一步步走**（已寫好完整教學）。

產出兩個值，都存進 n8n Credentials（不要寫進 git、不要貼在對話以外的地方）：
- `FB_PAGE_ID`：粉專 ID
- `FB_PAGE_TOKEN`：永久粉專權杖 → n8n 建 Header Auth credential，名稱 `FB Page Token`，Header：`Authorization: Bearer <權杖>`

**驗收**：用 n8n 手動 HTTP 節點（或瀏覽器）打
`https://graph.facebook.com/v21.0/{FB_PAGE_ID}?fields=name&access_token={權杖}`
回傳粉專名稱 = 成功。

## 步驟 2：n8n 發文線

**AI 做**：寫一支新 workflow `workflows/yc-fb-publish.json`，並改 `workflows/line-command-router.json` 加一個「發」出口。規格：

1. **觸發**：LINE 指令 `發 YCxxxxxxx`（router 新分支，關鍵字「發」開頭 + 案件編號）
2. **查 Notion**：data source `bcf8f493-4aac-45bf-8223-9b49f29aff63`，篩 `案件編號 = YCxxx`。必要欄位：`粉專文案`（空的就先跑文案產生，同 yc-property-create 的 Gemini 寫法）、`來源連結`
3. **抓照片**：GET `來源連結` 的 HTML，抽圖庫 image URL（og:image + 頁內圖片，永慶 CDN 是公開網址），取前 4-6 張
4. **發文（FB Graph API，用 `FB Page Token` credential）**：
   - 每張照片：`POST /v21.0/{FB_PAGE_ID}/photos`，body `{url: <圖片網址>, published: false}` → 收集回傳的 `id`
   - 貼文：`POST /v21.0/{FB_PAGE_ID}/feed`，body `{message: <粉專文案>, attached_media: [{media_fbid: id1}, ...]}` → 拿 `id`（格式 `pageid_postid`）
   - permalink：`https://www.facebook.com/{id}`
5. **回寫 Notion**：`粉專貼文連結` ← permalink、`狀態` ← `已發布`、`KEIS同步` ← `未同步`
6. **LINE Reply**（用 reply token，免費）：「✅ 已發布 → {permalink}」+ `社團文案` 全文 +「撒網社團直接按貼文的『分享』；重點社團複製上面文案貼原生文。發了原生文回我『發到 X 社團』」

**流程注意**：
- 「發」之前的預覽已存在——建檔完成時 LINE 回覆本來就帶文案，使用者看過才會下「發」指令，所以本 workflow 不用再做預覽步驟
- 社團記錄只記原生文（「發到 X 社團」→ append `廣告貼文紀錄`，沿用現有 4d 邏輯，可先不動）

**使用者做**：n8n 開**新的空白 workflow** → Import from File 貼 JSON（⚠️ 絕對不要在現有 workflow 裡 import，會覆蓋）→ router 同樣方式更新 → 挑一個真實物件測試整條線。

**AI 已完成**（2026-07-17）：`workflows/yc-fb-publish.json`（24 節點：查 Notion → 缺文案就 Gemini 產粉專+社團兩版並回寫 → 抓來源連結照片取前 6 張 → FB `/photos` 逐張上傳拿 media id → `/feed` 發多圖貼文 → 回寫 Notion `粉專貼文連結`/`狀態=已發布`/`KEIS同步=未同步` → LINE Reply 帶社團文案）＋ router 加「發」出口。兩支 JSON 已複製到 `桌面\json\`。

**AI 已代匯入（2026-07-20，用 GitHub raw URL Import from URL，免檔案對話框）**：
- n8n 已有兩支新 workflow（都已存檔、含全部節點、尚未啟用）：
  - `YC 發文線（發 YCxxx）`（24 節點，= yc-fb-publish.json）
  - `LINE 指令分流器 v2（含發文線）`（= line-command-router.json）
- 已確認 credential `FB Page Token`（Header Auth）存在於 n8n。

**使用者剩下要做（照順序，都很簡單）**：
1. 開 `YC 發文線（發 YCxxx）`。若畫布空白按左下 ⛶（Zoom to Fit）。三個 FB 節點（「FB 上傳照片」「FB 發貼文（附圖）」「FB 發貼文（純文字）」，會有紅色驚嘆號）各點開 → Credential 欄選 `FB Page Token` → Save → **Publish/啟用**。
2. 啟用 `LINE 指令分流器 v2（含發文線）`；把**舊的**「LINE 指令分流器」（沒有 v2）**停用**（同時只能一個 active）。
3. 挑一個**已建檔、狀態還不是已發布**的真實物件，LINE 傳「發 YCxxx」測。

**測試注意**：第一次測若粉專貼文沒帶照片或帶到 logo，是照片抽取 regex 沒對到永慶該頁的圖片網址格式——把那個物件的永慶網址貼給 AI 調 `整理照片` 節點即可，其餘流程不受影響。

**驗收**：LINE 傳「發 YCxxx」→ 粉專出現含照片貼文 → Notion 連結/狀態正確 → LINE 收到回覆（含社團版文案）。

## 步驟 3：下架線

**AI 做**：改 `workflows/yc-removal-detector.json`，在「判定下架」之後加：
1. 若 `粉專貼文連結` 有值 → 從 URL 取 post id → `DELETE /v21.0/{post_id}`（用 `FB Page Token` credential）
2. 成功 → PATCH Notion `狀態=下架` 照舊，LINE Push 文案改為：「YCxxx 已下架，粉專貼文已自動刪除（分享文已全部失效）。你貼過原生文的社團：{廣告貼文紀錄}」
3. 刪文失敗 → 不要標下架，LINE Push 故障通知（附錯誤訊息）

**使用者做**：import（開新空白 workflow 同上）→ 把 cron（每日 09:00）打開——舊的「等額度」理由早就過期，直接開。

**驗收**：拿一個已下架的舊物件手動跑 `/yc-check-removed` webhook 看整條線。

## 步驟 4：KEIS 腳本驗證（可以和步驟 1-3 不同天做，互不擋）

**使用者做**（在門市電腦，照 `scripts/keis/README.md`）：
1. `python publish.py --login` → 手動登入 KEIS 一次 → 關瀏覽器
2. `python publish.py YC1868650`（這件還沒上架，成功就順便完成了）

**失敗時**：會自動截圖 `keis_error_YC1868650.png`，把截圖丟給 AI 修 selector，改完再跑。第一次跑失敗是預期內的，不用緊張。

## 步驟 5：KEIS 駐守模式（步驟 4 通過才做）

**AI 做**：把 `scripts/keis/publish.py` 加 `--watch` 模式：
- 每 10 分鐘 query Notion：`狀態=已發布 AND KEIS同步=未同步 AND 粉專貼文連結 非空`
- 有結果就跑既有上架流程（含「已新增過」視為成功的分支）→ 標 `已同步`
- 失敗：截圖 + 印 log，**同一物件連續失敗 3 次就跳過並停止重試**（避免無限撞牆），等人工處理
- 比照 `grab.py` 的駐守方式做一個 `.bat` 開機自啟

**使用者做**：門市電腦跑起來，掛著。

## 步驟 6：清舊（前面全部驗收通過才做）

- 砍 n8n `yc-rewrite-copy` workflow + router 的「生成文案」出口（git 裡對應檔案也刪）
- `.claude/skills/yc-ad/SKILL.md` 改寫：降級為維修工具（查物件狀態、重產文案、手動補記錄），刪掉 KEIS 指令包和回報流程
- STATUS.md 更新：v2 計畫段落改成「已上線」的精簡描述，刪掉建置細節

---

## 額度原則（步驟 2、3 寫 workflow 時遵守）

- 使用者觸發的一律 LINE **Reply**（免費），不用 Push
- 成功不推播；主動 Push 只有兩種：下架完成、故障
- 現有其他工具的通知**不要動**（使用者要求原樣保留）
- 守門員（查 quota API、>160 擋非緊急）：做步驟 2 時順手加，不單獨做
