# parser.py - 解析土地與建物謄本 PDF

import re
import pdfplumber

# ─────────────────────────────────────────
#  工具函式
# ─────────────────────────────────────────
def _read_pdf(path: str) -> str:
    lines = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                lines.append(t)
    return "\n".join(lines)

def _find(pattern, text, group=1, default=None):
    m = re.search(pattern, text)
    return m.group(group).strip() if m else default

def _to_float(s):
    try:
        return float(re.sub(r'[^\d.]', '', s))
    except Exception:
        return None

def _roc_to_ad(year, month, day):
    return int(year) + 1911, int(month), int(day)

# 國字大寫金額（舊制他項權利設定金額常用，例：肆佰捌拾萬）
_CN_D = {'零': 0, '壹': 1, '貳': 2, '參': 3, '叁': 3, '肆': 4,
         '伍': 5, '陸': 6, '柒': 7, '捌': 8, '玖': 9}
_CN_U = {'拾': 10, '佰': 100, '仟': 1000}
_CN_B = {'萬': 10 ** 4, '億': 10 ** 8}

def _cn_amount(s: str) -> int:
    """'肆佰捌拾萬' → 4800000；'壹仟肆佰壹拾萬' → 14100000"""
    total = section = num = 0
    for ch in s:
        if ch in _CN_D:
            num = _CN_D[ch]
        elif ch in _CN_U:
            section += (num if num else 1) * _CN_U[ch]
            num = 0
        elif ch in _CN_B:
            total += (section + num) * _CN_B[ch]
            section = num = 0
    return total + section + num

