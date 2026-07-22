# 廣告自動化 v3 工單 — KEIS API 全自動發粉專 + 煞車 + 下架/重發輪替

> **狀態：2026-07-21 使用者已說「執行」，workflow JSON 全部寫完（見 §0.5）。目前卡在 KEIS token，尚未匯入 n8n。**
> 接手的模型：不要重寫這幾支 workflow，先讀 `workflows/yc-v3-*.json`。匯入前務必開「新空白 workflow」再 Import，不要蓋在既有 workflow 上。
>
> **使用者有 ADHD（見 memory `user-has-adhd`）**：面向使用者的操作要拆成單一步驟、先給預設值讓他只做「可以／不要／改這裡」的反應，一次只問一件事，回覆要短。

---

## 0. 一句話目標

n8n 定時打 **KEIS API** 撈整個加盟體系在售案 → 自動產文案 → **發文前 LINE 預告給煞車視窗** → 沒喊停就自動發粉專多圖文 → 自動偵測下架刪文 → 定時重發維持粉專活躍。Notion 只當紀錄帳本，社團使用者手動分享不記錄。

---

## 0.5 實作狀態（2026-07-21 已建，尚未匯入 n8n）

| 檔案 | 內容 | 狀態 |
|---|---|---|
| `workflows/yc-v3-scan-publish.json` | 線 A：掃描→清洗→Gemini→Notion 待發→LINE 預告→Wait 10 分→重查→FB 多圖發文→Notion 已發布→LINE 通知（26 節點） | ✅ 已寫，待匯入 |
| `workflows/yc-v3-removal.json` | 線 B：每日 08:00 查 Notion 已發布 → KEIS 查該件 → 判下架 → 刪 FB 文 → Notion 標下架 → LINE Push | ✅ 已寫，待匯入 |
| `workflows/yc-v3-stop.json` | 煞車：webhook `yc-v3-stop`，收「停」或「停 AGxxx」→ Notion 待發列標「取消」→ LINE 回覆 | ✅ 已寫，待匯入 |
| `workflows/line-command-router.json` | 加「停」出口轉發到上面的 webhook + 說明文字 | ✅ 已改，**需重新匯入**（覆蓋既有 router） |

**實作時與原規格的差異（以實作為準）：**

1. **一次只發 1 件**（原規格 §5 是一次選 N 件）。改用 cron `0 9,11,13,15,17,19 * * *`（一天 6 次）× 每次 1 件 ＝ 每日 ~6 篇，落在 §11 的 5–10 件區間。好處：避免「多物件 × 多照片」巢狀迴圈，直接沿用已驗證的單件流程，發文時間天然打散、較不會被 FB 判洗版。
2. **KEIS 精準查單件的參數是 `search=`**（實測：`search=AG1918041` 回 `total:1`；`keyword=` / `contract_no=` / `q=` 會被忽略、回全部 7010 筆）。線 B 用 `GET /api/v1/property-management/?page=1&page_size=1&search={contract_no}`。
3. **列表預設排序＝最新在前**（實測 `houseol_created_at` 由新到舊），所以線 A 直接取前 40 筆當候選池即可，不用額外排序參數。
4. **Notion「狀態」select 新增兩個值**：`待發`（煞車視窗中）、`取消`（被喊停）。Notion select 寫入時會自動建選項，不用先手動建。
5. **煞車不需要新增 Notion 日期欄位**：靠「待發」列 + Wait 10 分鐘後重查該列狀態實現。
6. **線 C（重發輪替）延後到第二階段**，先讓主線上線。

**唯一上線阻塞**：KEIS 長效 token → 建 n8n Header Auth credential（名稱 `KEIS API Token`），再把 JSON 內的 `KEIS_TOKEN_CRED_ID` 佔位（線 A 2 處、線 B 1 處）與 `FB_PAGE_TOKEN_CRED_ID` 換成實際 credential id。

---

## 1. 已拍板決策（2026-07-21，取代舊 v2 handoff 的建檔/發文假設）

1. **資料唯一來源＝KEIS API**（`keis.kshouse.com.tw`）。**不爬永慶官網、不爬 houseol、不碰屋主資料。**
2. **範圍＝KEIS 看得到的整個加盟體系在售案都可發**（同一老闆，不限本店）→ **不做店別過濾**。
3. **發佈＝24h 全自動 + 煞車**：發文前 LINE 先推「準備發這幾件」，給 N 分鐘視窗回「停」攔截；不回就自動發。
4. **物件 key＝KEIS `contract_no`**（例 `AG1918041`），不用 YCxxx。
5. **Notion＝純紀錄／輪替帳本**，不是控制中心、**不做草稿**。
6. **社團＝使用者個人帳號手動分享，不記錄**（粉專原文刪除，分享自動失效，無需追蹤）。
7. **照片＝從 KEIS API `images[].image_url` 自動抓**，不手動。

