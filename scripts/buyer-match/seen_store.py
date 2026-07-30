"""記住「這位客戶的這個客需，上次已經回報過哪些案子」，重跑只給新的＋改價的。

用途：每天 08:10 那班（`daily_run.py --only-new`，排程預設就是這個）跑完的檔案只留
「上次沒出現過」跟「總價變了」的物件，不然每天 80 幾筆有一大半是昨天看過的同一批。
GUI 手動查維持全寫（想看完整清單就開 GUI 跑）。

設計決定（2026-07-30 跟使用者確認）：
1. **指紋不含總價**：`社區或地址|樓層|坪數`（見 `buyer_match.Card.unit_key()`）。
   總價另外存，變了就當「🔻降價／🔺調價」重新報一次——降價是可以打電話的理由，
   不該被當成重複吃掉。
2. **按「客戶／客需」分開記**，不是全域一份。同一戶對不同客戶都是新資訊，
   全域去重會害別的客戶漏看。
3. **保留 30 天沒再出現的就刪**，不是「這次沒出現就刪」。房地/i智慧掛掉那天會撈到
   0 筆，用「這次沒出現」的邏輯會把記憶整個清光，隔天全部重報一次。
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "state" / "seen.json"
RETAIN_DAYS = 30


def scope_key(customer: str, need: str) -> str:
    return f"{customer}／{need}"


def load() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        # 檔壞了不能讓整批停擺——當成沒記憶重新開始（最壞情況是今天全部當新案報一次）
        print(f"[WARN] seen.json 讀不起來（{type(e).__name__}），這次當作沒記憶", file=sys.stderr)
        return {}


def save(data: dict) -> bool:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(STATE_PATH)  # 換名是原子操作，寫一半被中斷不會留下壞檔
        return True
    except OSError as e:
        print(f"[WARN] seen.json 寫不進去（{type(e).__name__}）：{e}", file=sys.stderr)
        return False


def prune(data: dict, today: Optional[str] = None, retain_days: int = RETAIN_DAYS) -> int:
    """清掉 retain_days 天沒再出現的紀錄（案子早就下架了），回傳清掉幾筆。"""
    cutoff = (_as_date(today) or date.today()) - timedelta(days=retain_days)
    removed = 0
    for scope in list(data.keys()):
        units = data.get(scope) or {}
        for key in list(units.keys()):
            last = _as_date((units[key] or {}).get("last_seen"))
            if last is None or last < cutoff:
                del units[key]
                removed += 1
        if not units:
            del data[scope]
    return removed


def classify(
    data: dict,
    scope: str,
    entries: list,
    today: Optional[str] = None,
) -> tuple[list, list, int]:
    """把這次撈到的 entries 分成三堆，同時更新記憶。

    回傳 `(新出現的, [(entry, 舊總價), ...], 跟上次一樣被略過的筆數)`。
    entries 是 `[(Card, Agent|None, share_url|None), ...]`（buyer_match.match_areas 的輸出）。
    """
    today_str = today or datetime.now().strftime("%Y-%m-%d")
    units = data.setdefault(scope, {})
    fresh: list = []
    repriced: list = []
    skipped = 0

    for entry in entries:
        card = entry[0]
        key = card.unit_key()
        rec = units.get(key) or None
        price = card.price_wan

        if rec is None:
            fresh.append(entry)
        elif rec.get("price") != price:
            repriced.append((entry, rec.get("price")))
        else:
            skipped += 1

        units[key] = {
            "price": price,
            "first_seen": (rec or {}).get("first_seen", today_str),
            "last_seen": today_str,
        }
    return fresh, repriced, skipped


def price_change_note(old_price: Optional[int], new_price: Optional[int]) -> str:
    """給改價的物件加一行抬頭，貼給客戶時一眼看得出來為什麼又出現。"""
    if old_price is None or new_price is None:
        return "🔁 價格有變（其中一邊抓不到總價）"
    if new_price < old_price:
        diff = old_price - new_price
        return f"🔻 降價 {diff} 萬（{old_price} → {new_price} 萬）"
    if new_price > old_price:
        diff = new_price - old_price
        return f"🔺 調漲 {diff} 萬（{old_price} → {new_price} 萬）"
    return ""


def _as_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
