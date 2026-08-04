# -*- coding: utf-8 -*-
"""KEIS 公買競爭態勢週報。

回答的問題是「我們在這個池子裡的處境如何」，不是「今天搶到幾筆」（那個看 LINE 就好）：
  1. 這週公買出了多少貨、我們吃下多少
  2. 沒吃到的那些，卡在哪一條規則（哪一條擋掉最多）
  3. 哪些行政區／類型出貨最多
  4. 名單從進池到被搶走能撐幾秒（＝競爭有多兇）

用法：
    python stats.py            # 印出報表
    python stats.py --line     # 印出並推一則摘要到 LINE
    python stats.py --days 30  # 改看 30 天

⚠️ 存活秒數需要 `首次看到` 準確才算得出來。2026-08-04 那天總帳被覆蓋、整池的 `首次看到`
被蓋成同一時刻，所以那天（含以前）的存活秒數不可信，程式會自動排除算不出合理值的樣本。
"""
import argparse
import csv
import os
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCAL = Path(os.environ.get("LOCALAPPDATA") or HERE) / "keis-grab"
INVENTORY = LOCAL / "inventory.csv"
DAILY_SUMMARY = HERE / "daily_summary.csv"
GRABBED = HERE / "grabbed.csv"

# 存活秒數的合理範圍：負的代表我們是在它被申請之後才第一次看到（總帳失真或窗口排不到），
# 超過一天的多半是沒人要的冷門單，兩種都不能代表「競爭速度」，直接排除。
ALIVE_MIN_SEC, ALIVE_MAX_SEC = 0, 86400

# 總帳被重建的那一天，整池上千筆的 `首次看到` 會全被蓋成同一時刻，混進來會讓每個數字都失真
# （2026-08-04 實測：一天冒出 2862 筆「新進池」，真實只有 39 筆）。
# 歷史上真實單日最大量是 32 筆，所以「單日超過 300 筆」一定是重建造成的，整天排除。
LEDGER_REBUILD_THRESHOLD = 300


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    try:
        with p.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        print(f"⚠ 讀 {p.name} 失敗：{type(e).__name__}", file=sys.stderr)
        return []


def parse_dt(s: str):
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime((s or "")[:19], fmt)
        except Exception:
            continue
    return None


def build(days: int) -> dict:
    since = datetime.now() - timedelta(days=days)
    inv = read_csv(INVENTORY)

    # 這段期間第一次進池的名單
    recent = []
    for r in inv:
        d = parse_dt(r.get("首次看到", ""))
        if d and d >= since:
            recent.append(r)

    # 剔除「總帳重建日」——那天的 首次看到 是假的，留著會讓所有比例失真
    by_day = Counter(parse_dt(r["首次看到"]).strftime("%Y-%m-%d") for r in recent)
    dirty = {d for d, c in by_day.items() if c > LEDGER_REBUILD_THRESHOLD}
    if dirty:
        recent = [r for r in recent
                  if parse_dt(r["首次看到"]).strftime("%Y-%m-%d") not in dirty]

    # 只留「真的在池子裡觀察到」的列。來源=我方歷史搶單 是啟動時用 grabbed.csv 回填的，
    # 它的 首次看到 = 搶到時間、我方動作 恆為「搶到」——混進來會讓命中率永遠是 100%。
    recent = [r for r in recent if r.get("來源") != "我方歷史搶單"]

    got = [r for r in recent if r.get("我方動作") == "搶到"]

    # 沒吃到的卡在哪 —— 用「首次符合篩選=N」那些的當下原因
    # （`不符原因` 每輪會被覆蓋，最後多半停在「狀態=CoolingDown」，所以只拿它當粗略分類，
    #   並且把「狀態=」那類單獨歸成「被別人先拿走」，免得誤導成是我們的條件擋的）
    blocked = Counter()
    for r in recent:
        if r.get("我方動作") == "搶到":
            continue
        why = (r.get("不符原因") or "").strip()
        if not why:
            blocked["其他／不明"] += 1
        elif why.startswith("狀態="):
            blocked["被別人先拿走"] += 1
        elif why.startswith("縣市="):
            blocked["外縣市"] += 1
        elif why.startswith("預算上限"):
            blocked["預算上限低於 1000 萬"] += 1
        elif why == "非手機":
            blocked["市話／空號"] += 1
        elif why.startswith("排除類型"):
            blocked["公寓"] += 1
        elif why.startswith("建檔"):
            blocked["建檔超過 10 天"] += 1
        else:
            blocked[why] += 1

    areas = Counter((r.get("行政區") or "未填").strip() or "未填" for r in recent)
    cats = Counter((r.get("類型") or "未填").strip() or "未填" for r in recent)

    # 存活秒數：從第一次看到它是 Available，到它被申請走
    alive = []
    for r in recent:
        seen, app = parse_dt(r.get("首次看到", "")), parse_dt(r.get("app_time", ""))
        if seen and app and r.get("首次狀態") == "Available":
            sec = (app - seen).total_seconds()
            if ALIVE_MIN_SEC <= sec <= ALIVE_MAX_SEC:
                alive.append(sec)
    alive.sort()

    daily = [r for r in read_csv(DAILY_SUMMARY)
             if (r.get("日期") or "") >= since.strftime("%Y-%m-%d")]

    return {"days": days, "recent": recent, "got": got, "blocked": blocked,
            "areas": areas, "cats": cats, "alive": alive, "daily": daily,
            "dirty": sorted(dirty)}


