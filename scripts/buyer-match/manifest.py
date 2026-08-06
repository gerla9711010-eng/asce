"""記錄「哪個群組／客戶／客需 最新的結果存在哪個檔案」，給網頁看板用。

output/ 裡的檔名（例：`20260801_195049_采儒_文化中心周圍.txt`）不夠拿來重建
群組／客戶／客需——客需名稱本身可能含逗號/斜線，存檔時已經被替換成底線
（見 run_group_match.py / run_customer_match.py 的 label 組法），從檔名反推
會把「原本就有底線」跟「被替換掉的逗號/斜線」搞混，而且**群組完全沒進檔名**。

所以改成寫入端（跑完一筆就記一筆）主動維護這份索引，讀取端（網頁看板）
只管讀，不用猜檔名。

⚠️ **`full` 跟 `latest` 分開記**：每天 08:10 排程是 `--only-new` 模式，存檔內容只有
「今天新出現的／降價的」，不是完整候選清單——用這個當看板預設顯示的話，大部分時間
會看起來空空的（其實只是沒有新案，不代表沒有候選物件）。GUI／CLI 手動查（不加
`--only-new`）才是完整清單。看板要看的是完整清單，所以：
- `full`：只有 only_new=False（完整清單）的那次才更新，網頁看板主要顯示這個
- `latest`：不管哪種模式，永遠是最新一次，`full` 還沒有值時網頁看板退而求其次顯示這個
  （沒手動查過的客戶還是看得到東西，只是可能是稀疏的「今天新案」而不是完整清單）
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = BASE_DIR / "output" / "manifest.json"

UNASSIGNED_GROUP = "未分類"


def load() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        print(f"[WARN] manifest.json 讀不起來（{type(e).__name__}），當作空的", file=sys.stderr)
        return {}


def save(data: dict) -> None:
    try:
        MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = MANIFEST_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(MANIFEST_PATH)
    except OSError as e:
        # 記錄失敗不該讓查詢本身算失敗——查詢結果已經存檔了，只是看板晚點才看得到。
        print(f"[WARN] manifest.json 寫不進去（{type(e).__name__}），這筆不會出現在網頁看板", file=sys.stderr)


def prune_group(group: str, valid_keys: set[str]) -> list[str]:
    """拿掉這個群組裡，房地現在已經沒有的客戶／客需（使用者把客戶移出房地資料夾後，
    manifest 跟看板不會自己清掉舊紀錄——之前一直是「只累加、不刪除」，導致移除的客戶
    在網址上還陰魂不散。跟房地當下名單（valid_keys）比對，多出來的連 output 檔一起砍。"""
    data = load()
    bucket = data.get(group)
    if not bucket:
        return []
    removed = []
    for key in list(bucket.keys()):
        if key not in valid_keys:
            entry = bucket.pop(key)
            removed.append(key)
            for record in (entry.get("full"), entry.get("latest")):
                if record:
                    path = MANIFEST_PATH.parent / record["file"]
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        pass
    if removed:
        save(data)
    return removed


def record_result(
    group: Optional[str],
    customer: str,
    need: str,
    file_path: Path,
    hits: int,
    only_new: bool = False,
) -> None:
    """跑完一個「客戶／客需」存檔後呼叫一次。"""
    g = group or UNASSIGNED_GROUP
    data = load()
    bucket = data.setdefault(g, {})
    key = f"{customer}／{need}"
    entry = bucket.setdefault(
        key, {"customer": customer, "need": need, "full": None, "latest": None}
    )
    record = {
        "file": file_path.name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "hits": hits,
        "only_new": only_new,
    }
    entry["latest"] = record
    if not only_new:
        entry["full"] = record
    save(data)
