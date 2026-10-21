#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""案件資料 → 591 第 2 頁網址 ＋ fill591.js 的 DATA，加 --emit 直接產可貼上的腳本。

用法（2026-10-21 起資料預設走 KEIS API，不用開 houseol）：
  1. python prep.py AA1084264 --photos <dir>          # 案號；只給數字（1084264）也行，會去 KEIS 搜
     → 印 DATA、訴求重點、照片清單、注意事項
  2. Claude 依 SKILL.md Step 4 寫 head（【】那行）、亮點，跑第二次產腳本：
     python prep.py AA1084264 --head "美術園區｜恆上君悅｜三房雙衛平車" --title "…" \
         --hl "…" --hl "…" [--edit] --emit <dir>/run
     → <dir>/run_fill.js、<dir>/run_verify.js（已塞好 DATA、去掉註解），Read 後整份貼進 javascript_tool
  houseol 備案：KEIS 查不到時，get_page_text 抓 houseol print19 頁存成文字檔，把檔案路徑當第一個參數。

為什麼要有這支：手抄 20 幾個欄位到 DATA 是整個流程最容易靜靜抄錯的地方，坪數換算也一併
交給 ping.py 的 solve()，算不出來就 exit 1，跟直接跑 ping.py 同一套規則。
KEIS 跟 houseol 是同一份資料（2026-10-21 對過 AA1084264／EG0517920／AG1727776：坪數到小數 3 位都一樣），
KEIS 是結構化欄位，不用 regex 猜訴求重點是◎還是 1. 2. 3.，也不用把整頁重打成檔案。
KEIS 沒有「大樓名稱」：社區名靠 fill591 讀 591 依地址帶出的 placeholder，讀不到才從案名找。

房屋型態：透天/別墅/公寓/華廈直接對應；只寫「大樓」時用電梯數＋總樓層判（2026-10-21 使用者同意）：
  沒電梯→公寓、有電梯 10 樓以下→華廈、11 樓以上→電梯大樓。判不出來 exit 2 問使用者再帶 --type。
