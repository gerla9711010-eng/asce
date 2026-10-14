#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""591 廣告版位對照檔：哪個 591 物件編號現在掛哪個案件、哪天到期。

為什麼要有（2026-10-14 使用者要求）：物件下架時要知道那則 591 廣告還剩幾天——
剩 30 天以上可以「換物件」沿用版位，不到 30 天直接關。到期日記在本機，自己倒數，不用天天去 591 看。
看門狗（scripts/keis/ad_watchdog.py 判斷六）每天讀這份檔，配 KEIS「案件下架」標籤推 Telegram。

以 591 物件編號為主鍵：續刊、換物件（A→B）編號都不變，續刊改到期日、換物件改 case/adcase。
檔案放桌面 keis 資料夾（跟看門狗、.env 同一處）：ad591_ledger.json

用法：
  python ledger591.py list
  python ledger591.py add S21079359 --case AA1072556 --adcase 441035 --expires 2026-12-13 --title 美術館…
  python ledger591.py add S21079359 --left 60          # 用會員中心的「剩餘 N 天」換算到期日
  python ledger591.py renew S20935627 --expires 2027-01-17   # 續刊
  python ledger591.py swap S20935627 --case AG1234567 --adcase 441100 --title …   # 換物件
  python ledger591.py remove S20873427                 # 591 上已關閉
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

LEDGER = Path(os.environ.get("AD591_LEDGER") or
              Path(os.path.expanduser("~")) / "OneDrive" / "桌面" / "keis" / "ad591_ledger.json")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load():
    if LEDGER.exists():
        return json.loads(LEDGER.read_text(encoding="utf-8"))
    return {}


def save(d):
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(LEDGER)


def left(expires, today=None):
    return (datetime.strptime(expires, "%Y-%m-%d").date() - (today or date.today())).days


def norm_sid(s):
    s = s.strip().upper()
    if s.isdigit():
        sys.exit("物件編號要帶字首：出售 S、出租 R（例：S21079359）")
    return s


def main():
    ap = argparse.ArgumentParser(description="591 廣告版位對照檔")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("add", "renew", "swap"):
        p = sub.add_parser(name)
        p.add_argument("sid")
        p.add_argument("--case")
        p.add_argument("--adcase", type=int)
        p.add_argument("--title")
        p.add_argument("--expires", help="YYYY-MM-DD（廣告頁「有效期」）")
        p.add_argument("--left", type=int, help="會員中心「剩餘 N 天」，換算成到期日")
    p = sub.add_parser("remove")
    p.add_argument("sid")
    a = ap.parse_args()
    d = load()

    if a.cmd == "list":
        for sid, e in sorted(d.items(), key=lambda kv: kv[1]["expires"]):
            print("%-10s 剩 %3d 天（%s）%-10s KEIS %-7s %s"
                  % (sid, left(e["expires"]), e["expires"], e.get("case") or "-",
                     e.get("adcase") or "-", e.get("title") or ""))
        print("（%s，共 %d 筆）" % (LEDGER, len(d)))
        return

    sid = norm_sid(a.sid)
    if a.cmd == "remove":
        print("移除：%s %s" % (sid, d.pop(sid, "（本來就沒有）")))
        save(d)
        return

    exp = a.expires or (str(date.today() + timedelta(days=a.left)) if a.left is not None else None)
    e = d.get(sid, {})
    if a.cmd in ("renew", "swap") and not e:
        sys.exit("%s 不在對照檔裡，先 add" % sid)
    if a.cmd == "renew" and not exp:
        sys.exit("續刊要帶 --expires 或 --left")
    if a.cmd == "swap":
        if not a.case:
            sys.exit("換物件要帶 --case（新案件編號）")
        e["prev"] = (e.get("prev") or []) + [e.get("case")]   # 留換過的紀錄
    if a.cmd == "add" and not (exp or e.get("expires")):
        sys.exit("新增要帶 --expires 或 --left")
    for k, v in (("case", a.case), ("adcase", a.adcase), ("title", a.title), ("expires", exp)):
        if v is not None:
            e[k] = v
    e["updated"] = str(date.today())
    d[sid] = e
    save(d)
    print("%s：%s → 剩 %d 天" % (a.cmd, sid, left(e["expires"])), json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