---

## 2. KEIS API 參考（實測 2026-07-21，同一 tab 已登入狀態下驗證）

- Base：`https://keis.kshouse.com.tw`
- **認證：Bearer token（JWT）**。前端存在 localStorage key `token_desktop`，呼叫 API 時帶 `Authorization: Bearer <token>`。直接開 API URL（無 header）會回 `401 無法驗證憑證`。
  - ⚠️ **唯一擋住產出最終 code 的未知數**：n8n 要怎麼拿 token。兩條路，執行前二選一確認：
    - (A)【首選】向 KEIS（自家後台）要一組**長效 service token / API 金鑰**，直接存 n8n credential。最省事、最穩。
    - (B) n8n 跑登入流程：`POST /api/v1/auth/login`（**端點待確認**，已知有 `GET /api/v1/auth/me`）帶帳密 → 取回 JWT → 後續帶 Authorization。JWT 若短效要處理 refresh。
- **列表端點**：`GET /api/v1/property-management/?page=1&page_size=20&listing_type=買賣`
  - `listing_type` 值：`買賣` / `租賃`（URL-encode）
  - 回傳：`{ total, page, page_size, items: [...] }`
  - item 欄位（廣告可用）：`contract_no, case_name, case_price(萬,number), property_type, layout, room_count, living_count, bathroom_count, main_area, total_area, total_floors, floor_info, floor_start, floor_end, community_name, property_address_city, property_address_district, property_address_road, school_info, official_url, image_count, is_active, status, store_name`
- **詳情端點**：`GET /api/v1/property-management/{id}`（`id` 為列表回傳的數字 id，非 contract_no）
  - 額外欄位：`property_address_detail`（完整門牌）, `unit_price`, **`feature_1`~`feature_5`（業務手寫賣點＝文案素材主來源）**, `images[].image_url`（照片網址陣列）, `parking_type/parking_method/parking_volume/parking_area`, `construction_date`, `age`, `mrt_station/train_station/bus_station`, `market_info`, `main_use`, `building_structure`, `store_name`
- **🚫 禁用欄位（屋主個資，絕不進 Notion / AI / FB / log）**：
  `seller_name, seller_mobile, seller_home_phone, seller_company_phone, seller_birthday, seller_gender, seller_id, seller_type, seller_address_city/district/road/detail, apograph_no, apograph_url`
  - 說明：詳情端點是「完整物件管理記錄（業務用）」，本來就含委託人資料。列表端點較輕（含 `seller_name` 但無電話）。**清洗節點必須白名單，只留下面 §3 列的欄位，其餘全 drop。**

---

## 3. 資料白名單（清洗 Code 節點｜可直接用）

放在「KEIS 詳情 → Gemini」之間。**只保留廣告欄位，屋主個資明確剔除。**

```javascript
// n8n Code 節點：KEIS 詳情 → 廣告白名單（屋主個資一律 drop）
const d = $input.first().json.data || $input.first().json;
const num = v => (v === null || v === undefined || v === '') ? null : Number(v);
const s   = v => (v === null || v === undefined) ? '' : String(v).trim();

// 賣點素材：只用業務手寫 feature_1~5 + 實際有值的機能欄位，禁止 AI 自行杜撰
const features = [d.feature_1, d.feature_2, d.feature_3, d.feature_4, d.feature_5]
  .map(s).filter(Boolean);
const facilities = {
  學區: s(d.school_info), 商圈: s(d.market_info),
  捷運: s(d.mrt_station), 火車: s(d.train_station), 公車: s(d.bus_station),
}; // 空字串的下游 prompt 不得使用

const clean = {
  contract_no: s(d.contract_no),                 // 物件編號＝主 key
  案名: s(d.case_name),
  總價萬: num(d.case_price),                       // 鎖死，AI 不得改
  單價: num(d.unit_price),
  建物類型: s(d.property_type),
  格局: s(d.layout),
  房: num(d.room_count), 廳: num(d.living_count), 衛: num(d.bathroom_count),
  主建坪: num(d.main_area), 建物坪: num(d.total_area),
  樓層: s(d.floor_info), 總樓: num(d.total_floors),
  社區: s(d.community_name),
  地址: [s(d.property_address_city), s(d.property_address_district), s(d.property_address_road)].join(''),
  完整門牌: s(d.property_address_detail),          // 是否用於文案由 §7 決定（隱私）
  屋齡: num(d.age),
  車位: [s(d.parking_type), s(d.parking_method)].filter(Boolean).join('/'),
  official_url: s(d.official_url),                // 客人連結 + 下架偵測目標
  images: (d.images || []).map(x => x.image_url).filter(Boolean),
  is_active: d.is_active === true,
  status: s(d.status),
  賣點: features,
  機能: facilities,
};
return [{ json: clean }];
```

