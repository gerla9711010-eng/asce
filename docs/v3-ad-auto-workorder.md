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

---

## 15. 線 D：KEIS 廣告追蹤同步（2026-07-22 實作完成並實測）

**需求**：線 A 發完粉專 → 自動到 KEIS `ad-tracker` 新增一筆廣告紀錄（平台=臉書）；線 B 刪文下架 → 同一筆標成關閉。**已完成**。

### 15.1 KEIS 廣告追蹤 API（全部實測過）

認證同其他 KEIS API（`Authorization: Bearer <token>`，credential `KEIS API Token`）。

| 動作 | 端點 | 備註 |
|---|---|---|
| 進行中列表 | `GET /api/v1/adcases?is_expired=false&skip=0&limit=50&order_by=create_time&order_direction=desc` | |
| 已結束列表 | `GET /api/v1/adcases?is_expired=true` | |
| 單筆 | `GET /api/v1/adcases/{id}` | |
| **新增** | `POST /api/v1/adcases` | 必填只有 3 個：`adcase_title` / `adcase_url` / `adcase_member`，回傳含 `adcase_id` |
| **關閉** | `PUT /api/v1/adcases/{id}` body `{"is_expired": true}` | 局部更新，只送要改的欄位即可 |
| 刪除 | `DELETE /api/v1/adcases/{id}` | 軟刪除：兩個列表都查不到，但直接 GET id 仍回得到 |
| 統計 / 成員 | `GET /api/v1/adcases/dashboard/stats`、`GET /api/v1/adcases/members` | |

單筆欄位：
```
adcase_id, adcase_member(業務姓名), adcase_title, adcase_price(萬), adcase_road,
adcase_url          ← 永慶官網連結，格式 https://buy.yungching.com.tw/house/7411092
adcase_platforms    ← 平台字串，例 "591" / "臉書"
adcase_url591 / adcase_urlfacebook / adcase_urlinstagram / adcase_url5168 /
adcase_url579 / adcase_urlhaofun / adcase_urllewu / adcase_urltiktok /
adcase_urlwojia / adcase_uryoutube
closed_at, is_expired, hidden, url_invalid, offline_404_count, url_price, status_tags
```

⚠️ **`closed_at` 是唯讀**：PUT 送它會被無聲忽略（回 200 但值沒變）。關閉一律用 `is_expired: true`，送完就從進行中清單移到已結束清單。

⚠️ 這組端點是 FastAPI。**要探未知 schema 就送空 body 取 422**，錯誤訊息會直接列出缺哪些必填欄位（不會建資料），比開 DevTools 快。KEIS 沒有開 `/openapi.json`。

### 15.2 卡點解法：永慶官網連結怎麼查（已解）

KEIS 詳情端點 149 個欄位**全掃過，沒有任何永慶 product id**（`official_url` 是 houseol、`apograph_url` 是 hq.houseol）。houseol 的 `H888-S2981289` 也對應不到。所以只能反查永慶官網搜尋：

1. `GET https://buy.yungching.com.tw/list/{城市}-_c/{編號數字}_kw`
   （例 `…/list/高雄市-_c/0158419_kw`；編號 `YG0158419` 去掉英文前綴。舊筆記寫的 `?kw=` query 參數無效，**要用路徑形式 `_kw`**）
2. 頁面是 Angular SSR，**HTML 裡沒有 `<a href="/house/…">`**，唯一拿得到 id 的地方是 `<script type="application/ld+json">` 的 `ItemList`。
3. ⚠️ **`ItemList` 的第一個候選永遠是假 id `4308114`**（開它會拿到隨機推薦的別的物件，每次還不一樣）。實測 12 筆全都這樣，name 對得上但 url 位移了一格。
   **所以一定要驗證**：逐一 GET `/house/{id}`，用 `<title>` 開頭比對 `case_name`（比對前把空白全部去掉——有物件的案名含全形雙空格）。取第一個對得上的。
4. 查不到就退回 `official_url`（houseol），至少 KEIS 那筆建得起來，`ycResolveNote` 會記原因。

實測 12 筆物件（高雄/台南/台中都有）全部解析正確。驗證成本每次 1 + 最多 3 次 GET，線 A 一天只跑 6 次，可接受。

**交叉驗證**：建進 KEIS 後它自己會去抓那個連結，回填的 `url_price` 與 KEIS 物件總價一致（798 萬 = 798 萬），等於 KEIS 幫我們確認連結沒抓錯。

### 15.3 實作

**Notion 廣告 DB 新增兩個欄位**（已用 API 建好）：`KEIS廣告ID`(number)、`永慶官網連結`(url)。

**線 A**（`yc-v3-scan-publish.json`）在「Notion 標已發布」後、「LINE 發布通知」前插 4 個節點：

```
Notion 標已發布 → 解析永慶連結 → KEIS 新增廣告 → 取 KEIS 廣告ID → Notion 記 KEIS 廣告ID → LINE 發布通知
```