# ─────────────────────────────────────────
#  土地謄本解析
# ─────────────────────────────────────────
def parse_land(path: str) -> dict:
    text = _read_pdf(path)
    d = {}

    # 縣市 / 行政區 / 段小段
    m = re.search(r'([\u4e00-\u9fa5]+[市縣])\s*([\u4e00-\u9fa5]+[區鎮市鄉])\s*([\u4e00-\u9fa5段一二三四五六七八九十小]+)\s*(\d{4}-\d{4})\s*地號', text)
    if m:
        d['city']    = m.group(1)
        d['district'] = m.group(2)
        d['section'] = m.group(3)
        d['land_no'] = m.group(4)

    # 面積
    m = re.search(r'面積\s*([\d.]+)\s*平方公尺', text)
    if m:
        d['land_area'] = float(m.group(1))

    # 公告土地現值
    m = re.search(r'公告土地現值.*?(\d[\d,]+)\s*元/平方公尺', text)
    if m:
        d['land_announcement'] = _to_float(m.group(1))

    # 使用分區
    m = re.search(r'使用分區\s*(?:\(空白\)|([^\n(（]+?))\s*使用地類', text)
    if m and m.group(1):
        d['usage_zone_raw'] = m.group(1).strip()
    else:
        d['usage_zone_raw'] = None

    # 使用地類別
    m = re.search(r'使用地類\s*別\s*(?:\(空白\)|([^\n(（]+?))\s*面積', text)
    if m and m.group(1):
        d['usage_type'] = m.group(1).strip()
    else:
        d['usage_type'] = None

    # 持分（含「全部」單獨持有）
    m = re.search(r'權利範圍\s*(全部|[\d]+分之[\d]+)', text)
    if m:
        d['land_share'] = m.group(1)

    # 戶籍地（所有權人地址）
    # 格式：「地址\n<地址內容>」，若地址空白則下一行是「權利範圍」
    ownership_block = re.search(r'土地所有權部.*?相關他項權利登記', text, re.DOTALL)
    if ownership_block:
        m = re.search(r'地址\s*\n((?!權利範圍)[^\n]+)', ownership_block.group())
        if m:
            val = m.group(1).strip()
            bad_kw = ['銀行', '金庫', '保險', '股份有限公司', '財政']
            if val and any(k in val for k in ['路', '街', '巷', '號']) \
               and not any(k in val for k in bad_kw):
                d['owner_address'] = val

    # 他項權利（全部抓，合計）——格式歷代不一，全都要認得，漏認一種就少加一筆：
    # 關鍵字「擔保債權總金額」/舊制「設定金額」、「新台幣」/「新臺幣」（也可能省略）、
    # 金額用阿拉伯數字（可能帶千分位逗號）或國字大寫（肆佰捌拾萬元）
    mortgages = []
    for m in re.finditer(
            r'(?:擔保債權總金額|設定金額)[\s\S]{0,20}?(?:新[台臺]幣)?\s*'
            r'([\d,]+|[零壹貳參叁肆伍陸柒捌玖拾佰仟萬億]+)\s*元',
            text):
        raw = m.group(1)
        amt = int(raw.replace(',', '')) if raw[0].isdigit() else _cn_amount(raw)
        if amt:
            mortgages.append(amt)
    if mortgages:
        d['mortgage_items'] = [a // 10000 for a in mortgages]  # 各筆（萬元），log 核對用
        d['mortgage_total'] = sum(mortgages) // 10000  # 轉萬元

    # 銀行名稱（第一筆）
    m = re.search(r'權利人\s*([\u4e00-\u9fa5a-zA-Z0-9（）()]+(?:銀行|金庫)[^\s]*)', text)
    if m:
        d['mortgage_bank'] = m.group(1).strip()

    return d

# ─────────────────────────────────────────
#  建物謄本解析
# ─────────────────────────────────────────
def parse_building(path: str) -> dict:
    text = _read_pdf(path)
    d = {}

    # 門牌
    m = re.search(r'建物門牌\s*([^\n]+)', text)
    if m:
        d['address_raw'] = m.group(1).strip()

    # 縣市 / 行政區（從標題）
    m = re.search(r'([\u4e00-\u9fa5]+[市縣])\s*([\u4e00-\u9fa5]+[區鎮市鄉])\s*援?中?[\u4e00-\u9fa5段一二三四五六七八九十小]+\s*(\d{5}-\d{3})\s*建號', text)
    if m:
        d['city_b']    = m.group(1)
        d['district_b'] = m.group(2)
        d['building_no'] = m.group(3)

    # 完整建號（標題行）
    m = re.search(r'([\u4e00-\u9fa5段一二三四五六七八九十小]+)\s*(\d{5}-\d{3})\s*建號', text)
    if m:
        d['building_section'] = m.group(1)
        d['building_no']      = m.group(2)

    # 層數 / 所在層次
    m = re.search(r'層數\s*0*(\d+)層', text)
    if m:
        d['total_floors'] = int(m.group(1))

    # 每一層都要留（透天/多層建物一間謄本有好幾筆「層次 X 層次面積 Y」，
    # 舊版 re.search 只抓第一筆，2樓以上跟突出物全部漏掉、坪數誤算擠進同一格）
    d['floors'] = []
    for fm in re.finditer(r'層次\s*(.+?)\s*層次面積\s*([\d.]+)', text):
        d['floors'].append((fm.group(1).strip(), float(fm.group(2))))
    if d['floors']:
        d['floor_name'], d['floor_area'] = d['floors'][0]

    # 主建物總面積
    m = re.search(r'總面積\s*([\d.]+)\s*平方公尺', text)
    if m:
        d['total_area'] = float(m.group(1))

    # 主要用途
    m = re.search(r'主要用途\s*([^\n]+)', text)
    if m:
        d['usage_purpose'] = m.group(1).strip()

    # 主要建材
    m = re.search(r'主要建材\s*([^\n]+)', text)
    if m:
        d['structure'] = m.group(1).strip()

    # 建築完成日期
    m = re.search(r'建築完成日期\s*民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日', text)
    if m:
        d['complete_year']  = int(m.group(1))
        d['complete_month'] = int(m.group(2))
        d['complete_day']   = int(m.group(3))

    # 附屬建物 - 陽台 / 雨遮 / 花台（已知類型分別存欄位）；謄本上出現其他沒見過的
    # 類型（露台、夾層…）不要默默丟掉，存進 extra_attachments 讓填表時另開「其他-」欄
    d['extra_attachments'] = []
    known_purposes = ('陽台', '雨遮', '花台')
    for pm in re.finditer(r'附屬建物用途\s*(\S+?)\s*面積\s*([\d.]+)', text):
        purpose, area = pm.group(1), float(pm.group(2))
        if purpose in known_purposes:
            d[f'area_{purpose}'] = area
        else:
            d['extra_attachments'].append((purpose, area))

    # 共有部分 — 大樓常常不只一筆（大公/小公/停車場各自一個建號），每筆有
    # 自己的面積與權利範圍，而且面積行/權利範圍行的先後順序、換行位置各版
    # 謄本不固定（舊版只認一種固定行序，格式不同整段抓不到、公設直接漏算）。
    # 改成：從「共有部分」關鍵字往後逐建號切塊，塊內各自找面積與權利範圍；
    # 「含停車位」的持分屬於登記它的那個建號（車位坪 = 該建號面積 × 車位持分）。
    d['common_parts'] = []   # [{'no','area','share','parking_shares'}]
    sec = re.search(r'共\s*有\s*部\s*分', text)
    if sec:
        tail = text[sec.start():]
        stop = re.search(r'建物所有權部|土地所有權部|他項權利部', tail)
        if stop:
            tail = tail[:stop.start()]
        anchors = list(re.finditer(r'(\d{4,5}-\d{3})\s*建號', tail))
        for i, am in enumerate(anchors):
            if d.get('building_no') and am.group(1) == d['building_no']:
                continue   # 主建物建號誤入區塊，跳過
            end = anchors[i + 1].start() if i + 1 < len(anchors) else len(tail)
            block = tail[am.start():end]
            # 車位持分先抓、再從塊裡拿掉，下面找共有部分本身的權利範圍
            # 才不會抓到「含停車位…權利範圍…」那行的車位持分
            park_pat = r'含停車位[\s\S]{0,80}?權利範圍\s*(\d+分之\d+)'
            parking_shares = re.findall(park_pat, block)
            block_np = re.sub(park_pat, '', block)
            area_m  = re.search(r'([\d,]+(?:\.\d+)?)\s*平方公尺', block_np)
            share_m = re.search(r'權利範圍\s*(全部|\d+分之\d+)', block_np)
            if not area_m:
                continue
            d['common_parts'].append({
                'no': am.group(1),
                'area': float(area_m.group(1).replace(',', '')),
                'share': share_m.group(1) if share_m else None,
                'parking_shares': parking_shares,
            })
    if d['common_parts']:
        d['common_area']  = d['common_parts'][0]['area']
        d['common_share'] = d['common_parts'][0]['share']
    else:
        # 逐塊抓不到時退回舊版兩種固定格式
        m = re.search(
            r'共有部分資料.*?(\d{5}-\d{3})建號\n'
            r'共有部分\s*權利範圍\s*(\d+分之\d+)\n'
            r'([\d.]+)\s*平方公尺',
            text, re.DOTALL
        )
        if not m:
            m = re.search(
                r'共有部分[^\n]*([\d.]+)\s*平方公尺\s*權利範圍\s*(\d+分之\d+)',
                text
            )
            if m:
                d['common_area']  = float(m.group(1))
                d['common_share'] = m.group(2)
        else:
            d['common_area']  = float(m.group(3))
            d['common_share'] = m.group(2)

    # 停車位（含全形字元）
    m = re.search(r'含停車位\s*編號\s*([A-Za-zＡ-Ｚａ-ｚ０-９Ｂ\u4e00-\u9fa5A-Z0-9－\-]+)\s*權利範圍', text)
    if m:
        raw = m.group(1).strip()
        # 全形轉半形
        trans = str.maketrans('ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９－',
                               'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-')
        raw = raw.translate(trans)
        d['parking_no'] = raw
        pm = re.match(r'[Bb](\d+)', raw)
        if pm:
            d['parking_floor'] = int(pm.group(1))
            d['parking_type']  = '地下'
        else:
            d['parking_type'] = '地上'

    # 停車位持分（用來把車位坪數從共有部分拆出來）
    m = re.search(r'含停車位.*?權利範圍\s*(\d+分之\d+)', text, re.DOTALL)
    if m:
        d['parking_share'] = m.group(1)

    # 所有權人地址（建物謄本）— 只抓建物所有權部，排除空白行與銀行地址
    ownership_b = re.search(r'建物所有權部.*?相關他項權利登記', text, re.DOTALL)
    if ownership_b:
        m = re.search(r'地址\s*\n((?!權利範圍)[^\n]+)', ownership_b.group())
        if m:
            val = m.group(1).strip()
            bad_kw = ['銀行', '金庫', '保險', '股份有限公司', '財政']
            if val and any(k in val for k in ['路', '街', '巷', '號']) \
               and not any(k in val for k in bad_kw):
                d['owner_address_b'] = val

    return d

# ─────────────────────────────────────────
#  合併 + 坪數換算
# ─────────────────────────────────────────
def _share_to_float(s: str) -> float:
    """'100000分之616' → 616/100000；'全部' → 1.0"""
    m = re.match(r'(\d+)分之(\d+)', s or '')
    if m:
        return int(m.group(2)) / int(m.group(1))
    return 1.0


def is_full_ownership(share) -> bool:
    """權利範圍是否為全部（單獨持有）：'全部'、'1分之1'、'N分之N' 皆算全部。"""
    s = (share or '').strip()
    if s in ('全部', '1分之1', '全部1分之1'):
        return True
    m = re.fullmatch(r'(\d+)分之(\d+)', s)
    return bool(m and m.group(1) == m.group(2))

def _to_ping(sqm: float) -> float:
    return round(sqm / 3.305785, 2)

_ZH_NUM = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}

