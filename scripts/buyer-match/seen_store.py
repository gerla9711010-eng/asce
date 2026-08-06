"""記住「這位客戶的這個客需，上次已經回報過哪些案子」，重跑只給新的＋改價的。

用途：每天 08:10 那班（`daily_run.py --only-new`，排程預設就是這個）跑完的檔案只留
「上次沒出現過」跟「總價變了」的物件，不然每天 80 幾筆有一大半是昨天看過的同一批。
GUI 手動查維持全寫（想看完整清單就開 GUI 跑）。

設計決定（2026-07-30 跟使用者確認）：
1. **指紋不含總價**：`社區或地址|樓層|坪數`（見 `buyer_match.Card.unit_key()`）。
   總價另外存，變了就當「🔻降價」重新報一次——降價是可以打電話的理由，
   不該被當成重複吃掉。
2. **按「客戶／客需」分開記**，不是全域一份。同一戶對不同客戶都是新資訊，
   全域去重會害別的客戶漏看。
3. **保留 30 天沒再出現的就刪**，不是「這次沒出現就刪」。房地/i智慧掛掉那天會撈到
   0 筆，用「這次沒出現」的邏輯會把記憶整個清光，隔天全部重報一次。
4. **⚠️ 同一戶多店委託、各店開價不一樣**（2026-07-30 使用者提出，第一版真的會錯）：
   `buyer_match.dedup_by_fingerprint` 只合併「連開價都一樣」的重複委託，所以同一戶
   店A掛 1580、店B掛 1520 時，兩筆都會活著進到這裡。一戶只存一個價的話，第二筆就會
   被誤判成「降價 60 萬」，而且明天兩筆順序一換就變「調漲 60 萬」——天天來回跳。
   改成：
   - 先**照 unit_key 把同一戶的多筆委託併成一組**（完全不看開價），一戶就是一組
   - 比較基準用**這一戶的最低開價**（買方在意的就是最低那個，而且跟哪一筆先被撈到無關，
     不會因為順序改變就跳來跳去）
   - 記憶同時存 `prices`（這一戶各店的開價），新增一家店掛更高價不會觸發任何回報
   - **只有最低開價變低才報降價**；變高（多半是那個便宜的委託下架了）只更新記憶、
     不吵你，數字會列在總表的「漲價 N 筆略過」
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
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


@dataclass
class UnitGroup:
    """同一戶（可能被好幾家店委託）的一組委託。代表筆＝開價最低的那筆。"""

    key: str
    entry: tuple                      # 代表：(Card, Agent|None, share_url|None)
    others: list = field(default_factory=list)   # 同一戶其他店的委託
    prices: list = field(default_factory=list)   # 各店開價（含代表筆），已排序

    @property
    def min_price(self) -> Optional[int]:
        real = [p for p in self.prices if p is not None]
        return min(real) if real else None

    def note(self) -> str:
        """同一戶有多家店委託而且開價不同時，附一行說明——不然客戶問「別家怎麼比較便宜」
        會答不出來。開價都一樣的重複委託由 dedup_by_fingerprint 處理，不會走到這裡。"""
        real = sorted({p for p in self.prices if p is not None})
        if len(self.others) == 0 or len(real) < 2:
            return ""
        rest = "／".join(f"{p}" for p in real[1:])
        return f"（同一戶另有 {len(self.others)} 筆委託，開價 {rest} 萬）"


def group_by_unit(entries: list) -> list[UnitGroup]:
    """把同一戶的多筆委託併成一組，**完全不看開價**。

    這是跟 `buyer_match.dedup_by_fingerprint` 的差別：那支的指紋含開價，所以同一戶
    各店開價不同時會留成多筆；跨天比價必須先併成一戶，否則同一戶的兩個價格會互相
    被當成「改價」（見模組開頭第 4 點）。"""
    order: list[str] = []
    buckets: dict[str, list] = {}
    for entry in entries:
        key = entry[0].unit_key()
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(entry)

    groups: list[UnitGroup] = []
    for key in order:
        items = buckets[key]
        # 代表筆＝開價最低的（抓不到開價的排最後），跟被撈到的順序無關
        items.sort(key=lambda e: (e[0].price_wan is None, e[0].price_wan or 0))
        groups.append(
            UnitGroup(
                key=key,
                entry=items[0],
                others=items[1:],
                prices=[e[0].price_wan for e in items],
            )
        )
    return groups


def classify(
    data: dict,
    scope: str,
    entries: list,
    today: Optional[str] = None,
) -> tuple[list[UnitGroup], list[tuple[UnitGroup, Optional[int]]], int, int]:
    """把這次撈到的 entries 按「戶」分堆，同時更新記憶。

    回傳 `(新出現的戶, [(降價的戶, 上次最低開價), ...], 跟上次一樣略過的戶數, 漲價略過的戶數)`。
    entries 是 `[(Card, Agent|None, share_url|None), ...]`（buyer_match.match_areas 的輸出）。
    """
    today_str = today or datetime.now().strftime("%Y-%m-%d")
    units = data.setdefault(scope, {})
    fresh: list[UnitGroup] = []
    dropped: list[tuple[UnitGroup, Optional[int]]] = []
    skipped = 0
    raised = 0

    for group in group_by_unit(entries):
        rec = units.get(group.key) or None
        now_min = group.min_price

        if rec is None:
            fresh.append(group)
        else:
            before_min = rec.get("price")
            if before_min is not None and now_min is not None and now_min < before_min:
                dropped.append((group, before_min))
            elif before_min is not None and now_min is not None and now_min > before_min:
                # 多半是那個便宜的委託下架了，不是屋主漲價 → 只更新記憶，不吵人
                raised += 1
            else:
                skipped += 1

        units[group.key] = {
            "price": now_min,   # 比較基準：這一戶的最低開價
            "prices": sorted({p for p in group.prices if p is not None}),
            "first_seen": (rec or {}).get("first_seen", today_str),
            "last_seen": today_str,
        }
    return fresh, dropped, skipped, raised


def price_change_note(old_price: Optional[int], new_price: Optional[int]) -> str:
    """給降價的物件加一行抬頭，貼給客戶時一眼看得出來為什麼又出現。"""
    if old_price is None or new_price is None:
        return "🔁 價格有變（其中一邊抓不到總價）"
    if new_price < old_price:
        return f"🔻 降價 {old_price - new_price} 萬（{old_price} → {new_price} 萬）"
    if new_price > old_price:
        return f"🔺 調漲 {new_price - old_price} 萬（{old_price} → {new_price} 萬）"
    return ""


def _as_date(value) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