- `解析永慶連結`：Code 節點，用 `this.helpers.httpRequest` 做 §15.2 的搜尋+驗證，順便把 `地址` 去掉城市當 `adcase_road`
- `KEIS 新增廣告`：POST `/adcases`，`adcase_platforms='臉書'`、`adcase_urlfacebook=permalink`、`adcase_memo` 記編號
- 全部節點 `onError: continueRegularOutput` —— **KEIS 掛掉不能害粉專那篇白發**
- LINE 完成通知尾巴多一行「📊 KEIS 廣告追蹤：已同步 / 建立失敗（原因）」

**線 B**（`yc-v3-removal.json`）：`展開結果` 多讀 `KEIS廣告ID`，並在「PATCH 標記下架」後接：

```
PATCH 標記下架 → 備妥 KEIS 關閉 → 有 KEIS 廣告? ─┬─(是)→ KEIS 關閉廣告 → 彙總結果
                                                └─(否)────────────────→ 彙總結果
```

`KEIS 關閉廣告` = PUT `/adcases/{id}` body `{"is_expired": true}`。舊資料沒有 `KEIS廣告ID` 的會走「否」直接跳過。

⚠️ **KEIS 擋重複的 `adcase_url`**：同一個官網連結再 POST 一次會回 **HTTP 500**，訊息是 `創建案件失敗: 400: 您已經新增過此官網連結`（狀態碼給 500 但實際是 400）。`取 KEIS 廣告ID` 節點認得這個訊息，會回報「KEIS 上已有同連結的廣告，未重複建立」而不是當成錯誤。做線 C 重發輪替時要注意這點。

**2026-07-22 實測**：建→關→刪整輪跑過；已上線的第一篇真實廣告 YG0158419 已補建進 KEIS（`adcase_id` 325866，平台=臉書），Notion 三個欄位都回寫成功。

---

## 16. KEIS token 改成每次跑自己登入（2026-07-23，修一個會讓全系統靜默停擺的問題）

**問題**：原本 credential `KEIS API Token`（id `EaVn8LzS7lT5tW10`）存的是從瀏覽器 localStorage 抓的靜態 JWT。實際量過 **這個 JWT 只活 8 小時**（`expires_in: 28800`）。線 A 一天跑 6 次、線 B 每天 08:00，等於絕大多數的執行都會 401，而且因為節點設了 `neverError`，**失敗是靜悄悄的**——線 B 會全部判成「KEIS 暫時無法確認，本次略過」，看起來像一切正常。

**解法**：兩條線的第一個節點都改成先自己登入。

- 新 credential：**`KEIS 帳密（自動登入）`**（id `KPvi4Z4Z8IAhKbdz`，型別 **Custom Auth**），內容是
  `{"body": {"username": "…", "password": "…"}}`
  用 Custom Auth 是為了讓帳密留在 n8n 的 credential 裡，**不會寫進 workflow JSON 進 git**。
- 新節點 **`KEIS 登入`**：`POST https://keis.kshouse.com.tw/api/v1/auth/login?device_type=desktop`，header `Content-Type: application/x-www-form-urlencoded`，開 `fullResponse`。
- 所有 KEIS 節點（線 A 的撈列表/物件詳情/新增廣告，線 B 的查 is_active/關閉廣告）拿掉舊 credential，改成 header
  `Authorization: {{ 'Bearer ' + $('KEIS 登入').first().json.body.access_token }}`

舊的 `KEIS API Token` credential 已無人使用，留著沒有害處但不要再拿它當範例。

---

## 17. 線 B 下架判定：主要靠 KEIS 廣告追蹤自己的偵測（2026-07-23 定案）

**關鍵認知**：KEIS 廣告追蹤那個頁面**本來就是拿來盯廣告死活的**，它自己會去抓 `adcase_url`。不用我們另外寫偵測。

**KEIS 的偵測行為（實測）**：

| 觸發時機 | 實測 |
|---|---|
| 新增廣告時 | **15～20 秒內**就抓一次 |
| 之後 | 每天凌晨掃一輪（進行中 7 筆的 `url_update_time` 分佈在 00:20～05:28）|

抓完會寫回這些欄位：

- 連結死掉 → `url_invalid: true`，`status_tags: ['案件下架']`，`url_price: null`
- 連結還活著 → `url_invalid: false`，`url_price` 填上官網當下的價格（可拿來對帳）
- 另外還會標 `新上架`、`降價100萬` 這類 tag

⚠️ **KEIS 只標記，不會自動關閉**：`is_expired` 不會自己變 true（實測 60 秒內沒動，歷史資料上已結束那幾筆的 `closed_at` 是同一個時間戳＝人工批次關的）。所以線 B 還是要自己送 `PUT {"is_expired": true}`。

**線 B 的判定（兩套邏輯）**：

1. **有 `KEIS廣告ID` 的**（v3 自己發的）→ 開頭先 `GET /adcases?skip=0&limit=100` 撈全部（不帶 `is_expired` 就回全部，limit 上限 100），用 `adcase_id` 對照。`url_invalid === true` 或 `status_tags` 含「下架」或 `is_expired === true` → 判下架。**這是主路徑。**
2. **沒有 `KEIS廣告ID` 的**（v2 時期用 LINE 手動貼永慶網址建的舊資料，本來就不在 KEIS）→ 退回雙重確認：`property-management` 查無 **而且** 來源連結真的死了（`this.helpers.httpRequest` 打一次，HTTP ≥400 或頁面含 `已下架/物件不存在/已成交/查無此物件`）。