---

## 4. 架構（三條線）

```
線 A  掃描 + 全自動發文（cron）          ← 主線，含煞車
線 B  下架偵測（cron，改用 KEIS is_active）← 沿用 yc-removal-detector 骨架
線 C  重發輪替（併入線 A 每日額度）        ← 維持粉專活躍、防沉底
```

---

## 5. 線 A：掃描 + 全自動發文（含煞車）｜節點序

1. **Cron**：預設每天 09:00 Asia/Taipei（tunable）
2. **KEIS 取 token**：HTTP（依 §2 (A) 或 (B)，**待確認後補**）
3. **KEIS 列表 GET**：分頁撈在售案（`listing_type=買賣`），彙整成 items
4. **過濾**：`image_count > 0`（沒照片不發）＋符合廣告池規則（**預設：有照片即進池**，tunable §8）
5. **對 Notion 帳本判重**：`contract_no` 已在帳本且「未到下次重發時間」→ 跳過（見 §9 判重 code）
6. **選今日要發 N 件**：預設 5–10 件、白天打散（tunable）
7. **逐件 KEIS 詳情 GET → §3 白名單清洗**（drop 屋主欄位）
8. **Gemini 產文案**：facts 鎖死、賣點只准用 `feature_1~5` + 有值機能，禁杜撰（見 §6 prompt）
9. **煞車**：LINE Push「準備發這幾件〔清單〕，10 分鐘內回『停 AGxxx』或『全停』可攔截」→ **Wait 節點 10 分鐘**
10. **檢查是否被喊停**：查攔截 flag（一個 Notion 欄位／KV／或掃 LINE 回訊）→ 未被停才續發；被停的件標記跳過
11. **FB 發文**：沿用 `workflows/yc-fb-publish.json` 的 `/photos`(published:false) 逐張上傳 → `/feed` 附 `attached_media` 多圖貼文（用 `FB Page Token` credential）。**照片改用 KEIS `images[]` 網址**
12. **寫 Notion 帳本**：`contract_no, 案名, 總價, 地址, 粉專貼文連結(permalink), 狀態=已發布, 發文時間, 下次重發時間=+7天, official_url`
13. **LINE 通知**：「今天發了這幾件 + 連結」（Push，非 Reply，因無使用者觸發）

---

## 6. Gemini 文案 prompt（防幻覺鎖死版｜可直接用）

```
你是房地產廣告文案。以下為官方結構化事實，全部為鐵律，禁止更改任何數字或新增未提供的資訊。

【鐵律事實】
案名：{{案名}}
總價：{{總價萬}} 萬（文案只能出現這個價格，禁止任何其他數字）
格局：{{格局}}　建物：{{建物坪}} 坪（主建 {{主建坪}} 坪）　樓層：{{樓層}}
地址：{{地址}}　屋齡：{{屋齡}} 年　車位：{{車位}}
建物類型：{{建物類型}}

【唯一可用的賣點素材】（只能用下列文字改寫，不得自行補學區/捷運/建材/商圈等未列資訊）
{{賣點 join 換行}}
機能（僅在有值時可提，空的不得杜撰）：學區 {{機能.學區}}／商圈 {{機能.商圈}}／捷運 {{機能.捷運}}

【產出】回傳 JSON：{"粉專文案":"…(200-300字)","社團文案":"…(50-80字,不放連結)"}
規則：開頭吸睛含 emoji；不得杜撰任何未提供事實；廣告不實有法律責任，寧可少講不可亂編。
```

程式端再保險：產出後把總價數字掃一遍，非 `{{總價萬}}` 的價格字串一律替換（沿用 `yc-property-create.json` 的鎖價後處理）。

---

## 7. 線 B：下架偵測（改用 KEIS）｜沿用 `yc-removal-detector.json` 骨架

