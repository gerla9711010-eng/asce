# KEIS 搶單 grab.py 工單：穩定性加固 + 品質控管篩選

> 狀態：**待審核，尚未套用**。看過說「執行」才會改 `scripts/keis/grab.py` 並同步到桌面。
> 目標檔案：`scripts/keis/grab.py`（已確認與桌面 `C:\Users\user\OneDrive\桌面\keis\grab.py` 完全相同）。
> 產出日：2026-07-22

---

## 這次要做什麼（總覽）

| # | 類別 | 改什麼 | 為什麼 |
|---|---|---|---|
| B1 | 篩選/記錄 | 需求區域有行政區就記錄，新增 Notion 欄位「行政區」 | 業務要知道客戶想買哪一區 |
| B2 | 篩選 | 只留號碼是**手機**的，市話一律不搶 | 品質控管：市話多為公司/固網、聯絡效率差 |
| B3 | 篩選 | 類型是**公寓**不搶（空白 / `-` 照收） | 品質控管：不做公寓 |
| B4 | 篩選 | 預算**有填且上限 < 1000萬**不搶（空白照收） | 品質控管：只接 1000 萬以上等級的買方 |
| A1 | 穩定性 | 查詢改「主帳號失敗自動換下一個帳號」 | 今早 08:00 主帳號一逾時＝三帳號全盲，錯過開盤 |
| A2 | 穩定性 | 早上開盤時段(06:00–08:10)重試間隔縮到 1–3 秒 | 開盤名單幾秒被秒殺，5–8 秒才重試太慢 |
| A3 | 穩定性 | 碰到 HTTP 400 先自動重登一次再試 | 今早 10:03 的 400；補一層網子（純加固） |
| A4 | 穩定性 | 高頻觀測檔搬離 OneDrive 同步路徑 | page1_track 一直被 OneDrive 弄成損毀檔、洗版 log |

> B4 預算判斷已拍板：**看上限**。區間 700–1000 萬 → 上限 1000，不算低於門檻 → **保留**；單一值 750 萬 → **丟**；0–360 萬 → 丟；5500 萬以上 → 留；空白 → 留。

---

## 篩選邏輯總表（改完後 `matches()` 的完整判斷）

一筆名單要「搶」必須**同時**滿足：

1. `status == Available`（可搶，既有）
2. 縣市 ∈ `["高雄市"]`（既有）
3. **號碼是手機**（`09` 或掉 0 的 `9` 開頭）；市話 / 空號 → 丟
4. **類型 ≠ 公寓**；空白 / `-` → 收
5. **預算上限 ≥ 1000 萬，或預算空白**；有填且上限 < 1000 → 丟

> 行政區（B1）是**只記錄、不篩選**——它不決定搶不搶，只是搶到後多存一欄。

---

## Part B —— 品質控管篩選 + 行政區

### B0. 匯入與設定區

檔頭 `import` 加 `re`：

```python
import re
```

設定區（第 51–58 行 CONFIG 那塊）加入品質控管開關：

```python
# ====== 品質控管篩選（2026-07-22 加）======
ONLY_MOBILE = True            # True=只搶號碼是手機的，市話/空號一律不搶
EXCLUDE_TYPES = ["公寓"]      # 這些類型不搶；類型空白 / "-" 不受影響照收
MIN_BUDGET_CEILING = 1000     # 預算「上限」低於這個(萬)不搶；預算空白不受影響照收
```

### B1. 行政區小工具（新增函式，放在 `fmt_budget` 附近）

```python
def fmt_district(rec: dict) -> str:
    """需求區域(target_areas 是 list)組成字串，多區用「、」串。沒有就空字串。"""
    return "、".join(a for a in (rec.get("target_areas") or []) if a)
```

### B2. 手機判斷小工具（新增函式，放在 `norm_phone` 附近）

```python
def is_mobile(phone: str) -> bool:
    """判斷(通常被遮罩的)號碼是不是手機。query() 回來的號碼被遮成前 3 碼可見，
    例 '095*******'、市話 '716*******'/'055*******'——只看開頭就分得出來。
    台灣手機 = 09 開頭；有些後台把開頭的 0 吃掉存成 9 開頭，也算手機。
    其餘(市話區碼 02~08、存成 7…/3…、空號、開頭 00…)一律不是手機。"""
    d = re.sub(r"\D", "", phone or "")        # 只留數字（去掉遮罩星號/空白/橫線）
    if not d:
        return False
    return d.startswith("09") or d.startswith("9")
```

### B3+B4. 改寫 `matches()`（第 271–284 行）

