#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""houseol「不動產售屋資料」頁文字 → 591 第 2 頁網址 ＋ fill591.js 的 DATA。

用法：
  1. get_page_text 抓 houseol print19 頁，整段存成文字檔
  2. python prep.py page.txt --photos <scratchpad>/pics   （--type 只有來源寫「大樓」時才要帶）
  3. 照輸出開「第 2 頁網址」（直接跳過第 1 頁四層選單），把 DATA 貼進 fill591.js，
     title / desc 由 Claude 依 SKILL.md Step 4 的規格自己寫（素材是輸出的「訴求重點」）

為什麼要有這支：手抄 20 幾個欄位到 DATA 是整個流程最容易靜靜抄錯的地方，坪數換算也一併
交給 ping.py 的 solve()，算不出來就 exit 1，跟直接跑 ping.py 同一套規則。

委託書（一般/專任）會去 KEIS 查 contract_type；查不到就留 null 並警告，不要自己猜。
--photos 順便從 KEIS 下載照片（同 keis.py photos），最後印出刊登後要跑的 KEIS 同步指令（承辦人已帶好）。

房屋型態：來源「型式/用途」寫透天/別墅/公寓/華廈就直接對應；只寫「大樓」分不出公寓/華廈/電梯大樓，
這時 exit 2 叫你問使用者再帶 --type（2026-10-14 使用者同意改成只有大樓才問）。
"""
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ping import solve, park_type, tr  # noqa: E402

# 591 第 1 頁「房屋型態」對應網址的 shape（2026-10-14 逐一點過記下來的）
SHAPE = {"公寓": 1, "電梯大樓": 2, "透天厝": 3, "別墅": 4, "華廈": 5}
# 縣市 → region；只驗過高雄。其他縣市不帶 region，591 會跳縣市選單讓人點
REGION = {"高雄市": 17}
PAGE2 = ("https://user.591.com.tw/post/two/sale?is_use_first=1&kind=9&shape={shape}"
         "&purpose=3&purpose_custom=&use_new_post=0{region}&new_post_plan=1")

CN_NUM = "〇一二三四五六七八九十"

# 591「生活機能」勾選（買方篩選會用到）。只認訴求重點原文的明確字眼，寧可漏勾不要錯勾（2026-10-14 使用者同意這套規則）。
# 學區欄不算數（每間都有學區）；市場欄只寫泛稱「傳統市場」也不算，要有實際名稱。
AMENITY = [
    ("近便利商店", r"超商|便利商店|7-?11|全家"),
    ("近傳統市場", r"[市巿]場"),   # 巿（U+5DFF）是常見錯字，AG1918099「近自由巿場」
    ("近百貨公司", r"百貨"),
    ("近公園綠地", r"公園|綠地"),
    ("近學校", r"學校|學區|國小|國中|高中|大學"),
    ("近醫療機構", r"醫院|醫療|診所|醫學"),
    ("近夜市", r"夜市"),
]
# 「特色標籤」更嚴：訴求重點原文要出現這幾個字才勾
TAGS = [("明星學區", r"明星學區"), ("制震宅", r"制震"), ("重劃區", r"重劃區")]
GENERIC_MARKET = {"", "傳統市場", "市場", "無"}


def grab(pat, text, default=None, flags=0):
    m = re.search(pat, text, flags)
    return m.group(1).strip() if m else default


def num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def fmt(x):
    """坪數輸出成字串，保留兩位（3.6 → '3.60'），跟 591 回讀的值一致。"""
    return "%.2f" % x


def parse_addr(addr):
    addr = addr or ""
    city, rest = addr[:3], addr[3:]
    if not city.endswith(("市", "縣")):
        return None
    # 鄉鎮區：先認「區」——「前鎮區」「鳳山區」名字裡就有鎮/市，懶惰比對會切錯（踩過：前鎮｜區公正路）
    i = rest.find("區", 0, 5)
    if i < 0:
        i = min([j for j in (rest.find(c, 1, 5) for c in "鄉鎮市") if j > 0] or [-1])
    if i < 0:
        return None
    dist, rest = rest[:i + 1], rest[i + 1:]
    m = re.match(
        r"(?P<street>.+?(?:路|街|大道|道)(?:[" + CN_NUM + r"\d]+段)?)"
        r"(?:(?P<lane>\d+)巷)?(?:(?P<alley>\d+)弄)?(?P<no>\d+)號(?:之(?P<nosub>\d+))?"
        r"(?:(?P<floor>\d+)樓)?", rest)
    if not m:
        return None
    return dict(m.groupdict(), city=city, dist=dist)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("page", help="houseol print19 頁的文字檔")
    ap.add_argument("--type", choices=list(SHAPE), help="房屋型態；來源只寫「大樓」時必帶（問使用者）")
    ap.add_argument("--photos", metavar="DIR", help="順便從 KEIS 下載照片解壓到這個資料夾")
    ap.add_argument("--no-keis", action="store_true", help="不查 KEIS 委託類型")
    a = ap.parse_args()

    t = Path(a.page).read_text(encoding="utf-8")
    warn = []

    contract_no = grab(r"售合約編號：\s*(\w+)", t)
    case_name = grab(r"案名：\s*(.+?)\s+型式/用途", t)
    addr = grab(r"座落：[ \t]*(\S+)", t)
    community = grab(r"大樓名稱：[ \t]*(\S*)", t)  # 空的時候 \s* 會跨行抓到下一行（AG1918099 抓成「總」）
    agent = grab(r"承辦人[ \t]+(\S+)", t)
    form = grab(r"型式/用途：\s*(\S+)", t, "")
    if not a.type:
        a.type = next((v for k, v in (("透天", "透天厝"), ("別墅", "別墅"), ("公寓", "公寓"),
                                       ("華廈", "華廈"), ("電梯", "電梯大樓")) if k in form), None)
        if not a.type:
            print("[停手] 來源型式寫「%s」，分不出公寓/華廈/電梯大樓——問使用者，再帶 --type 重跑" % form)
            sys.exit(2)

    # ---- 坪數 ----
    total = num(grab(r"總\s*建\s*坪\s*([\d.]+)", t))
    # 主建物可能分樓層列，夾在「物」跟下一個坪數欄位之間的「N 坪」全部加總。
    # 透天實例（AG1727776）：1 樓／2 樓／3 樓／騎樓 樓／地下一層 樓 各一行，而且沒有「附屬建物」那行，
    # 騎樓、地下層也算主建物（加起來才等於總建坪）。
    main_blk = grab(r"主\s*建\s*物(.*?)(?=附屬建物|公共設施|公設車位|地\s*坪)", t, "", re.S)
    main_area = sum(num(v) for v in re.findall(r"([\d.]+)\s*坪", main_blk))
    floors_main = re.findall(r"(?<![\d一二三四五六七八九十層])(\d+)\s*樓\s*[\d.]+\s*坪", main_blk)
    annex = num(grab(r"附屬建物\s*([\d.]+)", t))
    public = num(grab(r"公共設施\s*([\d.]+)", t))
    park = num(grab(r"公設車位\s*([\d.]+)", t))
    land = num(grab(r"地\s*坪\s*([\d.]+)", t))
    park_desc = grab(r"停車方式：[ \t]*(\S*)", t, "")

    out, pw = solve(main_area, annex, public, park, total)
    if out is None:
        print("[停手] 坪數算不出來，問使用者：")
        for w in pw:
            print("  " + w)
        sys.exit(1)
    warn += pw

    # ---- 其他欄位 ----
    a_ = parse_addr(addr)
    if not a_:
        warn.append("地址拆不開：%s——city/district/street/no 要手動補" % addr)
        a_ = {}
    above = grab(r"地上\s*(\d+)\s*樓", t)
    rooms = grab(r"(\d+)\s*房", grab(r"格\s*局：(.*?)(?:面前路寬|\n)", t, ""))
    halls = grab(r"(\d+)\s*廳", grab(r"格\s*局：(.*?)(?:面前路寬|\n)", t, ""))
    baths = grab(r"(\d+)\s*衛", grab(r"格\s*局：(.*?)(?:面前路寬|\n)", t, ""))
    built = grab(r"建築完成日：\s*(\d+/\d+/\d+)", t)
    by, bm, bd = (built.split("/") if built else (None, None, None))
    price = grab(r"售價\s*([\d.]+)\s*萬", t)
    fee = grab(r"管\s*理\s*費：\s*(\d+)", t)
    mrt = grab(r"捷\s*運\s*站：\s*(\S+?)\s+電\s*梯", t)
    ori = None
    m = re.search(r"座\s*向：\s*座\s*(\S*)\s*朝\s*(\S*)\s", t)
    if m and m.group(1) and m.group(2) and m.group(1) not in ("朝",):
        ori = "坐%s朝%s" % (m.group(1), m.group(2))
    selling = re.search(r"訴\s*求\s*重\s*點(.*?)(?:凱璿不動產事業股份有限公司|本表單係)", t, re.S)
    points = [p.strip() for p in re.findall(r"◎([^◎]+)", selling.group(1))] if selling else []

    pts = "\n".join(points)
    market = grab(r"市\s*場：[ \t]*(\S*)", t, "")
    amenities = [n for n, pat in AMENITY if re.search(pat, pts)]
    if market not in GENERIC_MARKET and "近傳統市場" not in amenities:
        amenities.insert(1, "近傳統市場")
    tags = [n for n, pat in TAGS if re.search(pat, pts)]

    is_house = a.type in ("透天厝", "別墅")
    if is_house:
        nfl = [int(f) for f in floors_main] or [1]
        floor_type, f_from, f_to = "出售多層", str(min(nfl)), str(max(nfl))
        total_floors = above or str(max(nfl))
        community = None
    else:
        # 大樓的低樓層店住：主建物寫「1-2 樓 35.238 坪」、地址沒有樓層（AG1918099）→ 出售多層
        rng = re.search(r"(\d+)\s*[-~～]\s*(\d+)\s*樓", main_blk)
        if rng and not a_.get("floor"):
            floor_type, f_from, f_to = "出售多層", rng.group(1), rng.group(2)
        else:
            floor_type, f_from, f_to = "出售單層", a_.get("floor"), ""
        total_floors = above
        if not f_from:
            warn.append("地址裡沒有樓層，floorFrom 要手動補")

    contract = None
    if not a.no_keis and contract_no:
        try:
            import keis
            c = keis.keis_client()
            ct = (keis.find_property(c, contract_no) or {}).get("contract_type")
            contract = {"一般委託": "有簽訂", "專任委託": "有簽訂專任約"}.get(ct)
            if not contract:
                warn.append("KEIS contract_type=%r 對不到委託書選項，問使用者" % ct)
        except Exception as e:  # KEIS 掛了不擋整份，但要講
            warn.append("KEIS 查委託類型失敗（%s），contract 要手動補" % e)

    data = {
        "city": a_.get("city"), "district": a_.get("dist"), "street": a_.get("street"),
        "lane": a_.get("lane") or "", "alley": a_.get("alley") or "",
        "no": a_.get("no"), "noSub": a_.get("nosub") or "", "hideNo": True,
        "floorType": floor_type, "floorFrom": f_from, "floorTo": f_to,
        "totalFloors": total_floors, "community": community or "",
        "rooms": rooms, "halls": halls, "baths": baths, "balcony": "",
        "builtY": by, "builtM": str(int(bm)) if bm else None, "builtD": str(int(bd)) if bd else None,
        "orientation": ori,
        "areaTotal": fmt(out["權狀坪數"]), "areaMain": fmt(tr(main_area)),
        "areaAnnex": fmt(tr(annex)), "areaPublic": fmt(out["共有部分"]),
        "areaParking": fmt(out["車位面積"]) if out["車位面積"] is not None else None,
        "parkingType": park_type(park_desc) if out["車位面積"] is not None else None,
        "landArea": fmt(tr(land)) if is_house and land else None,
        "price": price, "mgmtFee": fee if fee and int(fee) > 0 else None, "mrt": mrt,
        "title": "", "desc": [],
        "contract": contract,
        "amenities": amenities, "tags": tags,
    }
    has_space = grab(r"車\s*位：[ \t]*(\S*)", t, "")
    if out["車位面積"] is None and has_space and has_space != "無":
        data["parkingInPrice"] = True
        warn.append("來源車位寫「%s」（停車方式 %s）但沒有公設車位坪數——問使用者：要補坪數，還是不填坪數、"
                    "售價選含車位、文案註明（AA1072556 使用者選後者）" % (has_space, park_desc))
    if data["parkingType"] and "其他" in data["parkingType"]:
        warn.append("停車方式「%s」看不出平面/機械，車位類型跟使用者確認" % park_desc)
    for k in ("city", "district", "street", "no", "totalFloors", "rooms", "builtY", "price"):
        if not data[k]:
            warn.append("必填欄位 %s 沒抓到，手動補" % k)

    shape = SHAPE[a.type]
    region = REGION.get(data["city"])
    print("案件：%s｜%s｜承辦 %s｜型態 %s（來源：%s）" % (contract_no, case_name, agent, a.type, form))
    print("第 2 頁網址：" + PAGE2.format(shape=shape, region="&region=%d" % region if region else ""))
    print("坪數分支：%s" % out.get("_分支", "無車位"))
    print("DATA =")
    print(json.dumps(data, ensure_ascii=False, indent=1))
    print("訴求重點（亮點區唯一素材）：")
    for p in points:
        print("  ◎" + p)
    if not points:
        print("  （空的——亮點區留空，跟使用者說明，不要自己編）")
    if a.photos and contract_no:
        import keis
        print("\n照片：")
        try:
            keis.cmd_photos(argparse.Namespace(contract_no=contract_no, out=a.photos))
        except SystemExit as e:
            warn.append("照片下載失敗：%s" % e)
    print("\n刊登後 KEIS 同步（先 dry-run，對了再加 --apply）：")
    print("  python .claude/skills/591-ad/keis.py sync %s --url591 <廣告網址> --member %s"
          % (contract_no, agent or "<承辦人>"))
    for w in warn:
        print("[注意] " + w)


if __name__ == "__main__":
    main()