"""
import argparse, json, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
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


def split_points(body):
    """訴求重點原文 → 一條一條。三種寫法都見過：◎條列、「1. 2. 3.」編號（可能兩條擠同一行，
    AA1084264 的 5./6.）、一行一條沒符號（EG0517920）。(?!\\d) 防「路寬 8.5米」被當編號切開。"""
    pts = [p.strip() for p in re.findall(r"◎([^◎]+)", body)]
    if not pts and re.search(r"(?:^|\s)1[.、．](?!\d)", body):
        pts = [p.strip() for p in re.split(r"(?:^|\s)\d{1,2}[.、．](?!\d)", body) if p.strip()]
    if not pts:
        pts = [ln.strip() for ln in body.splitlines() if ln.strip()]
    return pts


def infer_type(form, elevators, above):
    """來源型式 → 591 房屋型態。回 (型態, 怎麼判的)；判不出回 (None, 原因)。"""
    for k, v in (("透天", "透天厝"), ("別墅", "別墅"), ("公寓", "公寓"), ("華廈", "華廈"), ("電梯", "電梯大樓")):
        if k in form:
            return v, "來源寫「%s」" % form
    if "大樓" in form or "大廈" in form:
        if elevators is None or not above:
            return None, "來源只寫「%s」，電梯數/總樓層缺（電梯 %s、地上 %s 樓）" % (form, elevators, above)
        if elevators == 0:
            return "公寓", "來源「%s」、沒電梯" % form
        return ("電梯大樓" if above >= 11 else "華廈"), "來源「%s」、電梯 %d 部、地上 %d 樓" % (form, elevators, above)
    return None, "來源型式「%s」對不到 591 型態" % form


# ---------------- 兩種來源 → 同一份 facts ----------------

FIXTURES = HERE / "fixtures"   # 離線測試資料（有地址/承辦人，個資，.gitignore 掉）


def from_keis(key, offline=False, save=False):
    """offline：只讀 fixtures/{案號}.json，不連 KEIS（改 prep.py 測試用，2026-10-21 測試連打 KEIS 被限流後加的）。
    save：連 KEIS 後把回應存成 fixture。"""
    if offline:
        p = FIXTURES / ("%s.json" % key)
        if not p.exists():
            sys.exit("沒有離線資料 %s（先用 --save-fixture 連一次 KEIS 存下來）" % p)
        fx = json.loads(p.read_text(encoding="utf-8"))
        return keis_facts(fx["prop"], fx["detail"])
    import keis
    c = keis.keis_client()
    prop = keis.find_property(c, key)
    if not prop:   # 只給數字（使用者常講「改發 1084264」）：前綴有 AA/AG/EG…，用搜尋找唯一一筆
        items = c.get(keis.API + "/property-management/", params={"search": key, "page_size": 20}).json().get("items", [])
        items = [i for i in items if re.sub(r"\D", "", i.get("contract_no", "")) == re.sub(r"\D", "", key)]
        if len(items) != 1:
            sys.exit("KEIS 用 %s 查到 %d 筆，停手：%s" % (key, len(items), [i.get("contract_no") for i in items]))
        prop = items[0]
    x = c.get(keis.API + "/property-management/%s/" % prop["id"]).json()
    if save:
        FIXTURES.mkdir(exist_ok=True)
        (FIXTURES / ("%s.json" % prop["contract_no"])).write_text(
            json.dumps({"prop": prop, "detail": x}, ensure_ascii=False, indent=1), encoding="utf-8")
        print("[fixture] 存到 %s" % (FIXTURES / ("%s.json" % prop["contract_no"])))
    return keis_facts(prop, x)


def keis_facts(prop, x):
    feats = "\n".join(x.get("feature_%d" % i) or "" for i in range(1, 6))
    cd = x.get("construction_date") or ""
    built = None
    if re.match(r"\d{4}-\d{2}-\d{2}", cd):
        y, m, d = cd[:10].split("-")
        built = (str(int(y) - 1911), str(int(m)), str(int(d)))
    lay = x.get("layout") or ""
    dm, ds = x.get("direction_main"), x.get("direction_secondary")
    price = x.get("case_price")
    return {
        "src": "KEIS", "contract_no": prop["contract_no"], "case_name": x.get("case_name"),
        "agent": x.get("sales_agent_name"), "store": x.get("store_name"),
        "addr": x.get("property_address_detail"), "community": "",
        "form": x.get("property_type") or "", "elevators": x.get("elevator_count") if x.get("elevator_count") is not None else (0 if x.get("property_type", "").endswith("透天") else None),
        "above": x.get("total_floors"), "floor_start": x.get("floor_start"), "floor_end": x.get("floor_end"),
        "main": num(x.get("main_area")), "annex": num(x.get("ancillary_area")), "public": num(x.get("pub_area")),
        "park": num(x.get("parking_area")), "total": num(x.get("total_registered_area")),
        "land": num(x.get("total_land_area")),
        "park_desc": x.get("parking_method") or "", "has_space": x.get("parking_type") or "",
        "rooms": x.get("room_count") or grab(r"(\d+)\s*房", lay), "halls": x.get("living_count") or grab(r"(\d+)\s*廳", lay),
        "baths": grab(r"(\d+)\s*衛", lay) or (str(int(x["bathroom_count"])) if x.get("bathroom_count") else None),
        "built": built, "price": ("%g" % price) if price else None,
        "fee": x.get("management_fee") or None, "fee_cycle": x.get("management_fee_payment_method") or "",
        "mrt": x.get("mrt_station") or None, "ori": ("坐%s朝%s" % (dm, ds)) if dm and ds else None,
        "points": split_points(feats), "market": x.get("market_info") or "",
        "status": x.get("current_status") or "", "contract_type": prop.get("contract_type"),
        "multi_from_main": None, "floors_main": [],
    }


def from_houseol(path):
    t = Path(path).read_text(encoding="utf-8")
    main_blk = grab(r"主\s*建\s*物(.*?)(?=附屬建物|公共設施|公設車位|地\s*坪)", t, "", re.S)
    lay = grab(r"格\s*局：(.*?)(?:面前路寬|\n)", t, "")
    built = grab(r"建築完成日：\s*(\d+/\d+/\d+)", t)
    m = re.search(r"座\s*向：\s*座\s*(\S*)\s*朝\s*(\S*)\s", t)
    ori = "坐%s朝%s" % (m.group(1), m.group(2)) if m and m.group(1) and m.group(2) and m.group(1) != "朝" else None
    selling = re.search(r"訴\s*求\s*重\s*點(.*?)(?:凱璿\S*公司|本表單係)", t, re.S)   # 結尾是該店公司名，別店不同
    elev = grab(r"電\s*梯：\s*(\d+)\s*部", t)
    rng = re.search(r"(\d+)\s*[-~～]\s*(\d+)\s*樓", main_blk)
    contract_no = grab(r"售合約編號：\s*(\w+)", t)
    ct = None   # houseol 備案不另外打 KEIS 查委託類型（使用者 10-21：不用為這個多查），下面會提醒手動選
    return {
        "src": "houseol", "contract_no": contract_no, "case_name": grab(r"案名：\s*(.+?)\s+型式/用途", t),
        "agent": grab(r"承辦人[ \t]+(\S+)", t), "store": grab(r"分店[ \t]+(\S+)", t),
        "addr": grab(r"座落：[ \t]*(\S+)", t),
        "community": grab(r"大樓名稱：[ \t]*(\S*)", t) or "",   # 空的時候 \s* 會跨行抓到下一行（AG1918099 抓成「總」）
        "form": grab(r"型式/用途：\s*(\S+)", t, ""),
        "elevators": int(elev) if elev else (0 if re.search(r"電\s*梯：\s*無", t) else None),
        "above": int(grab(r"地上\s*(\d+)\s*樓", t) or 0) or None, "floor_start": None, "floor_end": None,
        # 主建物可能分樓層列（透天 AG1727776：1/2/3 樓＋騎樓＋地下一層，騎樓、地下層也算主建物），全部加總
        "main": sum(num(v) for v in re.findall(r"([\d.]+)\s*坪", main_blk)),
        "annex": num(grab(r"附屬建物\s*([\d.]+)", t)), "public": num(grab(r"公共設施\s*([\d.]+)", t)),
        "park": num(grab(r"公設車位\s*([\d.]+)", t)), "total": num(grab(r"總\s*建\s*坪\s*([\d.]+)", t)),
        "land": num(grab(r"地\s*坪\s*([\d.]+)", t)),
        "park_desc": grab(r"停車方式：[ \t]*(\S*)", t, ""), "has_space": grab(r"車\s*位：[ \t]*(\S*)", t, ""),
        "rooms": grab(r"(\d+)\s*房", lay), "halls": grab(r"(\d+)\s*廳", lay), "baths": grab(r"(\d+)\s*衛", lay),
        "built": tuple(str(int(v)) if i else v for i, v in enumerate(built.split("/"))) if built else None,
        "price": grab(r"售價\s*([\d.]+)\s*萬", t), "fee": grab(r"管\s*理\s*費：\s*(\d+)", t), "fee_cycle": "月繳",
        "mrt": grab(r"捷\s*運\s*站：\s*(\S+?)\s+電\s*梯", t), "ori": ori,
        "points": split_points(selling.group(1) if selling else ""),
        "market": grab(r"市\s*場：[ \t]*(\S*)", t, ""), "status": grab(r"現\s*況：\s*(\S+)", t, ""),
        "contract_type": ct,
        # 大樓低樓層店住：主建物寫「1-2 樓 35.238 坪」、地址沒樓層（AG1918099）→ 出售多層
        "multi_from_main": (rng.group(1), rng.group(2)) if rng else None,
        "floors_main": [int(f) for f in re.findall(r"(?<![\d一二三四五六七八九十層])(\d+)\s*樓\s*[\d.]+\s*坪", main_blk)],
    }


# ---------------- facts → DATA ----------------

def spec_lines(d, is_house):
    """文案規格區（📍🏠📐🏢💰）照 DATA 組，數字跟表單同一份，不會打錯。"""
    loc = (d["district"] or "") + (d["street"] or "") + ("，" + d["community"] if d["community"] else "")
    if is_house:
        area = "📐建坪%s坪" % d["areaTotal"] + ("／地坪%s坪" % d["landArea"] if d["landArea"] else "")
    else:
        area = "📐權狀%s坪%s" % (d["areaTotal"], "（含車位）" if d["areaParking"] else "")
    if d["floorType"] == "出售多層":
        fl = ("🏢%s-%s樓／全棟%s層" % (d["floorFrom"], d["floorTo"], d["totalFloors"])
              if is_house and d["floorFrom"] == "1" and d["floorTo"] == str(d["totalFloors"])
              else "🏢%s-%s樓／%s樓" % (d["floorFrom"], d["floorTo"], d["totalFloors"]))
    else:
        fl = "🏢%s樓／%s樓" % (d["floorFrom"], d["totalFloors"])
    return ["📍" + loc, "🏠%s房%s廳%s衛" % (d["rooms"], d["halls"], d["baths"]), area, fl, "💰%s萬" % d["price"]]


def minify(js):
    """去掉註解跟縮排，貼進 javascript_tool 的字數少一半。fill591/verify591 裡沒有含 // 的字串（LINE 網址 10-21 拿掉了）。"""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    out = []
    for ln in js.splitlines():
        ln = re.sub(r"\s+//[^'\"`]*$", "", ln).strip()
        if ln and not ln.startswith("//"):
            out.append(ln)
    return "\n".join(out)


