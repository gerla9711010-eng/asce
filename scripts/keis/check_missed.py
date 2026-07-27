"""稽核用：檢查「第一次出現時就符合條件」的一手名單，有沒有漏搶。

只抓真正的缺口：一手單、當初就符合條件、但沒標記搶到。
被別人搶走(CoolingDown)、過7天釋出的舊貨，都不算漏搶，本來就不看。

用法：直接跑 `python check_missed.py`，會印出漏掉的名單。
"""
import csv
import re

import grab  # 直接重用 grab.py 的篩選邏輯，之後改條件這邊自動跟著變

INVENTORY_CSV = grab.INVENTORY_CSV


def parse_budget(s: str):
    s = (s or "").strip()
    if s in ("", "-"):
        return 0, 0
    m = re.match(r"(\d+)-(\d+)萬", s)
    if m:
        return float(m.group(1)), float(m.group(2))
    m = re.match(r"(\d+)萬以上", s)
    if m:
        return float(m.group(1)), 0
    m = re.match(r"(\d+)萬", s)
    if m:
        return float(m.group(1)), float(m.group(1))
    return 0, 0


def main():
    with open(INVENTORY_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    missed = []
    for row in rows:
        if row.get("來源") != "新出現" or row.get("首次狀態") != "Available":
            continue  # 不是「我們親眼看到它剛進池、當時沒人碰」的一手單
        if row.get("我方動作") == "搶到":
            continue  # 已經搶到

        budget_start, budget_end = parse_budget(row.get("預算"))
        rec = {
            "status": "Available",  # 用首次看到當下的狀態重算，不被後來被搶走蓋掉
            "target_city": row.get("縣市"),
            "property_category": row.get("類型"),
            "phone_number": row.get("電話"),
            "budget_start": budget_start,
            "budget_end": budget_end,
            "start_time": row.get("建檔時間"),
        }
        if grab.skip_reason(rec) is None:
            missed.append(row)

    print(f"稽核 {len(rows)} 筆總帳，一手且符合條件、卻沒標記搶到的：{len(missed)} 筆")
    for r in missed:
        print(f"  單號{r['summary_id']}  首次看到={r['首次看到']}  "
              f"{r['縣市']}/{r['類型']}/{r['預算']}/{r['電話']}  "
              f"現況={r['最後狀態']}（我方動作={r['我方動作'] or '(空白)'}）")


if __name__ == "__main__":
    main()