def _zh_floor(s):
    """'十二' → 12，'地下一' / 'B1' → None（地下層另計）"""
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if '十' in s:
        parts = s.split('十')
        tens = _ZH_NUM.get(parts[0], 1) if parts[0] else 1
        ones = _ZH_NUM.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return _ZH_NUM.get(s)

def merge(land: dict, building: dict) -> dict:
    data = {}

    # 地址（縣市 + 門牌）
    city = land.get('city') or building.get('city_b', '')
    district = land.get('district') or building.get('district_b', '')
    addr_raw = building.get('address_raw', '')
    data['address'] = f"{city}{district}{addr_raw}" if addr_raw else ''

    # 建物資訊
    data['structure']      = building.get('structure', '')
    data['usage_purpose']  = building.get('usage_purpose', '')
    data['complete_year']  = building.get('complete_year')
    data['complete_month'] = building.get('complete_month')
    data['complete_day']   = building.get('complete_day')
    data['total_floors']   = building.get('total_floors', 1)

    # 坪數
    total_area = building.get('total_area', 0)
    data['area_indoor']  = _to_ping(total_area) if total_area else None
    data['area_balcony'] = _to_ping(building['area_陽台']) if 'area_陽台' in building else None
    data['area_canopy']  = _to_ping(building['area_雨遮']) if 'area_雨遮' in building else None

    # 主建物逐層坪數（依謄本記載分別列出，不要全部擠進「室內」一格）
    data['floor_pings'] = [(label, _to_ping(area))
                            for label, area in building.get('floors', [])]

    # 附屬建物裡謄本上出現、但沒有對應固定欄位（陽台/雨遮/花台）的類型 →
    # 帶去讓填表時另開「其他-」欄，不要默默漏掉
    data['extra_attachments'] = [(label, _to_ping(area))
                                  for label, area in building.get('extra_attachments', [])]

    # 公設分攤：共有部分可能有多筆建號，各筆 面積×權利範圍 加總 = 這戶分到的
    # 全部共有坪數。車位持分包含在其登記建號的權利範圍內，車位坪 = 該建號
    # 面積 × 車位持分，單獨拆出填 F28；其他公設 = 全部共有 − 車位，填 F30
    # （F28 + F30 必須等於謄本共有部分權利範圍換算的合計）
    parts = building.get('common_parts') or []
    comm_area  = building.get('common_area')
    comm_share = building.get('common_share')
    if parts:
        full = sum(p['area'] * _share_to_float(p['share'])
                   for p in parts if p['share'])
        park = sum(p['area'] * _share_to_float(ps)
                   for p in parts for ps in p['parking_shares'])
        if not park and building.get('parking_share'):
            park = parts[0]['area'] * _share_to_float(building['parking_share'])
        data['area_common']  = _to_ping(full - park)
        data['area_parking'] = _to_ping(park) if park else None
    elif comm_area and comm_share:
        comm_full_area = comm_area * _share_to_float(comm_share)
        park_share = building.get('parking_share')
        park_area  = comm_area * _share_to_float(park_share) if park_share else 0
        data['area_common']  = _to_ping(comm_full_area - park_area)
        data['area_parking'] = _to_ping(park_area) if park_area else None
    else:
        data['area_common']  = None
        data['area_parking'] = None

    # 地坪
    if land.get('land_area') and land.get('land_share'):
        ratio = _share_to_float(land['land_share'])
        data['area_land'] = _to_ping(land['land_area'] * ratio)
        data['land_share'] = land['land_share']
    else:
        data['area_land'] = None
        data['land_share'] = None

    # 土地所有權
    data['ownership'] = '全部' if is_full_ownership(land.get('land_share')) else '持分'

    # 公告土地現值
    data['land_announcement'] = land.get('land_announcement')

    # 他項權利
    data['mortgage']        = bool(land.get('mortgage_total'))
    data['mortgage_amount'] = land.get('mortgage_total')
    data['mortgage_items']  = land.get('mortgage_items')   # 各筆明細（萬），log 核對用
    data['mortgage_bank']   = land.get('mortgage_bank')

    # 車位
    data['parking_no']    = building.get('parking_no')
    data['parking_floor'] = building.get('parking_floor')
    data['parking_type']  = building.get('parking_type')

    # 使用分區（謄本有記載才填）
    data['usage_zone_raw'] = land.get('usage_zone_raw')
    data['usage_type']     = land.get('usage_type')

    # 地號資訊（給使用分區查詢用）
    data['land_city']     = land.get('city', '')
    data['land_district'] = land.get('district', '')
    data['land_section']  = land.get('section', '')
    data['land_no']       = land.get('land_no', '')

    # 建築型態 + floor_range（所在層/總層）
    floors = data['total_floors']
    cur_floor = _zh_floor(building.get('floor_name'))
    fr = f"{cur_floor}/{floors}" if cur_floor else f"1/{floors}"
    if floors >= 6:
        data['building_type'] = '大樓'
    elif floors >= 3:
        data['building_type'] = '公寓'
    else:
        data['building_type'] = '透天'
    data['floor_range'] = fr

    # 戶籍地（優先用土地謄本所有權人地址，排除銀行/法人地址）
    def _is_valid_owner_addr(s):
        if not s:
            return False
        if not any(k in s for k in ['路', '街', '巷', '號']):
            return False
        # 排除明顯是銀行/法人地址（含「銀行」「金庫」「保險」「公司」）
        if any(k in s for k in ['銀行', '金庫', '保險', '股份有限公司', '財政部', '國稅局']):
            return False
        return True

    land_owner  = land.get('owner_address', '')
    bldg_owner  = building.get('owner_address_b', '')
    if _is_valid_owner_addr(land_owner):
        data['owner_address'] = land_owner
    elif _is_valid_owner_addr(bldg_owner):
        data['owner_address'] = bldg_owner
    else:
        data['owner_address'] = None

    # 預設欄位（使用者補充）
    for key in ['case_name', 'price', 'layout_rooms', 'layout_halls', 'layout_baths',
                'guard', 'mgmt_parking', 'parking_entrance', 'current_status',
                'road_width', 'elevator_units', 'elevator_count',
                'window_facing', 'door_facing', 'market_nearby', 'park_nearby',
                'total_units', 'mgmt_fee', 'building_name', 'builder',
                'school_junior', 'school_primary']:
        data.setdefault(key, None)

    data['selling_points'] = []
    data['agent_name']  = '薛力瑜'
    data['agent_name2'] = '周珈伊'

    return data


if __name__ == '__main__':
    import json, sys
    if len(sys.argv) == 3:
        land = parse_land(sys.argv[1])
        bldg = parse_building(sys.argv[2])
        merged = merge(land, bldg)
        print(json.dumps(merged, ensure_ascii=False, indent=2))
