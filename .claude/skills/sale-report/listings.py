# -*- coding: utf-8 -*-
"""第5頁「周遭開價」— 從貼上的房仲平台列表文字產生開價圖、彙整 PDF，並回寫 spec['listings']。

用法:  python listings.py <data.json>

spec 需要的欄位（放在 listings.src）:
    "listings": {
      "src": {
        "paste":   "周遭開價.txt",          # 貼上的列表原文（src_dir 下），一筆一塊、以「大樓,住宅」結尾
        "subject": "繁榮大學城",            # 同社區，圖上標紅
        "date":    "2026/10/15",            # 抓資料的日期（上架時間從這天往回推）
        "groups":  [[5,12],[39,4,38]],      # 選填：人工指定同一戶（原始編號），其餘自動判斷
        "split":   [[28,3]],                # 選填：自動判成同戶但其實不是
        "labels":  {"14": [40.3, 790]}      # 選填：個別標籤位置（資料座標），覆蓋自動排版
      }
    }

產出（都在 src_dir）: 周遭物件開價.png、<subject>_周遭開價彙整.pdf；spec 的 listings.title/image/rows/notes 直接改寫。
"""
import json
import os
import re
import statistics
import sys

DUR_MIN_DAYS = 60          # 刊登未滿 2 個月不標時間（使用者決定：短的標了反而誤導）
LONG_DAYS = 270            # 「刊登已超過 9 個月仍在售」那行 bullet 的門檻


# ------------------------------------------------------------------ parse
TYPE_RE = re.compile(r'^[^\d,]+,[^\d,]+$')          # 「大樓,住宅」「大樓,店面」；「1樓,2樓」有數字不算


def _num(s):
    m = re.search(r'[\d,]+(?:\.\d+)?', s)
    return float(m.group(0).replace(',', '')) if m else None


def _age_days(s):
    if '小時' in s or '分鐘' in s:
        return 0
    if s.startswith('昨天'):
        return 1
    n = int(_num(s))
    if '天前' in s:
        return n
    if '個月前' in s:
        return n * 30
    if '年前' in s:
        return n * 365
    raise ValueError(s)


def _floor(s):
    """'9樓/共12樓'→(9,12)；'12樓'→(12,None)；'1樓,2樓/共7樓' 或範圍→(None,7)"""
    tot = re.search(r'共(\d+)樓', s)
    tot = int(tot.group(1)) if tot else None
    head = s.split('/')[0]
    one = re.fullmatch(r'(\d+)樓', head.strip())
    return (int(one.group(1)) if one else None, tot)


def _floor_label(s):
    f, t = _floor(s)
    if f:
        return '%dF' % f
    nums = re.findall(r'(\d+)樓', s.split('/')[0])
    return '%s~%sF' % (nums[0], nums[-1]) if nums else ''


def parse(text):
    lines = [l.strip() for l in text.replace('\r', '').split('\n')]
    lines = [l for l in lines if l]
    blocks, cur = [], []
    for l in lines:
        cur.append(l)
        if TYPE_RE.match(l):
            blocks.append(cur)
            cur = []
    out = []
    for i, b in enumerate(blocks, 1):
        r = dict(id=i, platform=b[0], title=b[1], road='', community='', upd='',
                 price=None, unit=None, floor='', total=None, main=None, land=None,
                 age=None, layout='', kind=b[-1].split(',')[1])
        addr = b[2].split()
        r['road'] = addr[2] if len(addr) >= 3 else ''
        for l in b[3:-1]:
            if re.fullmatch(r'\d+筆', l):
                continue
            if l.endswith('更新'):
                r['upd'] = l[:-2]
            elif l.endswith('萬/坪'):
                r['unit'] = _num(l)
            elif l.endswith('萬'):
                r['price'] = _num(l)
            elif '樓' in l and re.search(r'\d樓', l):
                r['floor'] = l
            elif l.startswith('總 '):
                r['total'] = _num(l)
            elif l.startswith('主 '):
                r['main'] = _num(l)
            elif l.startswith('地 '):
                r['land'] = _num(l)
            elif re.match(r'[\d.]+年', l):
                r['age'] = _num(l)
            elif re.search(r'\d房', l):
                r['layout'] = l
            elif not r['community'] and not r['upd']:
                r['community'] = l              # 社區名在「N筆」之前，可能沒有
        out.append(r)
    return out