MIN_SAMPLE = 10          # 少於這個數，任何比例都只是雜訊，不要裝作看得出趨勢


def _short(d: dict) -> str | None:
    """樣本太少時，直接說「還不能下結論」，不要印一份看起來有模有樣的假報表。"""
    if len(d["recent"]) >= MIN_SAMPLE:
        return None
    L = [f"📊 KEIS 公買競爭態勢（近 {d['days']} 天）", "",
         f"可用樣本只有 {len(d['recent'])} 筆，還不足以下任何結論。", ""]
    if d["dirty"]:
        L += [f"原因：總帳在 {'、'.join(d['dirty'])} 被重建過，那幾天整池的「首次看到」",
              "被蓋成同一時刻，全部排除了。乾淨資料從重建日的隔天開始累積，",
              "大約一週後這份報表才有意義。"]
    else:
        L.append("原因：這段期間公買出貨太少。")
    return "\n".join(L)


def fmt_report(d: dict) -> str:
    if (s := _short(d)):
        return s
    n, g = len(d["recent"]), len(d["got"])
    rate = f"{g / n * 100:.0f}%" if n else "—"
    L = [f"📊 KEIS 公買競爭態勢（近 {d['days']} 天）", ""]
    L.append(f"新進池名單 {n} 筆／我方拿到 {g} 筆（吃下 {rate}）")
    if d["dirty"]:
        L.append(f"⚠ 已排除總帳重建日：{'、'.join(d['dirty'])}（那幾天的紀錄不可信）")

    if d["alive"]:
        a = d["alive"]
        L += ["", f"⏱ 名單存活時間（進池 → 被申請走），{len(a)} 筆樣本",
              f"   中位數 {a[len(a) // 2]:.0f} 秒／最快 {a[0]:.0f} 秒／最慢 {a[-1] / 60:.0f} 分"]
    else:
        L += ["", "⏱ 存活時間：樣本不足（需要 `首次看到` 準確的資料，2026-08-05 起才會累積）"]

    L += ["", "🚧 沒拿到的卡在哪"]
    total_blocked = sum(d["blocked"].values()) or 1
    for why, c in d["blocked"].most_common(6):
        L.append(f"   {why:<18} {c:>4} 筆（{c / total_blocked * 100:.0f}%）")

    L += ["", "📍 出貨最多的行政區"]
    for a, c in d["areas"].most_common(6):
        L.append(f"   {a:<10} {c:>4} 筆")

    L += ["", "🏠 類型分布"]
    for t, c in d["cats"].most_common(6):
        L.append(f"   {t:<10} {c:>4} 筆")

    if d["daily"]:
        L += ["", "📅 每日（新名單／符合條件／搶到）"]
        for r in d["daily"]:
            L.append(f"   {r.get('日期')}  {r.get('新名單') or '-':>4}"
                     f" ／{r.get('符合條件') or '-':>4} ／{r.get('搶到') or '-':>4}")
    return "\n".join(L)


def fmt_line(d: dict) -> str:
    """LINE 版：手機看得完的長度，只留最能改變決策的東西。"""
    if (s := _short(d)):
        return s
    n, g = len(d["recent"]), len(d["got"])
    rate = f"{g / n * 100:.0f}%" if n else "—"
    L = [f"📊 KEIS 公買週報（近 {d['days']} 天）",
         f"新進池 {n} 筆／我方拿到 {g} 筆（{rate}）"]
    if d["alive"]:
        a = d["alive"]
        L.append(f"⏱ 名單平均撐 {a[len(a) // 2]:.0f} 秒就被搶走")
    L.append("")
    L.append("沒拿到的前三名：")
    for why, c in d["blocked"].most_common(3):
        L.append(f"・{why} {c} 筆")
    top = d["areas"].most_common(3)
    if top:
        L.append("")
        L.append("出貨最多：" + "、".join(f"{a}{c}筆" for a, c in top))
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--line", action="store_true", help="推一則摘要到 LINE")
    args = ap.parse_args()

    if not INVENTORY.exists():
        print(f"✗ 找不到總帳 {INVENTORY}", file=sys.stderr)
        return 1

    d = build(args.days)
    print(fmt_report(d))

    if args.line:
        sys.path.insert(0, str(HERE))
        try:
            import grab                                  # 借用 grab.py 既有的 notify
            ok = grab.notify({"event": "alert", "text": fmt_line(d)})
            print("\n📲 LINE 已推" if ok else "\n❌ LINE 推播失敗")
        except Exception as e:
            print(f"\n❌ 推 LINE 失敗：{type(e).__name__}: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