def put_data(js, data):
    i = js.index("const DATA = {")
    j = js.index("};", i) + 2
    return js[:i] + "const DATA = " + json.dumps(data, ensure_ascii=False) + ";" + js[j:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="案號（AA1084264，或只給數字）走 KEIS；houseol print19 頁文字檔路徑走備案")
    ap.add_argument("--type", choices=list(SHAPE), help="房屋型態；自動判不出來時才要帶（問使用者）")
    ap.add_argument("--photos", metavar="DIR", help="順便從 KEIS 下載照片解壓到這個資料夾")
    ap.add_argument("--community", help="社區名（591 帶不出來時，從案名或網路查到的）")
    ap.add_argument("--edit", action="store_true", help="換物件（改既有廣告）：產的腳本用修改模式")
    ap.add_argument("--head", help="文案第一行【】裡的字（地段＋房型＋賣點，不含價格）")
    ap.add_argument("--title", help="廣告標題（6～30 字）")
    ap.add_argument("--hl", action="append", default=[], help="亮點一條（2～5 條，只能改寫訴求重點）")
    ap.add_argument("--emit", metavar="PREFIX", help="產 PREFIX_fill.js、PREFIX_verify.js（要一起帶 --head --title --hl）")
    ap.add_argument("--offline", action="store_true", help="只讀 fixtures/，不連 KEIS（改這支程式時測試用）")
    ap.add_argument("--save-fixture", action="store_true", help="連 KEIS 後把回應存進 fixtures/")
    a = ap.parse_args()

    if a.offline and a.photos:
        sys.exit("--offline 不能下載照片（會連 KEIS）")
    f = from_houseol(a.src) if Path(a.src).is_file() else from_keis(a.src, a.offline, a.save_fixture)
    warn = []

    typ, why = (a.type, "手動 --type") if a.type else infer_type(f["form"], f["elevators"], f["above"])
    if not typ:
        print("[停手] %s——問使用者，再帶 --type 重跑" % why)
        sys.exit(2)

    out, pw = solve(f["main"], f["annex"], f["public"], f["park"], tr(f["total"]))
    if out is None:
        print("[停手] 坪數算不出來，問使用者：")
        for w in pw:
            print("  " + w)
        sys.exit(1)
    warn += pw

    a_ = parse_addr(f["addr"])
    if not a_:
        warn.append("地址拆不開：%s——city/district/street/no 要手動補" % f["addr"])
        a_ = {}
    is_house = typ in ("透天厝", "別墅")
    above = f["above"]
    if is_house:
        if f["floor_end"]:
            lo, hi = max(1, f["floor_start"] or 1), f["floor_end"]   # KEIS 透天 B1-3 記成 -1～3，591 填 1～3
        else:
            nfl = f["floors_main"] or [1]
            lo, hi = min(nfl), max(nfl)
        floor_type, f_from, f_to = "出售多層", str(lo), str(hi)
        total_floors = str(above or hi)
        community = None
    else:
        fs, fe = f["floor_start"], f["floor_end"]
        if fs and fe and fe != fs:
            floor_type, f_from, f_to = "出售多層", str(fs), str(fe)
        elif fs:
            floor_type, f_from, f_to = "出售單層", str(fs), ""
        elif f["multi_from_main"] and not a_.get("floor"):
            floor_type, (f_from, f_to) = "出售多層", f["multi_from_main"]
        else:
            floor_type, f_from, f_to = "出售單層", a_.get("floor"), ""
        total_floors = str(above) if above else None
        community = a.community or f["community"]
        if not f_from:
            warn.append("沒有樓層資料，floorFrom 要手動補")

    # 能上架就一定有委託書（使用者 2026-10-21），預設「有簽訂」不問；KEIS 順便帶回專任才選專任約
    contract = "有簽訂專任約" if f["contract_type"] == "專任委託" else "有簽訂"

    pts = "\n".join(f["points"])
    amenities = [n for n, pat in AMENITY if re.search(pat, pts)]
    if f["market"] not in GENERIC_MARKET and "近傳統市場" not in amenities:
        amenities.insert(1, "近傳統市場")
    tags = [n for n, pat in TAGS if re.search(pat, pts)]
    fee = f["fee"] if f["fee"] and int(float(f["fee"])) > 0 else None

    data = {
        "city": a_.get("city"), "district": a_.get("dist"), "street": a_.get("street"),
        "lane": a_.get("lane") or "", "alley": a_.get("alley") or "",
        "no": a_.get("no"), "noSub": a_.get("nosub") or "", "hideNo": True,
        "floorType": floor_type, "floorFrom": f_from, "floorTo": f_to,
        "totalFloors": total_floors, "community": community or "",
        "rooms": str(f["rooms"]) if f["rooms"] else None, "halls": str(f["halls"]) if f["halls"] else None,
        "baths": str(f["baths"]) if f["baths"] else None, "balcony": "",
        "builtY": f["built"][0] if f["built"] else None, "builtM": f["built"][1] if f["built"] else None,
        "builtD": f["built"][2] if f["built"] else None,
        "orientation": f["ori"],
        "areaTotal": fmt(out["權狀坪數"]), "areaMain": fmt(tr(f["main"])),
        "areaAnnex": fmt(tr(f["annex"])), "areaPublic": fmt(out["共有部分"]),
        "areaParking": fmt(out["車位面積"]) if out["車位面積"] is not None else None,
        "parkingType": park_type(f["park_desc"]) if out["車位面積"] is not None else None,
        "landArea": fmt(tr(f["land"])) if is_house and f["land"] else None,
        "price": f["price"], "mgmtFee": str(int(float(fee))) if fee else None, "mrt": f["mrt"],
        "title": "", "desc": [],
        "contract": contract,
        "amenities": amenities, "tags": tags,
    }
    if out["車位面積"] is None and f["has_space"] and f["has_space"] != "無" and not is_house:
        data["parkingInPrice"] = True
        warn.append("來源車位寫「%s」（停車方式 %s）但沒有公設車位坪數——問使用者：要補坪數，還是不填坪數、"
                    "售價選含車位、文案註明（AA1072556 使用者選後者）" % (f["has_space"], f["park_desc"]))
    if data["parkingType"] and "其他" in data["parkingType"]:
        warn.append("停車方式「%s」看不出平面/機械，車位類型跟使用者確認" % f["park_desc"])
    if fee and f["fee_cycle"] not in ("", "月繳"):
        warn.append("管理費是「%s」，fill591 只會選月繳，手動改" % f["fee_cycle"])
    if "出租" in (f["status"] or "") or "收租" in (f["case_name"] or ""):
        warn.append("現況「%s」／案名有收租：帶租約要問使用者（AG1918099 使用者說否）" % f["status"])
    if typ in ("電梯大樓", "華廈") and not data["community"]:
        warn.append("沒有社區名：留空，fill591 會讀 591 依地址帶出的（在 placeholder，回傳「社區來源」）；"
                    "是「無」才自己查：案名 → WebSearch「路名＋門牌 社區」（不帶樓層），再 --community 重產")
    for k in ("city", "district", "street", "no", "totalFloors", "rooms", "builtY", "price"):
        if not data[k]:
            warn.append("必填欄位 %s 沒抓到，手動補" % k)

    spec = spec_lines(data, is_house)
    region = REGION.get(data["city"])
    print("案件：%s｜%s｜承辦 %s（%s）｜來源 %s" % (f["contract_no"], f["case_name"], f["agent"], f["store"], f["src"]))
    print("型態：%s（%s）" % (typ, why))
    print("第 2 頁網址（新刊）：" + PAGE2.format(shape=SHAPE[typ], region="&region=%d" % region if region else ""))
    print("坪數分支：%s" % out.get("_分支", "無車位"))
    print("DATA =")
    print(json.dumps(data, ensure_ascii=False, indent=1))
    print("文案規格區（自動）：")
    for s in spec:
        print("  " + s)
    print("訴求重點（亮點區唯一素材）：")
    for p in f["points"]:
        print("  ◎" + p)
    if not f["points"]:
        print("  （空的——亮點區留空，跟使用者說明，不要自己編）")

    if a.photos and f["contract_no"]:
        import keis
        print("\n照片：")
        try:
            keis.cmd_photos(argparse.Namespace(contract_no=f["contract_no"], out=a.photos))
        except SystemExit as e:
            warn.append("照片下載失敗：%s" % e)

    if a.emit:
        if not (a.head and a.title and a.hl):
            sys.exit("--emit 要一起帶 --head、--title、--hl")
        if not 6 <= len(a.title) <= 30:
            warn.append("標題 %d 字，591 要 6～30 字" % len(a.title))
        if not 2 <= len(a.hl) <= 5:
            warn.append("亮點 %d 條，規格是 2～5 條" % len(a.hl))
        data["title"] = a.title
        data["desc"] = ["【%s】" % a.head] + spec + ["", "✨亮點"] + ["・" + h.lstrip("・") for h in a.hl]
        fill = put_data((HERE / "fill591.js").read_text(encoding="utf-8"), data)
        if a.edit:
            fill = fill.replace("const EDIT = null;", "const EDIT = { shape: '%s' };" % typ, 1)
        ver = put_data((HERE / "verify591.js").read_text(encoding="utf-8"), data)
        for suffix, js in (("_fill.js", fill), ("_verify.js", ver)):
            p = Path(a.emit + suffix)
            p.write_text(minify(js), encoding="utf-8")
            print("\n產出 %s（%d 行）" % (p, len(minify(js).splitlines())))
        print("模式：%s" % ("修改（換物件）EDIT shape=" + typ if a.edit else "新刊"))
    else:
        print("\n下一步：寫好 head／title／亮點後加 --head --title --hl%s --emit <prefix> 產腳本"
              % (" --edit" if a.edit else ""))

    print("\n刊登後 KEIS：新刊 `keis.py sync %s --url591 <網址>`；換物件 `keis.py swap S<編號> %s`（都先 dry-run）"
          % (f["contract_no"], f["contract_no"]))
    for w in warn:
        print("[注意] " + w)


if __name__ == "__main__":
    main()