# ----------------------------------------------------------------- dedupe
def _same(a, b):
    """同一戶在不同平台：坪數幾乎一樣、樓層不矛盾、開價差 10% 內。"""
    if a['kind'] != b['kind'] or None in (a['total'], b['total'], a['main'], b['main']):
        return False
    if abs(a['total'] - b['total']) > 0.2 or abs(a['main'] - b['main']) > 0.15:
        return False
    fa, fb = _floor(a['floor']), _floor(b['floor'])
    if fa[0] and fb[0] and fa[0] != fb[0]:
        return False
    return abs(a['price'] - b['price']) <= 0.1 * min(a['price'], b['price'])


def dedupe(rows, groups=(), split=()):
    R = {r['id']: r for r in rows}
    parent = {i: i for i in R}

    def root(i):
        while parent[i] != i:
            i = parent[i]
        return i

    no = {frozenset(p) for p in split}
    for g in groups:
        for i in g[1:]:
            parent[root(i)] = root(g[0])
    pinned = {i for g in groups for i in g}
    ids = sorted(R)
    for x in ids:
        for y in ids:
            if x < y and not ({x, y} & pinned) and frozenset((x, y)) not in no \
                    and _same(R[x], R[y]):
                parent[root(y)] = root(x)
    clus = {}
    for i in ids:
        clus.setdefault(root(i), []).append(i)

    units = []
    for mem in clus.values():
        ms = [R[i] for i in mem]
        rep = min(ms, key=lambda r: _age_days(r['upd']))          # 最新更新那筆當代表
        lands = [r['land'] for r in ms if r['land']]
        note = []
        land = rep['land']
        if len(lands) >= 2:
            med = statistics.median(lands)
            bad = [r['id'] for r in ms if r['land'] and abs(r['land'] - med) > 0.3 * med]
            if bad:
                note.append('#%s 地坪疑似平台誤植' % '/'.join(map(str, bad)))
                land = med
        prices = sorted({r['price'] for r in ms})
        if len(prices) > 1:
            note.append('各平台開價 %s' % '／'.join('%g' % p for p in prices))
        plats = []
        for r in ms:
            if r['platform'] not in plats:
                plats.append(r['platform'])
        units.append(dict(rep=rep, mem=sorted(mem), land=land, note='；'.join(note),
                          plats='、'.join(plats),
                          days=max(_age_days(r['upd']) for r in ms)))
    units.sort(key=lambda u: (u['rep']['kind'] != '住宅', u['rep']['unit']))
    return units


def q(v, p):
    k = (len(v) - 1) * p
    f = int(k)
    c = min(f + 1, len(v) - 1)
    return v[f] + (v[c] - v[f]) * (k - f)


