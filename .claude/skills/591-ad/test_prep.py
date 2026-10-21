#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""prep.py 回歸測試，全部離線（fixtures/），一個 KEIS 請求都不送。改 prep.py／ping.py 之後跑：
    python .claude/skills/591-ad/test_prep.py

為什麼要有（2026-10-21）：改 prep.py 時每測一次就連 KEIS 一次，二十幾次被限流（紅線 360）。
期望值都是 591 前台驗收過的（verify591 16/16）：AA1084264＝S21079307、EG0517920＝S20698894；
AG1727776＝S21079267（10-14 刊的透天）。fixtures/ 有個資，不進 git；沒有就先 prep.py <案號> --save-fixture。
"""
import json, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FX = HERE / "fixtures"

COMMON = {"hideNo": True, "contract": "有簽訂"}
CASES = [
    # (參數, 期望型態, 期望 DATA 欄位)
    (["AA1084264", "--offline"], "電梯大樓", {
        "district": "鼓山區", "street": "馬卡道路", "no": "407", "floorType": "出售單層", "floorFrom": "8",
        "totalFloors": "13", "rooms": "3", "halls": "2", "baths": "2", "builtY": "94", "builtM": "12", "builtD": "15",
        "orientation": "坐東南朝西北", "areaTotal": "43.05", "areaMain": "22.39", "areaAnnex": "2.68",
        "areaPublic": "12.22", "areaParking": "5.74", "parkingType": "平面式停車位", "landArea": None,
        "price": "1580", "mgmtFee": "2439"}),
    (["EG0517920", "--offline"], "電梯大樓", {
        "district": "鳥松區", "street": "澄明街", "no": "208", "floorType": "出售單層", "floorFrom": "5",
        "totalFloors": "15", "rooms": "4", "builtY": "106", "builtM": "6", "builtD": "2",
        "areaTotal": "63.13", "areaMain": "29.95", "areaAnnex": "9.80", "areaPublic": "17.39",
        "areaParking": "5.98", "price": "2498", "mgmtFee": "4286"}),
    (["AG1727776", "--offline"], "透天厝", {
        "district": "三民區", "street": "建工路", "floorType": "出售多層", "floorFrom": "1", "floorTo": "3",
        "totalFloors": "3", "areaTotal": "46.16", "areaMain": "46.16", "landArea": "24.95",
        "areaParking": None, "mrt": "C28高雄高工", "price": "2288"}),
    # houseol 備案路線：同兩案，結果要跟 KEIS 版一樣（社區名 houseol 才有）
    ([str(FX / "AA1084264.txt")], "電梯大樓", {
        "areaTotal": "43.05", "areaMain": "22.39", "areaPublic": "12.22", "areaParking": "5.74",
        "floorFrom": "8", "price": "1580"}),
    ([str(FX / "EG0517920.txt")], "電梯大樓", {
        "community": "圓山大院", "areaTotal": "63.13", "areaParking": "5.98", "floorFrom": "5"}),
]
# 訴求重點切條：AA1084264 的 5./6. 擠同一行要切成 6 條
POINTS = {"AA1084264": 6}


def main():
    fail = 0
    for args, typ, want in CASES:
        name = Path(args[0]).name
        if not (Path(args[0]).exists() or (FX / (args[0] + ".json")).exists()):
            print("SKIP %s（沒有 fixture）" % name)
            continue
        out = subprocess.run([sys.executable, str(HERE / "prep.py")] + args, capture_output=True,
                             text=True, encoding="utf-8").stdout
        m = re.search(r"DATA =\n(\{.*?\n\})", out, re.S)
        if not m:
            print("FAIL %s：沒有 DATA\n%s" % (name, out[-500:]))
            fail += 1
            continue
        d = json.loads(m.group(1))
        bad = ["%s 要 %r 得 %r" % (k, v, d.get(k)) for k, v in {**COMMON, **want}.items() if d.get(k) != v]
        if not re.search(r"型態：%s" % typ, out):
            bad.append("型態不是 %s：%s" % (typ, (re.search(r"型態：.*", out) or [""])[0]))
        if "坪數算不出來" in out or "回推檢查不合" in out:
            bad.append("坪數警告")
        key = name.split(".")[0]
        if key in POINTS and len(re.findall(r"  ◎", out)) != POINTS[key]:
            bad.append("訴求重點 %d 條，要 %d" % (len(re.findall(r"  ◎", out)), POINTS[key]))
        print(("FAIL %s：%s" % (name, "；".join(bad))) if bad else "ok   %s" % name)
        fail += bool(bad)
    print("\n%s" % ("全部通過" if not fail else "%d 案失敗" % fail))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
