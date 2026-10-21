#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""591 廣告版位對照檔：哪個 591 物件編號現在掛哪個案件、哪天到期。

為什麼要有（2026-10-14 使用者要求）：物件下架時要知道那則 591 廣告還剩幾天——
改址次數還有（一期 2 次）就能「換物件」沿用版位，用完只能關；換不換使用者看剩幾天決定。到期日記在本機，自己倒數，不用天天去 591 看。
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
  python ledger591.py add S20698894 --edits 1          # 手動校正已用掉的改址次數
  python ledger591.py add S21079307 --agent 劉宸伶 --phone 0913710277 --store 博愛凱璿店   # 該聯絡誰

聯絡人（2026-10-21 起）：使用者要「每個廣告位都知道該聯絡誰」。KEIS 只有承辦人姓名，電話在 houseol 來源頁，
用 houseol_contact.js 一次查好寫進來。換物件（swap）時舊聯絡人會跟著換掉，記得一起帶新的。

改址次數（2026-10-21 起）：591 規定「現況、出售地址、出售樓層、總樓層」一個刊期只能改 2 次，
換物件一定會扣 1 次。591 頁面上查不到剩幾次（只在送出時的確認框說「將扣除1次」），所以自己記：
swap 自動 +1，用完了 swap 會擋。使用者自己在 591 改過地址/樓層要用 --edits 校正。
續刊後次數會不會重算沒驗證過，renew 不動次數，下次在確認框看到再校正。
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

EDIT_LIMIT = 2   # 591：一個刊期內地址/樓層/總樓層/現況可改 2 次

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
        p.add_argument("--edits", type=int, help="已用掉的改址次數（手動校正用）")
        p.add_argument("--agent", help="承辦人（物件的聯絡人，不是 KEIS 廣告專員）")
        p.add_argument("--phone", help="承辦人手機")
        p.add_argument("--store", help="承辦人分店")
    p = sub.add_parser("remove")
    p.add_argument("sid")
    a = ap.parse_args()
    d = load()

    if a.cmd == "list":
        for sid, e in sorted(d.items(), key=lambda kv: kv[1]["expires"]):
            print("%-10s 剩 %3d 天（%s）改址剩 %d/%d  %-10s KEIS %-7s %s"
                  % (sid, left(e["expires"]), e["expires"], EDIT_LIMIT - e.get("edits", 0), EDIT_LIMIT,
                     e.get("case") or "-", e.get("adcase") or "-", e.get("title") or ""))
            if e.get("agent"):
                print("           聯絡：%s %s（%s）" % (e["agent"], e.get("phone") or "電話未記", e.get("store") or "-"))
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
        for k in ("agent", "phone", "store"):   # 換了案件，舊的聯絡人不能留著誤導
            e.pop(k, None)
        if not a.case:
            sys.exit("換物件要帶 --case（新案件編號）")
        if e.get("edits", 0) >= EDIT_LIMIT and a.edits is None:
            sys.exit("%s 這個刊期的改址次數已用完（%d/%d），591 不會讓你換物件。真的還有次數就帶 --edits 校正"
                     % (sid, e.get("edits", 0), EDIT_LIMIT))
        e["prev"] = (e.get("prev") or []) + [e.get("case")]   # 留換過的紀錄
        e["edits"] = e.get("edits", 0) + 1
    if a.cmd == "add" and not (exp or e.get("expires")):
        sys.exit("新增要帶 --expires 或 --left")
    for k, v in (("case", a.case), ("adcase", a.adcase), ("title", a.title), ("expires", exp), ("edits", a.edits),
                 ("agent", a.agent), ("phone", a.phone), ("store", a.store)):
        if v is not None:
            e[k] = v
    e["updated"] = str(date.today())
    d[sid] = e
    save(d)
    print("%s：%s → 剩 %d 天，改址剩 %d/%d" % (a.cmd, sid, left(e["expires"]), EDIT_LIMIT - e.get("edits", 0), EDIT_LIMIT),
          json.dumps(e, ensure_ascii=False))


if __name__ == "__main__":
    main()
