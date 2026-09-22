#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KEIS 公買查詢配額探測：打一次，看限流解了沒，結果推 Telegram。

為什麼要獨立成一支：2026-09-21 KEIS 開始限制「公買查詢每天最多 300 次」（**每個帳號各自算**，
2026-09-22 17:34 實測推翻了先前「綁 IP」的判斷）。歸零時點不是午夜（09-22 07:31、10:15 都還被擋，
17:15 已恢復），落在 17:10 前後。要再確認只能挑時間點試。

⚠️ **一次只打一次，不要連續重試。** 無法排除 KEIS 是「冷卻期內再碰就重置倒數」那種做法
（`retry-after` 永遠回固定的 86400，兩種做法從回應看起來一模一樣）。多戳幾次可能把自己
永遠鎖住，所以這支腳本刻意只打一次就結束。

用法：
    python quota_probe.py              # 打一次，推 Telegram
    python quota_probe.py --quiet      # 已經確認解除過就不重複推（給第二個時段的排程用）

排程（一次性，用完自己刪）：
    schtasks /create /tn "KEIS配額探測-1710" /tr "..." /sc once /st 17:15
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

HERE = Path(__file__).parent
MARKER = Path.home() / "OneDrive" / "桌面" / "keis" / "quota_probe_result.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true",
                    help="若先前的探測已經確認解除，就直接結束不再打（避免多餘的試探）")
    args = ap.parse_args()

    if args.quiet and MARKER.exists():
        try:
            if json.loads(MARKER.read_text(encoding="utf-8")).get("ok"):
                print("先前已確認解除，跳過")
                return 0
        except Exception:
            pass

    for env in (HERE / ".env", Path.home() / "OneDrive" / "桌面" / "keis" / ".env"):
        if env.exists():
            load_dotenv(env)
            break

    import grab
    import notify_telegram

    now = datetime.now()
    retry_after = None      # KEIS 回的原始 retry-after，用來分辨固定值還是真倒數
    accts = grab.load_accounts()
    if not accts:
        print("讀不到帳號")
        return 1
    try:
        body = grab.Keis(*accts[0]).query()
        n = len(body.get("data") or [])
        ok, text = True, (f"✅ KEIS 配額已恢復（{now.strftime('%m/%d %H:%M')} 探測，查到 {n} 筆）。"
                          f"不用做任何事：晚上本來就不放貨，搶單程式明天 00:01 會自己醒來，"
                          f"08:00 那班正常。想馬上恢復監控才需要重開 run.bat。")
    except grab.RateLimited as e:
        retry_after = e.retry_after
        # ⚠️ 一定要把 retry-after 的原始值留下來。它若一直是 86400 就是個沒資訊量的固定值；
        # 但只要哪一次回的是別的數字（尤其是遞減的），那就是真正的剩餘時間，答案直接出來。
        # 2026-09-22 之前沒記這個值，白白浪費了兩次探測機會。
        hint = ""
        if e.retry_after and e.retry_after != 86400:
            eta = now + timedelta(seconds=e.retry_after)
            hint = (f" ⭐ retry-after={e.retry_after}s（不是固定的 86400！這是真的剩餘時間，"
                    f"約 {eta.strftime('%m/%d %H:%M')} 解除）")
        else:
            hint = f"（retry-after={e.retry_after}s，還是那個固定值，沒有資訊量）"
        ok, text = False, (f"⛔ KEIS 配額還沒恢復（{now.strftime('%m/%d %H:%M')} 探測）："
                           f"{e.detail}{hint}。今天不再試探，下一個時段再看。")
    except Exception as e:
        ok, text = False, (f"⚠ KEIS 配額探測失敗（{now.strftime('%m/%d %H:%M')}）："
                           f"{type(e).__name__}: {str(e)[:120]}")

    print(text)
    try:
        hist = []
        if MARKER.exists():
            try:
                old = json.loads(MARKER.read_text(encoding="utf-8"))
                hist = old.get("history") or []
            except Exception:
                hist = []
        hist.append({"at": now.isoformat(timespec="seconds"), "ok": ok,
                     "retry_after": retry_after})
        MARKER.write_text(json.dumps(
            {"at": now.isoformat(timespec="seconds"), "ok": ok, "text": text,
             "retry_after": retry_after, "history": hist[-20:]},
            ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass
    if notify_telegram.enabled():
        notify_telegram.send(text)
    else:
        print("（Telegram 沒設定，只印在畫面上）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