**為什麼舊資料一定要雙重確認**：只看 KEIS 的話，那 4 筆本來就不在 KEIS 的舊資料會全部被判下架——試跑時真的發生了，照跑會自動刪掉其中 2 篇**物件還在賣**的粉專貼文。反過來只看連結也不行：YG0158419 的來源連結是 houseol，**物件還在賣但那個 houseol 連結已經 404**。

**2026-07-23 實測**（全部只讀或用拋棄式資料，沒動到真資料）：

- 主路徑「連結失效」分支：建一筆用死連結的拋棄式廣告 → KEIS 秒標 `url_invalid=true` + `案件下架` → 線 B 真實節點判定「要下架 = true，理由：KEIS 廣告追蹤標記官網連結已失效（案件下架）」✅
- 主路徑「連結正常」分支：真實的 YG0158419（`adcase_id` 325866）→「KEIS 廣告追蹤顯示連結正常」✅
- 舊資料路徑：3 筆「KEIS 查無但來源連結仍正常 → 略過」、YC1835328「KEIS 查無 + 來源連結 404 → 判定下架」✅
- 關閉段：拋棄式廣告跑一次 → `is_expired` 變 true、移到已結束清單 ✅

---

## 18. 線 B 通知政策：只推故障，不推日常（2026-07-23 拍板）

**決策依據（使用者）**：社團的物件是從**粉專用「分享」發出去的**，粉專原文一刪，所有分享自動失效。所以下架成功時**沒有任何事需要使用者做** → 不需要通知。

**新政策：正常日子一則都不推。** 只有這兩種情況會推：

| 情況 | 訊息 | 使用者要做什麼 |
|---|---|---|
| 粉專貼文自動刪除失敗 | ⚠️ 列出案名/編號/**粉專連結**/錯誤原因 | 點連結進去手動刪 |
| KEIS 撈不到資料 | 🔧 今天的下架偵測沒跑成功 | 連兩天收到才要查 |

刪文失敗時 `markRemoved=false` → Notion 狀態維持「已發布」→ **明天 08:00 會自動再試**，訊息裡有寫。所以偶爾一則不用理它，連續幾天才是真的壞了。

**順便修掉重複推播**：舊版「彙總結果」有 **4 條線進來**（IF 已下架?[false]、可標下架?[false]、有 KEIS 廣告?[false]、KEIS 關閉廣告）。n8n 是**每條有資料的分支各跑一次**，所以只要當天同時有「下架的」和「沒下架的」，就會推 2～3 則一模一樣的摘要。

新版把「彙總結果」整個砍掉，改成兩條各自獨立的通知支線：

```
判定刪除結果 ─┬→ 可標下架? → PATCH → 備妥KEIS關閉 → 有KEIS廣告? → KEIS關閉廣告（結束，不通知）
              └→ 篩出刪文失敗 → 組刪文失敗通知 → LINE Push
KEIS 撈廣告清單 ─┬→ 查 Notion 已發布 →（主線）
                 └→ 篩出 KEIS 故障 → 組 KEIS 故障通知 → LINE Push
```

所有「沒事」的分支（IF 已下架?[false] 等）現在都是**斷頭的**，不接任何東西。

估計用量：從**每月 ~30 則**（每天固定一則摘要）降到 **~0～2 則**。

⚠️ **「戰果」是搶單專用關鍵字，不要拿來查廣告。** 廣告要加查詢指令的話另外取名。

---

## 19. 其他已知可優化項（尚未動工）

| 項目 | 現況 | 影響 |
|---|---|---|
| Notion 判重打 40 次 | 線 A 每輪把 40 個候選各查一次 Notion＝一天 240 次 | 改成「一次撈全部案件編號在記憶體比對」＝1 次。**等廣告範圍規範定案後一起改** |
| 掃描視窗只有最新 100 筆 | `page_size` 上限就是 100（201 會 422）。目前 100 筆涵蓋約 2.5 天、集團一天約 40 筆新案 | 現在安全。若集團案量暴增，新案可能在被掃到前就被擠出視窗 → 要改成翻 2～3 頁 |
| 一天發 6 篇到同一個粉專 | cron `0 9,11,13,15,17,19` 每輪 1 件 | 尚未評估是否過量 |

**已確認不用改**：線 A 撈的整個 KEIS（6623 筆）就是老闆那 40 間加盟店的案子。抽樣 39 筆（第 1/5/20/40/60 頁）店別全是永慶不動產／永義房屋／台慶不動產的高雄門市，沒有任何外部品牌混入。使用者的目標是撈買方名單，發集團內任一店的案子都可以。（使用者本人 store_id=4「永慶不動產博愛凱璿」。列表端點的 `store_name` 是空的，只有詳情端點有，真要過濾得在「白名單清洗」那關做。）

**第二階段**（線 D 之後）：線 C 重發輪替（防貼文沉底）。