def dur_text(days):
    if days < DUR_MIN_DAYS:
        return None
    return '已刊登 1年以上' if days >= 365 else '已刊登 %d個月以上' % (days // 30)


def name_of(r):
    n = r['community'] or r['road'] or '未標示社區'
    return n if len(n) <= 6 else n[:6] + '…'


# ------------------------------------------------------------------ chart
def chart(units, subject, out_png, user_labels=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager as fm
    fm.fontManager.addfont('C:/Windows/Fonts/msjh.ttc')
    plt.rcParams['font.family'] = 'Microsoft JhengHei'

    res = [u for u in units if u['rep']['kind'] == '住宅']
    tp = sorted(u['rep']['price'] for u in res)
    xs = [u['rep']['total'] for u in res]
    span = max(xs) - min(xs)
    # 左右各留一欄放標籤，點不會被字蓋住
    x0, x1 = min(xs) - 0.42 * span, max(xs) + 0.42 * span
    y0, y1 = tp[0] - 30, tp[-1] + 35

    # 要標的點（最多 10 個）：同社區 → 最高/最低開價 → 刊登最久的
    pick = [u for u in res if u['rep']['community'] == subject]
    for u in (max(res, key=lambda u: u['rep']['price']), min(res, key=lambda u: u['rep']['price'])):
        if u not in pick:
            pick.append(u)
    pick += sorted([u for u in res if u not in pick and u['days'] >= DUR_MIN_DAYS],
                   key=lambda u: -u['days'])
    pick = pick[:10]

    # 自動排版：依 x 排序，左半數放左欄、右半數放右欄；欄內依點的高低等距排
    order = sorted(pick, key=lambda u: u['rep']['total'])
    half = (len(order) + 1) // 2
    pos = {}
    for side, grp in (('L', order[:half]), ('R', order[half:])):
        grp = sorted(grp, key=lambda u: -u['rep']['price'])
        n = len(grp)
        for k, u in enumerate(grp):
            fy = 0.93 - (0.86 * k / (n - 1) if n > 1 else 0.43)
            tx = x0 + 0.005 * (x1 - x0) if side == 'L' else x0 + 0.795 * (x1 - x0)
            pos[u['rep']['id']] = (tx, y0 + fy * (y1 - y0))
    for k, v in (user_labels or {}).items():
        pos[int(k)] = tuple(v)

    fig, ax = plt.subplots(figsize=(7.3, 5.43), dpi=220)
    for u in res:
        r = u['rep']
        sub = r['community'] == subject
        ax.scatter(r['total'], r['price'], s=110 if sub else 60,
                   c='#C00000' if sub else '#1F4E79', alpha=.95 if sub else .6,
                   edgecolors='white', zorder=3)
    for u in pick:
        r = u['rep']
        lab = '%s %s\n%g萬｜@%.1f' % (name_of(r), _floor_label(r['floor']), r['price'], r['unit'])
        d = dur_text(u['days'])
        if d:
            lab += '\n' + d
        ax.annotate(lab, (r['total'], r['price']), xytext=pos[r['id']], textcoords='data',
                    va='center', fontsize=9.5, linespacing=1.15,
                    color='#C00000' if r['community'] == subject else '#222',
                    arrowprops=dict(arrowstyle='-', color='#999', lw=.6))
    lo, hi = q(tp, .25), q(tp, .75)
    ax.axhspan(lo, hi, color='#FFF2CC', zorder=0)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_xlabel('總坪數（坪）', fontsize=11)
    ax.set_ylabel('開價（萬）', fontsize=11)
    ax.grid(alpha=.3)
    ax.spines[['top', 'right']].set_visible(False)
    ax.set_title('周遭待售住宅 %d 戶：坪數 × 開價（紅＝%s）\n黃色帶＝開價主流帶 %.0f～%.0f萬'
                 % (len(res), subject, lo, hi), fontsize=12, linespacing=1.4)
    fig.text(0.01, 0.005, '※ 刊登時間依各平台最早一筆更新紀錄推算，為最少時間',
             fontsize=8, color='#666')
    plt.tight_layout(rect=(0, 0.02, 1, 1))
    plt.savefig(out_png)
    plt.close(fig)


# ------------------------------------------------------------- summary pdf
def summary_pdf(rows, units, subject, date, out_pdf):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                    Spacer, PageBreak)
    pdfmetrics.registerFont(TTFont('JH', 'C:/Windows/Fonts/msjh.ttc', subfontIndex=0))
    pdfmetrics.registerFont(TTFont('JHB', 'C:/Windows/Fonts/msjhbd.ttc', subfontIndex=0))
    H1 = ParagraphStyle('h1', fontName='JHB', fontSize=16, leading=22)
    H2 = ParagraphStyle('h2', fontName='JHB', fontSize=12, leading=18, spaceBefore=6)
    P = ParagraphStyle('p', fontName='JH', fontSize=9.5, leading=14)
    C = ParagraphStyle('c', fontName='JH', fontSize=7.5, leading=9.5)

    def fmt(x, d=2):
        if x is None:
            return '—'
        v = '%.*f' % (d, x)
        return v.rstrip('0').rstrip('.') if '.' in v else v

    def style(t, hl, head):
        st = [('FONT', (0, 0), (-1, -1), 'JH', 8), ('FONT', (0, 0), (-1, 0), 'JHB', 8),
              ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(head)),
              ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
              ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#999999')),
              ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F2F2F2')])]
        st += [('BACKGROUND', (0, n), (-1, n), colors.HexColor('#FFF2CC')) for n in hl]
        t.setStyle(TableStyle(st))
        return t

    res = [u for u in units if u['rep']['kind'] == '住宅']
    tp = sorted(u['rep']['price'] for u in res)
    up = sorted(u['rep']['unit'] for u in res)
    same = [u for u in res if u['rep']['community'] == subject]
    story = [
        Paragraph('周遭待售物件開價彙整', H1),
        Paragraph('%s 周邊｜整理日 %s｜資料來源：各房仲平台刊登頁' % (subject, date), P),
        Spacer(1, 4 * mm), Paragraph('一、摘要', H2),
        Paragraph('刊登共 <b>%d</b> 筆，同一戶多平台重複刊登合併後為 <b>%d</b> 戶（住宅 %d 戶）。'
                  '以下統計只算住宅、每戶算一次。' % (len(rows), len(units), len(res)), P),
        Spacer(1, 2 * mm)]
    summ = [['項目', '最低', 'P25', '中位數', 'P75', '最高'],
            ['總價（萬）'] + [fmt(x, 0) for x in (tp[0], q(tp, .25), statistics.median(tp), q(tp, .75), tp[-1])],
            ['單價（萬/坪）'] + [fmt(x, 1) for x in (up[0], q(up, .25), statistics.median(up), q(up, .75), up[-1])]]
    story += [style(Table(summ, colWidths=[35 * mm] + [25 * mm] * 5), [], '#1F4E79'),
              Spacer(1, 3 * mm),
              Paragraph('‧ 開價主流帶（P25~P75）：總價 <b>%.0f～%.0f 萬</b>、單價 <b>%.1f～%.1f 萬/坪</b>'
                        % (q(tp, .25), q(tp, .75), q(up, .25), q(up, .75)), P)]
    if same:
        story.append(Paragraph('‧ 同社區（%s）在售 %d 戶：%s，表中以黃底標示' % (
            subject, len(same), '、'.join('%s %g 萬（@%.1f）' % (_floor_label(u['rep']['floor']),
                                         u['rep']['price'], u['rep']['unit']) for u in same)), P))
    story += [Paragraph('‧ 開價是屋主期待價，未經成交驗證；定價依據以實價登錄為主，開價只作上緣參考', P),
              PageBreak(), Paragraph('二、去重後物件一覽（%d 戶，依單價由低到高）' % len(units), H2)]

    tb = [['#', '路段', '社區', '總價\n(萬)', '單價\n(萬/坪)', '樓層', '總坪', '主建物', '地坪',
           '屋齡', '格局', '刊登平台', '最少\n刊登', '原始編號', '備註']]
    hl = []
    for n, u in enumerate(units, 1):
        r = u['rep']
        tb.append([str(n), r['road'] or '—', Paragraph(r['community'] or '—', C), fmt(r['price'], 0),
                   fmt(r['unit'], 1), _floor_label(r['floor']) or '—', fmt(r['total']), fmt(r['main']),
                   fmt(u['land']), fmt(r['age'], 1),
                   r['layout'] + ('' if r['kind'] == '住宅' else '(%s)' % r['kind']),
                   Paragraph(u['plats'], C), '%d天' % u['days'],
                   Paragraph(','.join(map(str, u['mem'])), C), Paragraph(u['note'], C)])
        if r['community'] == subject:
            hl.append(n)
    cw = [8, 18, 30, 13, 14, 17, 13, 13, 12, 11, 22, 30, 16, 20, 40]
    story += [style(Table(tb, colWidths=[w * mm for w in cw], repeatRows=1), hl, '#1F4E79'),
              PageBreak(), Paragraph('三、原始刊登清單（%d 筆，照平台原文）' % len(rows), H2)]

    tb = [['#', '平台', '標題', '路段', '社區', '更新', '總價', '單價', '樓層', '總坪', '主建物',
           '地坪', '屋齡', '格局', '類型']]
    hl = []
    for r in rows:
        tb.append([str(r['id']), r['platform'], Paragraph(r['title'], C), r['road'] or '—',
                   Paragraph(r['community'] or '—', C), r['upd'], fmt(r['price'], 0), fmt(r['unit'], 1),
                   _floor_label(r['floor']) or '—', fmt(r['total']), fmt(r['main']), fmt(r['land']),
                   fmt(r['age'], 1), r['layout'], r['kind']])
        if r['community'] == subject:
            hl.append(r['id'])
    cw = [8, 14, 46, 18, 30, 16, 12, 11, 17, 13, 13, 12, 11, 22, 11]
    story.append(style(Table(tb, colWidths=[w * mm for w in cw], repeatRows=1), hl, '#595959'))

    def foot(c, d):
        c.setFont('JH', 7)
        c.setFillColor(colors.grey)
        c.drawRightString(landscape(A4)[0] - 10 * mm, 5 * mm, '第 %d 頁' % d.page)
    SimpleDocTemplate(out_pdf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm,
                      topMargin=10 * mm, bottomMargin=10 * mm, title='周遭待售物件開價彙整'
                      ).build(story, onFirstPage=foot, onLaterPages=foot)


# --------------------------------------------------------- spec['listings']
def bands(prices):
    """把開價切成 4 段：只在不同價位之間切（同價不拆），各段戶數盡量平均，
    平手時選各段價差加總最小的切法。回傳 [[prices], ...]"""
    from itertools import combinations
    v = sorted(prices)
    n = len(v)
    cuts = [i for i in range(1, n) if v[i] != v[i - 1]]
    best = None
    for cs in combinations(cuts, min(3, len(cuts))):
        edges = (0,) + cs + (n,)
        segs = [v[a:b] for a, b in zip(edges, edges[1:])]
        key = (sum((len(g) - n / 4) ** 2 for g in segs), sum(g[-1] - g[0] for g in segs))
        if best is None or key < best[0]:
            best = (key, segs)
    return best[1] if best else [v]


def spec_section(rows, units, subject, date):
    res = [u for u in units if u['rep']['kind'] == '住宅']
    tp = sorted(u['rep']['price'] for u in res)
    tbl = []
    for b in bands(tp):
        cnt = {}
        for p in b:
            cnt[p] = cnt.get(p, 0) + 1
        det = '／'.join('%g' % p + ('×%d' % c if c > 1 else '') for p, c in sorted(cnt.items()))
        tbl.append(['%g～%g萬' % (b[0], b[-1]) if b[0] != b[-1] else '%g萬' % b[0], str(len(b)), det])
    tbl.append(['合　計', str(len(res)), '中位數約 %.0f萬' % statistics.median(tp)])
    longs = [u for u in res if u['days'] >= LONG_DAYS]
    same = [u for u in res if u['rep']['community'] == subject]
    notes = ['※ 資料來源：各房仲平台刊登（%s）' % date,
             '　%d筆去除重複刊登後為 %d戶' % (len(rows), len(res)), '',
             '‧ 周邊開價主流帶　%.0f～%.0f萬' % (q(tp, .25), q(tp, .75))]
    if longs:
        lp = sorted(u['rep']['price'] for u in longs)
        notes += ['', '‧ 刊登已超過 %d個月仍在售：%d戶' % (LONG_DAYS // 30, len(longs)),
                  '　開價 %g～%g萬' % (lp[0], lp[-1])]
    if same:
        notes += ['', '‧ 同社區在售　' + '／'.join('%s %g萬' % (_floor_label(u['rep']['floor']),
                                                           u['rep']['price']) for u in same)]
    ag = [u['rep']['age'] for u in res if u['rep']['age']]
    title = '本案周邊 屋齡%d～%d年大樓 待售物件開價分布（%d戶）' % (int(min(ag)), int(max(ag)), len(res))
    return title, tbl, notes


def main(spec_path):
    spec = json.load(open(spec_path, encoding='utf-8'))
    src_dir = spec.get('src_dir') or os.path.dirname(os.path.abspath(spec_path))
    L = spec.setdefault('listings', {})
    s = L['src']
    rows = parse(open(os.path.join(src_dir, s['paste']), encoding='utf-8').read())
    units = dedupe(rows, s.get('groups', []), s.get('split', []))
    subject, date = s['subject'], s.get('date', '')
    png = os.path.join(src_dir, '周遭物件開價.png')
    chart(units, subject, png, s.get('labels'))
    summary_pdf(rows, units, subject, date, os.path.join(src_dir, '%s_周遭開價彙整.pdf' % subject))
    title, tbl, notes = spec_section(rows, units, subject, date)
    L.update(title=L.get('title_override') or title, image='周遭物件開價.png', rows=tbl, notes=notes)
    json.dump(spec, open(spec_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    res = [u for u in units if u['rep']['kind'] == '住宅']
    with open(os.path.join(src_dir, '_listings_check.txt'), 'w', encoding='utf-8') as f:
        f.write('刊登 %d 筆 → %d 戶（住宅 %d）\n' % (len(rows), len(units), len(res)))
        for u in units:
            r = u['rep']
            f.write('%s %s %s %g萬 @%s 總%s 主%s 最少刊登%d天 成員%s %s\n' % (
                r['kind'], r['community'] or r['road'], r['floor'], r['price'], r['unit'],
                r['total'], r['main'], u['days'], u['mem'], u['note']))
        # 平台四捨五入或樓層寫法不同時自動判不出來 → 列出來人工決定要不要寫進 src.groups
        f.write('\n疑似同戶（沒合併，要合就寫進 listings.src.groups）：\n')
        for i, a in enumerate(res):
            for b in res[i + 1:]:
                ra, rb = a['rep'], b['rep']
                near = (ra['community'] and ra['community'] == rb['community']) or                        (ra['road'] and ra['road'] == rb['road'])
                if near \
                        and abs(ra['total'] - rb['total']) < 1.5 \
                        and abs(ra['price'] - rb['price']) <= 0.1 * min(ra['price'], rb['price']):
                    f.write('  %s ↔ %s　%s %g萬/%g萬 總%s/%s\n' % (
                        a['mem'], b['mem'], ra['community'] or ra['road'], ra['price'],
                        rb['price'], ra['total'], rb['total']))
    print('ok -> %s（%d 筆 → %d 戶）；去重明細看 _listings_check.txt' % (png, len(rows), len(units)))


if __name__ == '__main__':
    main(sys.argv[1])
