"""記住「這位客戶的這個子條件，上次已經看過哪些永慶連結」，重跑時能標出新出現的案子。

跟舊版（i智慧 時代的 seen_store.py，08-14 隨 i智慧 一起刪除）比，資料簡單很多：
舊資料源有結構化的價格/坪數/樓層可以比對「降價」，這支新資料源只有 title/subtitle
（截斷的字串，不能拿來算價格）跟 `yc_link`——但 `yc_link` 本身就是天生唯一的房源
URL，直接拿來當指紋剛好，不用像舊版那樣猜 unit_key、處理同戶多店開價。

只做「這個連結對這個客戶/子條件是不是第一次看到」，不追蹤降價/漲價——沒有結構化
價格資料做不了那個，需要再另外討論。
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

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
        # 檔壞了不能讓整批停擺——當成沒記憶重新開始（最壞情況是這次全部當新案標一次）
        print(f"[WARN] seen.json 讀不起來（{type(e).__name__}），這次當作沒記憶", file=sys.stderr)
        return {}


def save(data: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(STATE_PATH)  # 換名是原子操作，寫一半被中斷不會留下壞檔
    except OSError as e:
        print(f"[WARN] seen.json 寫不進去（{type(e).__name__}）：{e}", file=sys.stderr)


def prune(data: dict, today: date | None = None, retain_days: int = RETAIN_DAYS) -> int:
    """清掉 retain_days 天沒再出現的連結（案子早就下架，或客需已經不查這個範圍了），
    回傳清掉幾筆。"""
    cutoff = (today or date.today()) - timedelta(days=retain_days)
    removed = 0
    for scope in list(data.keys()):
        links = data.get(scope) or {}
        for link in list(links.keys()):
            try:
                last = date.fromisoformat((links[link] or {}).get("last_seen", ""))
            except ValueError:
                last = None
            if last is None or last < cutoff:
                del links[link]
                removed += 1
        if not links:
            del data[scope]
    return removed


def mark_seen(
    data: dict, customer: str, need: str, yc_links: list[str], today: date | None = None
) -> set[str]:
    """回報這輪這個客需看到的所有連結，更新記憶，回傳其中「第一次出現」的那些連結。"""
    scope = scope_key(customer, need)
    today_str = (today or date.today()).isoformat()
    links = data.setdefault(scope, {})
    new_links: set[str] = set()
    for link in yc_links:
        if link not in links:
            new_links.add(link)
            links[link] = {"first_seen": today_str, "last_seen": today_str}
        else:
            links[link]["last_seen"] = today_str
    return new_links