- 對帳本內「狀態=已發布」的每件，查 KEIS 該 `contract_no` 的 `is_active`
- `is_active=false` 或 KEIS 查無此案 → 取 permalink 的 post id → `DELETE /v21.0/{post_id}`（FB Page Token）→ Notion 標「狀態=下架」→ LINE 通知「下架了這幾件」
- **防呆**：KEIS API 掛掉／逾時／回非預期 → 不判下架、不刪文，改推故障通知（避免誤刪）
- cron 預設每天一次（可與線 A 錯開）

---

## 8. 線 C：重發輪替（防沉底、維持活躍）

- 帳本中「狀態=已發布」且「發文時間 > 重發間隔」→ 刪舊 FB 文 → 重新發 → 更新 permalink + 下次重發時間
- **FB spam 防護（重要）**：重發時**變化照片順序 + 文案開頭**，避免被判定重複洗版；發文時間白天打散；重發量併入線 A 每日上限
- 預設重發間隔 7 天（tunable）

---

## 9. Notion 帳本判重 / 排程 code（可直接用）

```javascript
// 判斷某 contract_no 今天要不要（重新）發
const now = new Date();
const rec = $json.notionRecord; // 查 Notion 帳本（filter: contract_no equals）後帶入，可能為 null
if (!rec) return [{ json: { action: '首發' } }];
const status = rec.properties['狀態']?.select?.name;
if (status === '下架') return [{ json: { action: '跳過' } }];
const next = rec.properties['下次重發時間']?.date?.start;
if (next && new Date(next) <= now) return [{ json: { action: '重發', pageId: rec.id } }];
return [{ json: { action: '跳過' } }];
```

---

## 10. Credentials / 設定盤點

| 名稱 | 狀態 | 備註 |
|---|---|---|
| KEIS token | ⏳ **唯一待確認** | §2：要長效 service token（首選）或 login 流程 |
| FB Page Token | ✅ 已有 | Header Auth，發文/刪文 |
| Gemini API Key | ✅ 已有 | 產文案 |
| Notion API Token | ✅ 已有 | 帳本讀寫 |
| LINE Channel Access Token | ✅ 已有 | 煞車預告 + 通知（Push） |

---

## 11. 預設參數（先這樣跑，上線後看數據調）

| 參數 | 預設 | 可調 |
|---|---|---|
| 掃描/發文頻率 | 每天一次 | ✅ |
| 每日發文量 | 5–10 件，白天打散 | ✅ |
| 煞車視窗 | 發文前 10 分鐘 | ✅ |
| 重發間隔 | 同件 7 天 | ✅ |
| 廣告池規則 | 有照片即進池 | ✅ |

---

## 12. 驗收標準

- **線 A**：cron 觸發 → LINE 收到煞車預告 → 不回應 → 粉專出現含 KEIS 照片的貼文 → Notion 帳本記錄 permalink → LINE 收到「今天發了什麼」
- **煞車**：預告後回「停 AGxxx」→ 該件當日不發
- **線 B**：某件 KEIS `is_active=false` → 對應 FB 貼文被刪 → LINE 收到「下架了什麼」
- **線 C**：某件超過重發間隔 → 舊文刪、新文發、permalink 更新
- **隱私紅線**：全程 Notion / FB / log / AI prompt 都查不到任何 `seller_*` / `apograph_*` 欄位

---

## 13. 尚未定 / 使用者待辦（擺到最後）

- ⏳【上線前必解｜唯一阻塞】KEIS n8n 登入方式（長效 token vs login 流程）— §2 → 建 credential `KEIS API Token` → 換掉 3 處 `KEIS_TOKEN_CRED_ID` + 3 處 `FB_PAGE_TOKEN_CRED_ID`
- ⏳ 匯入 4 支 workflow（3 支新的開空白匯入；router 覆蓋既有那支）
- ⏳ 線 C 重發輪替（第二階段）
- 廣告池規則、頻率微調（先用 §11 預設，上線後調）
- （可有可無，2 分鐘）刪掉早前那篇有格局浮水印的 FB 測試文

---

## 14. 與舊 v2 的關係

- 舊 `docs/v2-handoff.md` 的「LINE 建檔 → 發 YCxxx」流程被本工單取代（資料源從 LINE 手貼永慶網址改成 KEIS API 自動掃）。
- **可沿用**：`yc-fb-publish.json`（FB 多圖發文機制）、`yc-removal-detector.json`（下架刪文骨架）、鎖價後處理邏輯。
- 清舊（全部上線驗收後）：LINE 建檔器 / yc-rewrite-copy / router 相關出口再處理，本工單先不動。
```
