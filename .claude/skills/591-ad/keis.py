#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""591-ad 的 KEIS 助手：抓照片 + 刊登後同步廣告追蹤。

用法：
  python keis.py photos AA1072565 [--out 資料夾]
      反查 KEIS 物件ID → download-images zip → 解壓 → 印出檔案清單（給 591 上傳用）

  python keis.py sync AA1072565 --url591 https://sale.591.com.tw/home/house/detail/2/xxxx.html
      預設 dry-run，只印出「會怎麼改」。確認沒問題再加 --apply 真的寫進去。

憑證：讀桌面 keis 資料夾的 .env
  KEIS_USERNAME / KEIS_PASSWORD（KEIS 本體）
  KEIS_NOTION_TOKEN（查永慶官網連結用，沒有就得自己帶 --yc-url）

2026-09-19 實測過的 API 眉角（改之前先看，不要憑印象）：
  - 端點路徑結尾一定要有斜線，少了會 307（httpx 預設不跟隨 → 空回應）
  - property-management 只吃 `search=`，contract_no / keyword / q 全部被無聲忽略（回全部 7138 筆）
  - adcases 分頁參數是 `skip`（筆數位移），`page` 會被無聲忽略永遠回第一頁；page_size 上限 50
  - adcases 回傳的 list key 叫 `adcases`，不是 `items`
  - adcase_url 只收永慶/台慶連結，塞 houseol 網址會 500
  - KEIS 慣例是「一物件一筆廣告、多平台掛同一筆」：全部 266 筆裡沒有任何一個物件連結
    出現兩次，而 adcase_platforms 有一筆是 "591,臉書"（逗號分隔）。所以 591 上架後要
    **併進既有那筆**，不要新開一筆。
  - PUT 不確定是不是 partial update，所以一律「GET 整筆 → 改一個欄位 → PUT 整筆 → 再 GET 驗」，
    這樣不管它是覆蓋還是合併，結果都對，也不會把臉書連結洗掉。
