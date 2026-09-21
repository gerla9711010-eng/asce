#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""591 坪數換算：把來源頁的坪數欄位算成 591 表單要填的四個值。

用法：
  python ping.py --main 15.7 --annex 2.06 --public 12.918 --park 2.966 --total 30.67
  python ping.py --main 28.5 --annex 3.2 --public 0 --total 31.7      # 無公設車位

規則（2026-09-19 修正）：
  坪數一律「無條件捨去到小數點後 2 位」，但**只在最後輸出時捨去一次**。
  中間相加全部用原始精度——來源頁的「總建坪」本身就是 trunc(主+附+公設)，
  先捨去再相加會差 0.01~0.02 而對不上。
"""
import argparse, math, sys

TOL = 0.011  # 容許誤差：一個捨去單位

def tr(x):
    return math.floor(round(x, 6) * 100) / 100

def solve(main, annex, public, park, total):
    out, warn = {}, []
    sum_no_park = main + annex + public
    sum_with_park = sum_no_park + park

    if park <= 0:
        if abs(tr(sum_no_park) - total) > TOL:
            return None, ["無車位，但 主+附+公設 = %.3f（捨去 %.2f）對不上總建坪 %.2f，停下來問使用者"
                          % (sum_no_park, tr(sum_no_park), total)]
        out["車位面積"] = None
        out["車位類型"] = None
        out["共有部分"] = tr(public)
        out["權狀坪數"] = tr(total)
        out["權狀坪數選項"] = "不含車位面積"
        warn.append("無公設車位這條分支尚未在真實案件驗證過，送出前人工再看一次「權狀坪數」的下拉選項名稱")
        return out, warn

    subset = abs(tr(sum_no_park) - total) <= TOL
    additive = abs(tr(sum_with_park) - total) <= TOL

    if subset and additive:
        # 只可能在 park 小到捨去後消失時發生，極罕見
        warn.append("兩種分支都對得上（車位 %.3f 太小），依子集分支處理" % park)
    elif subset:
        pass
    elif additive:
        pass
    else:
        return None, [
            "兩種分支都套不出總建坪，停下來問使用者：",
            "  主+附+公設      = %.3f → 捨去 %.2f" % (sum_no_park, tr(sum_no_park)),
            "  主+附+公設+車位 = %.3f → 捨去 %.2f" % (sum_with_park, tr(sum_with_park)),
            "  來源頁總建坪    = %.2f" % total,
        ]

    out["車位面積"] = tr(park)
    out["共有部分"] = tr(public - park) if subset else tr(public)
    out["權狀坪數"] = tr(total)
    out["權狀坪數選項"] = "含車位面積"
    out["_分支"] = "公設車位是公共設施的子集（共有部分要扣掉車位）" if subset \
                 else "公設車位外加（共有部分不扣）"

    if out["共有部分"] < 0:
        return None, ["公設車位 %.3f 大於公共設施 %.3f，共有部分算出負數 %.2f，停下來問使用者"
                      % (park, public, out["共有部分"])]

    # 回推檢查：主+附+共有部分+車位 應該等於總建坪
    # 注意：子集分支下這個檢查是「有沒有飄移」而不是獨立驗算——扣掉車位再加回來會互相抵消，
    # 所以負數那種錯它抓不到，要靠上面那道 guard。
    check = tr(main + annex + out["共有部分"] + out["車位面積"])
    if abs(check - tr(total)) > TOL:
        warn.append("回推檢查不合：主+附+共有部分+車位 = %.2f ≠ 總建坪 %.2f，人工確認" % (check, total))
    return out, warn

def park_type(desc):
    d = desc or ""
    has_m, has_p = "機械" in d, "平面" in d
    if has_m and has_p: return "平面式+機械式"
    if has_m: return "機械式停車位"
    if has_p: return "平面式停車位"
    return "其他（跟使用者確認）"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--main", type=float, required=True, help="主建物")
    ap.add_argument("--annex", type=float, required=True, help="附屬建物")
    ap.add_argument("--public", type=float, required=True, help="公共設施")
    ap.add_argument("--park", type=float, default=0.0, help="公設車位（沒有就不填）")
    ap.add_argument("--total", type=float, required=True, help="總建坪")
    ap.add_argument("--parkdesc", default="", help="來源頁「停車方式」原文")
    ap.add_argument("--land", type=float, default=0.0, help="地坪（土地坪數）；透天/店面必填")
    a = ap.parse_args()

    out, warn = solve(a.main, a.annex, a.public, a.park, a.total)
    if out is None:
        print("[停手] 算不出來：")
        for w in warn: print("  " + w)
        sys.exit(1)

    print("分支：%s" % out.pop("_分支", "無車位"))
    print("-" * 46)
    if out["共有部分"]:
        print("591 共有部分   ：%s" % out["共有部分"])
    else:
        print("591 共有部分   ：0（無公設，該欄留空或填 0）")
    if out["車位面積"] is not None:
        print("591 車位面積   ：%s" % out["車位面積"])
        print("591 車位類型   ：%s" % park_type(a.parkdesc))
    else:
        print("591 車位面積   ：（無，該欄留空）")
    print("591 權狀坪數   ：%s（選「%s」）" % (out["權狀坪數"], out["權狀坪數選項"]))
    if a.land:
        print("591 土地坪數   ：%s" % tr(a.land))
    for w in warn:
        print("[注意] " + w)

if __name__ == "__main__":
    main()