```python
def matches(rec: dict) -> bool:
    if rec.get("status") != "Available":
        return False
    if CITIES and rec.get("target_city") not in CITIES:
        return False

    # ---- 品質控管篩選（2026-07-22 加）----
    # B2 只要手機：市話 / 空號不搶
    if ONLY_MOBILE and not is_mobile(rec.get("phone_number")):
        return False
    # B3 類型公寓不搶；空白 / "-" 放行
    cat = rec.get("property_category")
    if cat and cat != "-" and cat in EXCLUDE_TYPES:
        return False
    # B4 預算「上限」低於門檻不搶；空白(0)放行。上限 = budget_end 優先，沒有才用 budget_start
    ceiling = rec.get("budget_end") or rec.get("budget_start") or 0
    if ceiling and ceiling < MIN_BUDGET_CEILING:
        return False
    # ---- 品質控管篩選 end ----

    # 舊的 MIN_BUDGET / MAX_BUDGET 仍保留（預設 None 不作用，之後想細調再用）
    budget = rec.get("budget_start") or 0
    if budget > 0:
        if MIN_BUDGET is not None and budget < MIN_BUDGET:
            return False
        if MAX_BUDGET is not None and budget > MAX_BUDGET:
            return False
    return True
```

### B1（續）. 把行政區存進紀錄的每個環節

**`grab_record()`（第 326–343 行）** 在回傳 dict 加一欄：

```python
        return {
            ...
            "start_time": r["start_time"][:16],
            "district": fmt_district(r),          # ← 新增
            "remarks": (r.get("remarks") or "").strip(),
        }
```

**`record_from_application()`（第 768–785 行，補漏回查用）** 同樣加：

```python
        "start_time": str(app.get("start_time", ""))[:16],
        "district": fmt_district(app),            # ← 新增
        "remarks": (app.get("remarks") or "").strip(),
```

**`append_csv()`（第 346–359 行）** 表頭與每列**尾端**加「行政區」（放最後，才不會弄亂既有 9 欄格式的舊資料）：

```python
            if new:
                w.writerow(["搶到時間", "帳號", "summary_id", "姓名", "電話",
                            "縣市", "類型", "預算", "建檔時間", "行政區"])   # ← 尾端加
            for g in grabbed:
                w.writerow([g["grabbed_at"], g.get("account", ""), g["summary_id"],
                            g["name"], g["phone"], g["city"], g["category"],
                            g["budget"], g["start_time"], g.get("district", "")])  # ← 尾端加
```

**`load_grabbed_row()`（第 635–651 行，Notion 補寫回查用）** 讀回新欄（舊資料沒有就空字串）：

```python
                if str(row[2]).strip() == str(sid):
                    return {"grabbed_at": row[0], "account": row[1], "summary_id": row[2],
                             "name": row[3], "phone": row[4], "city": row[5],
                             "category": row[6], "budget": row[7], "start_time": row[8],
                             "district": row[9] if len(row) >= 10 else "",   # ← 新增
                             "remarks": ""}
```

**`push_notion()`（第 682–724 行）** props 加行政區（用 rich_text，避免 select 要先建選項）：

```python
    if g.get("district"):
        props["行政區"] = {"rich_text": [{"text": {"content": g["district"]}}]}
```

**`desc()`（第 311–314 行，dry-run 預覽字串）** 順手把行政區也印出來（本來就有 join target_areas，維持即可，不強制改）。

### B1（續）. Notion 資料庫要手動加欄位

搶單名單 DB（`4f28b91531594c618725afc3ecc36e2f`）新增一欄：

- 欄位名：**行政區**
- 型別：**文字（rich_text）**

> 沒加也不會壞——`push_notion` 寫一個不存在的屬性 Notion 會回 400，程式已有 try/except 只記 log、不影響搶單。但那樣行政區就寫不進去，所以請先在 Notion 加好。

---

## Part A —— 穩定性加固

### A1. 查詢自動換帳號（避免主帳號一掛全盲）

新增函式（放在 `pick_candidates` 附近）：

```python
def query_any(clients: list) -> dict:
    """依序用各帳號查詢，第一個成功的就用。避免主帳號一次逾時/抽風就整輪全盲、
    錯過開盤那幾秒。IP 被擋是全帳號共通(同一台同一 IP)→ 直接往上拋。"""
    last_exc = None
    for cl in clients:
        try:
            return cl.query()
        except IPBlocked:
            raise
        except Exception as e:
            last_exc = e
            continue
    raise last_exc if last_exc else RuntimeError("query_any: 沒有可用帳號")
```

主迴圈第 992 行改用它：

```python
            body = query_any(clients)      # 原本: body = clients[0].query()
```

### A2. 開盤時段重試更快

設定區加：

```python
OPEN_RUSH = ("06:00", "08:10")   # 早上開盤搶最兇的窗口，重試間隔縮到最短
OPEN_RUSH_RETRY_MIN = 1          # 這窗口內暫時性錯誤最短 1 秒就重試（平常是 3 秒）
```

主迴圈 `except Exception` 的「一般暫時性錯誤」分支（第 1078–1079 行 `else:` 那段）改成：