"""
import argparse
import io
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import httpx

ENV_PATH = Path(os.path.expanduser("~")) / "OneDrive" / "桌面" / "keis" / ".env"
BASE = "https://keis.kshouse.com.tw"
API = BASE + "/api/v1"
NOTION_AD_DB = "07ee845168b64f8a9b5682e5069c733b"
PLATFORM_591 = "591"


def load_env():
    if not ENV_PATH.exists():
        sys.exit("找不到憑證檔：%s" % ENV_PATH)
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def keis_client():
    load_env()
    c = httpx.Client(timeout=120, follow_redirects=True,
                     headers={"user-agent": "Mozilla/5.0", "referer": BASE + "/login"})
    r = c.post(API + "/auth/login",
               data={"username": os.environ["KEIS_USERNAME"],
                     "password": os.environ["KEIS_PASSWORD"]})
    r.raise_for_status()
    c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
    return c


def find_property(c, contract_no):
    """案件編號 → KEIS 物件。查無回 None；查到多筆取 id 最大（最新）那筆。"""
    d = c.get(API + "/property-management/",
              params={"search": contract_no, "page_size": 20}).json()
    hits = [i for i in d.get("items", []) if i.get("contract_no") == contract_no]
    if not hits:
        return None
    if len(hits) > 1:
        print("[注意] 同一個案件編號查到 %d 筆，取 id 最大的那筆：" % len(hits))
        for h in hits:
            print("   id=%s status=%s case_name=%s"
                  % (h["id"], h.get("status"), h.get("case_name")))
        hits.sort(key=lambda x: x["id"])
    return hits[-1]


def cmd_photos(args):
    c = keis_client()
    prop = find_property(c, args.contract_no)
    if not prop:
        sys.exit("KEIS 查無案件編號 %s。改走 fallback：houseol 型錄頁「圖片打包下載」。"
                 % args.contract_no)
    print("物件：id=%s %s（狀態 %s，KEIS 記 %s 張照片）"
          % (prop["id"], prop.get("case_name"), prop.get("status"), prop.get("image_count")))
    r = c.get(API + "/property-management/%s/download-images" % prop["id"])
    if r.status_code != 200 or not r.content:
        sys.exit("下載照片失敗：HTTP %s。改走 houseol 型錄頁 fallback。" % r.status_code)
    out = Path(args.out or ("keis_photos_" + args.contract_no))
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        z.extractall(out)
    files = sorted(p for p in out.rglob("*") if p.is_file())
    total = sum(p.stat().st_size for p in files)
    print("解壓 %d 個檔到 %s（合計 %.1f MB）" % (len(files), out.resolve(), total / 1048576.0))
    for p in files:
        print("  %s  %.0f KB" % (p.name, p.stat().st_size / 1024.0))
    if prop.get("image_count") and len(names) != prop["image_count"]:
        print("[注意] zip 裡 %d 張，但 KEIS 記 %s 張，對不上——上傳前人工看一下"
              % (len(names), prop["image_count"]))
    if total > 10 * 1048576:
        print("[注意] 超過 10MB，591 上傳要分批")


def notion_lookup(contract_no):
    """從 Notion 廣告 DB 用案件編號撈永慶官網連結／案名／專員。查無或沒 token 回 None。"""
    tok = os.environ.get("KEIS_NOTION_TOKEN") or os.environ.get("NOTION_TOKEN")
    if not tok:
        return None
    h = {"Authorization": "Bearer " + tok, "Notion-Version": "2022-06-28",
         "Content-Type": "application/json"}
    r = httpx.post("https://api.notion.com/v1/databases/%s/query" % NOTION_AD_DB, headers=h,
                   json={"filter": {"property": "案件編號",
                                    "rich_text": {"equals": contract_no}},
                         "page_size": 5}, timeout=30)
    if r.status_code != 200:
        print("[注意] Notion 查詢失敗 %s：%s" % (r.status_code, r.text[:120]))
        return None
    res = r.json().get("results") or []
    if not res:
        return None

    def txt(props, name):
        p = props.get(name)
        if not p:
            return ""
        t = p["type"]
        v = p[t]
        if t in ("title", "rich_text"):
            return "".join(x["plain_text"] for x in v)
        return v or ""

    pr = res[0]["properties"]
    return {"yc_url": txt(pr, "永慶官網連結"), "title": txt(pr, "案名"),
            "member": txt(pr, "專員"), "page_id": res[0]["id"]}


def _curl(url):
    """用 curl 抓公開網頁。不用 httpx 是因為 buy.yungching.com.tw 的憑證會讓 Python 的
    OpenSSL 報 'Missing Subject Key Identifier'；Windows 的 curl 走 schannel 沒問題。
    （不要改成 httpx + verify=False 去繞，那是把憑證驗證整個關掉。）"""
    try:
        r = subprocess.run(["curl", "-sL", "-A", "Mozilla/5.0", url],
                           capture_output=True, timeout=40)
        return r.stdout.decode("utf-8", "ignore")
    except Exception as e:
        print("[注意] curl 失敗：%s" % e)
        return ""


def resolve_yc_url(prop):
    """案件編號 → 永慶官網連結。三項驗證全過才回傳；過不了回 (None, 原因)。

    驗證沿用 v3 發文線的撞號防線（docs/reference.md「永慶官網連結反查」）：
      1. productID 的數字部分要跟 KEIS contract_no 完全一致（字母前綴各家不同：YC/TC/YE）
      2. 行政區要對得上
      3. 至少一項數字佐證（總價或權狀坪數）
    2026-09-19 驗過兩筆：AG1727762→house/6914085、AA1044555→house/7525255。
    後者跟 v3 發文線自己反查、寫進 Notion 的答案一致，等於交叉驗證過一次。
    """
    digits = re.sub(r"\D", "", prop["contract_no"])
    html = _curl("https://buy.yungching.com.tw/search?kw=%s" % digits)
    ids = sorted(set(re.findall(r"/house/(\d{6,8})", html)))
    if not ids:
        return None, "永慶官網搜尋 kw=%s 沒有任何結果" % digits
    tried = []
    for hid in ids[:5]:
        page = _curl("https://buy.yungching.com.tw/house/%s" % hid)
        pid = (re.findall(r'"productID"\s*:\s*"([^"]+)"', page) or [""])[0]
        if re.sub(r"\D", "", pid) != digits:
            tried.append("%s productID=%s 數字對不上" % (hid, pid or "(無)"))
            continue
        dist = prop.get("property_address_district") or ""
        if dist and dist not in page:
            tried.append("%s 行政區 %s 對不上（撞號）" % (hid, dist))
            continue
        ok_num = []
        price, area = prop.get("case_price"), prop.get("total_area")
        if price and (("%g" % price) in page or "{:,}".format(int(price)) in page):
            ok_num.append("總價%g萬" % price)
        if area and ("%.2f" % area) in page:
            ok_num.append("坪數%.2f" % area)
        if not ok_num:
            tried.append("%s 編號行政區都對，但總價/坪數找不到佐證" % hid)
            continue
        return ("https://buy.yungching.com.tw/house/%s" % hid,
                "productID %s ＋ %s ＋ %s" % (pid, dist, "／".join(ok_num)))
    return None, "候選 %s 都沒過驗證：%s" % (ids[:5], "；".join(tried))


def find_adcase(c, yc_url):
    d = c.get(API + "/adcases/", params={"search": yc_url, "page_size": 50}).json()
    for a in d.get("adcases", []):
        if a.get("adcase_url") == yc_url:
            return a
    return None


def cmd_sync(args):
    c = keis_client()
    note = notion_lookup(args.contract_no) or {}
    yc_url = args.yc_url or note.get("yc_url")
    src = "（手動指定）" if args.yc_url else "（來自 Notion，v3 發文線反查好的）"
    if not yc_url:
        prop = find_property(c, args.contract_no)
        if not prop:
            sys.exit("KEIS 也查無案件編號 %s，停手。" % args.contract_no)
        yc_url, why = resolve_yc_url(prop)
        if not yc_url:
            sys.exit("拿不到永慶官網連結，停手——不要硬建，會留下沒登錄的孤兒廣告。\n"
                     "  Notion 廣告 DB：查無 %s\n  官網反查：%s\n"
                     "人工確認後用 --yc-url 帶進來。" % (args.contract_no, why))
        src = "（官網反查：%s）" % why
    print("永慶官網連結：%s%s" % (yc_url, src))

    existing = find_adcase(c, yc_url)
    if existing:
        aid = existing["adcase_id"]
        full = c.get(API + "/adcases/%s" % aid).json()
        before591 = full.get("adcase_url591") or ""
        plats = [p for p in (full.get("adcase_platforms") or "").split(",") if p]
        newplats = plats if PLATFORM_591 in plats else plats + [PLATFORM_591]
        print("\n既有廣告 adcase_id=%s「%s」" % (aid, full.get("adcase_title")))
        print("  adcase_url591 : %s  ->  %s" % (before591 or "(空)", args.url591))
        print("  platforms     : %s  ->  %s"
              % (full.get("adcase_platforms"), ",".join(newplats)))
        print("  （臉書連結 %s 保持不動）" % (full.get("adcase_urlfacebook") or "(空)"))
        if full.get("is_expired"):
            print("  is_expired    : True（%s 關閉）  ->  %s"
                  % ((full.get("closed_at") or "")[:10],
                     "False（重開）" if args.reopen else "True（不動，新連結會躺在已關閉的紀錄裡）"))
            if not args.reopen:
                print("[注意] 這筆廣告已經關閉。要讓新 591 廣告在 ad-tracker 生效，加 --reopen")
        if args.price:
            print("  adcase_price  : %s  ->  %s" % (full.get("adcase_price"), args.price))
        if before591 and before591 != args.url591:
            print("[注意] 這筆已經有別的 591 連結了，會被覆蓋——確定要換再 --apply")
        if not args.apply:
            print("\n== dry-run，沒有寫入。確認上面沒問題就加 --apply ==")
            return
        body = dict(full)
        body["adcase_url591"] = args.url591
        body["adcase_platforms"] = ",".join(newplats)
        if args.reopen:
            body["is_expired"] = False
        if args.price:
            body["adcase_price"] = args.price
        r = c.put(API + "/adcases/%s" % aid, json=body)
        print("PUT ->", r.status_code, r.text[:150])
        r.raise_for_status()
        after = c.get(API + "/adcases/%s" % aid).json()
        if args.reopen and after.get("is_expired"):
            print("[注意] is_expired 還是 True，重開沒生效——人工到 ad-tracker 確認")
        ok = (after.get("adcase_url591") == args.url591
              and PLATFORM_591 in (after.get("adcase_platforms") or "")
              and (after.get("adcase_urlfacebook") or "") == (full.get("adcase_urlfacebook") or ""))
        print("驗證：url591=%s platforms=%s facebook=%s"
              % (after.get("adcase_url591"), after.get("adcase_platforms"),
                 after.get("adcase_urlfacebook") or "(空)"))
        print("✓ 同步完成" if ok
              else "✗ 回讀對不上，人工到 ad-tracker 檢查 adcase_id=%s" % aid)
        return

    title = args.title or note.get("title") or ""
    member = args.member or note.get("member") or ""
    if not title:
        prop = find_property(c, args.contract_no)
        title = (prop or {}).get("case_name", "")
    print("\n查無既有廣告，會新建一筆：")
    print("  adcase_title    : %s" % title)
    print("  adcase_url      : %s" % yc_url)
    print("  adcase_url591   : %s" % args.url591)
    print("  adcase_platforms: %s" % PLATFORM_591)
    print("  adcase_member   : %s" % member)
    print("  adcase_memo     : %s" % args.contract_no)
    if not title or not member:
        sys.exit("title 或 member 是空的，KEIS 新增必填。用 --title / --member 補上再跑。")
    if not args.apply:
        print("\n== dry-run，沒有寫入。確認上面沒問題就加 --apply ==")
        return
    r = c.post(API + "/adcases/", json={
        "adcase_title": title, "adcase_url": yc_url, "adcase_member": member,
        "adcase_url591": args.url591, "adcase_platforms": PLATFORM_591,
        "adcase_memo": args.contract_no})
    print("POST ->", r.status_code, r.text[:250])
    r.raise_for_status()
    print("✓ 新增完成，到 ad-tracker 確認列表出現「新上架」標籤")


def main():
    ap = argparse.ArgumentParser(description="591-ad 的 KEIS 助手")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("photos", help="下載該案件的照片 zip 並解壓")
    p1.add_argument("contract_no")
    p1.add_argument("--out", help="解壓目的資料夾（預設 keis_photos_<編號>）")
    p1.set_defaults(func=cmd_photos)
    p2 = sub.add_parser("sync", help="把 591 廣告連結同步進 KEIS 廣告追蹤")
    p2.add_argument("contract_no")
    p2.add_argument("--url591", required=True, help="591 廣告完整網址")
    p2.add_argument("--yc-url", dest="yc_url", help="永慶官網連結（Notion 查不到時手動帶）")
    p2.add_argument("--title", help="新建時的廣告標題（Notion 查不到才需要）")
    p2.add_argument("--member", help="新建時的承辦專員（Notion 查不到才需要）")
    p2.add_argument("--reopen", action="store_true",
                    help="既有廣告已關閉時，一併把 is_expired 改回 False 重新啟用")
    p2.add_argument("--price", type=float, help="順便更新廣告總價（萬元）")
    p2.add_argument("--apply", action="store_true", help="真的寫入；不加就只是 dry-run")
    p2.set_defaults(func=cmd_sync)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