```python
            else:
                lo = OPEN_RUSH_RETRY_MIN if in_window(datetime.now(), OPEN_RUSH) else ERROR_RETRY_MIN
                retry = random.uniform(lo, ERROR_RETRY_MAX)
```

並新增一個泛用的時段判斷小工具（`in_expected_offline` 其實是特例，抽一個通用的）：

```python
def in_window(now: "datetime", window: tuple) -> bool:
    """now 是否落在 (start,end) 這個 HH:MM 區間（支援跨午夜）。"""
    minutes = now.hour * 60 + now.minute
    start, end = (_hhmm_to_min(x) for x in window)
    if start <= end:
        return start <= minutes < end
    return minutes >= start or minutes < end
```

> 註：這只縮短「一般暫時性錯誤」的重試間隔，不動「連續失敗 ≥10 次判定斷網」的低頻邏輯（斷網還是該退避，不該在開盤時段瘋狂重試）。

### A3. HTTP 400 先重登再試一次

`Keis._get()`（第 229–237 行）把 400 併進 401 的重登重試：

```python
    def _get(self, path: str):
        r = self.c.get(f"{API}{path}", headers=self._auth())
        if r.status_code in (400, 401):    # 401=token失效；400=偶發抽風/token邊界 → 重登再試一次
            self._login()
            r = self.c.get(f"{API}{path}", headers=self._auth())
        if r.status_code == 403:
            raise IPBlocked()
        r.raise_for_status()
        return r.json()
```

> 若重登後仍 400 → `raise_for_status()` 拋出 → 外層當暫時性錯誤重試（＝今天的行為，會自癒）。連續失敗超過 10 次且非深夜斷網時段，外層本來就會推 LINE 告警——所以「KEIS 真的改壞了」不會無聲無息。純加固、正常時完全不觸發。

### A4. 高頻觀測檔搬離 OneDrive

OneDrive Files On-Demand 會把**頻繁改寫**的小檔弄成損毀 reparse point（page1_track 已中招兩次）。把「每輪都寫」的觀測檔改存到 `%LOCALAPPDATA%`（機器本機、OneDrive 不同步）：

```python
# 高頻觀測檔搬離 OneDrive 同步路徑（2026-07-22）：page1_track / appearances / appear_state
# 每輪或每次新單都在寫，放 OneDrive 會被 Files On-Demand 弄成損毀檔。改放本機 LOCALAPPDATA。
_LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path(__file__).parent) / "keis-grab"
try:
    _LOCAL.mkdir(parents=True, exist_ok=True)
except Exception:
    _LOCAL = Path(__file__).parent      # 萬一建不了就退回原路徑，至少能跑

APPEAR_CSV   = _LOCAL / "appearances.csv"      # 原本: Path(__file__).parent / "appearances.csv"
APPEAR_STATE = _LOCAL / "appear_state.txt"     # 原本: Path(__file__).parent / "appear_state.txt"
TOPID_CSV    = _LOCAL / "page1_track3.csv"      # 原本: page1_track2.csv（換新檔名，避開損毀舊檔）
```

**維持在 OneDrive 資料夾不動**（低頻寫、要備份/要看得到）：`grabbed.csv`、`daily_summary.csv`、`notion_pending.txt`、`logs/`。

> 影響：`appearances.csv` 之後會在 `%LOCALAPPDATA%\keis-grab\`（約 `C:\Users\user\AppData\Local\keis-grab\`）而不是桌面 keis 資料夾。要看「名單幾點出現」的分析資料改看那裡（我這邊也讀得到）。舊的損毀 `page1_track.csv` / `page1_track2.csv` 留在原地當廢棄物，不用理它。

---

## 套用步驟（審核通過、你說「執行」後才做）

1. 改 repo `scripts/keis/grab.py`（上面所有 A + B）
2. `python -c "import ast; ast.parse(open('scripts/keis/grab.py',encoding='utf-8').read())"` 做語法檢查
3. dry-run 驗篩選：`python scripts/keis/grab.py`，確認列出的候選都符合新規則（手機、非公寓、預算 OK）
4. 開 feature branch → PR → 合 main（依 CLAUDE.md 分支策略）
5. 複製同一份到桌面 `C:\Users\user\OneDrive\桌面\keis\grab.py`（雙邊同步）
6. Notion 加「行政區」文字欄位
7. 雙擊桌面 `run.bat` 重開 watch，看 log 出現 `👁 watch 啟動`

## 驗收重點

- dry-run 不再列出市話、公寓、預算 <1000 萬（有填的）的名單
- 搶到後 `grabbed.csv` 最後一欄有行政區、Notion 頁面有行政區
- `%LOCALAPPDATA%\keis-grab\` 出現 `page1_track3.csv` 且持續長大、不再噴寫入失敗
- 隔天早上 08:00 log 若又逾時，應看到自動換帳號續掃、不再整輪空白
