"""把 expl_src/cN.py 的 (題號, 法條引用, 白話) 轉成 expl/cN.json
法條文字一律從 law/*.txt（全國法規資料庫原文）逐字貼，不手打。
引用格式： "法規代號 條號"  或  "法規代號 條號#行號,行號"（行號＝條文內第幾行，1 起算）
條號可寫 "38-1"。"""
import json, re, sys, importlib

LAWS = {  # 代號: (顯示名稱, 檔案)
    '租賃條例': ('租賃住宅市場發展及管理條例', 'law/租賃條例.txt'),
    '租賃細則': ('租賃住宅市場發展及管理條例施行細則', 'law/租賃細則.txt'),
    '租賃資訊辦法': ('租賃住宅服務業資訊提供辦法', 'law/租賃資訊辦法.txt'),
    '民法': ('民法', 'law/民法.txt'),
    '所得稅法': ('所得稅法', 'law/所得稅法.txt'),
    '土地稅法': ('土地稅法', 'law/土地稅法.txt'),
    '土地稅法細則': ('土地稅法施行細則', 'law/土地稅法細則.txt'),
    '房屋稅條例': ('房屋稅條例', 'law/房屋稅條例.txt'),
    '土地法': ('土地法', 'law/土地法.txt'),
    '個資法': ('個人資料保護法', 'law/個資法.txt'),
    '經紀業條例': ('不動產經紀業管理條例', 'law/不動產經紀業管理條例.txt'),
    '設計施工編': ('建築技術規則建築設計施工編', 'law/建築技術規則設計施工編.txt'),
    '設備編': ('建築技術規則建築設備編', 'law/建築技術規則設備編.txt'),
    '室內裝修辦法': ('建築物室內裝修管理辦法', 'law/室內裝修辦法.txt'),
    '昇降設備辦法': ('建築物昇降設備設置及檢查管理辦法', 'law/昇降設備辦法.txt'),
    '公安申報辦法': ('建築物公共安全檢查簽證及申報辦法', 'law/公安申報辦法.txt'),
    '地籍測量': ('地籍測量實施規則', 'law/地籍測量實施規則.txt'),
    '消防設置標準': ('各類場所消防安全設備設置標準', 'law/消防設置標準.txt'),
    '燃氣熱水器標準': ('燃氣熱水器及其配管安裝標準', 'law/燃氣熱水器標準.txt'),
    '消防法': ('消防法', 'law/消防法.txt'),
    '建築法': ('建築法', 'law/建築法.txt'),
    '強制執行法': ('強制執行法', 'law/強制執行法.txt'),
    '調解條例': ('鄉鎮市調解條例', 'law/調解條例.txt'),
    '租賃應記載': ('住宅租賃定型化契約應記載事項', 'law/租賃應記載.txt', '點'),
    '租賃不得': ('住宅租賃定型化契約不得記載事項', 'law/租賃不得記載.txt', '點'),
    '轉租應記載': ('住宅轉租定型化契約應記載事項', 'law/轉租應記載.txt', '點'),
    '轉租不得': ('住宅轉租定型化契約不得記載事項', 'law/轉租不得記載.txt', '點'),
    '包租應約定': ('住宅包租契約應約定事項', 'law/包租應約定.txt', '點'),
    '包租不得': ('住宅包租契約不得約定事項', 'law/包租不得約定.txt', '點'),
    '委託應記載': ('租賃住宅委託管理定型化契約應記載事項', 'law/委託應記載.txt', '點'),
    '委託不得': ('租賃住宅委託管理定型化契約不得記載事項', 'law/委託不得記載.txt', '點'),
    '公寓條例': ('公寓大廈管理條例', 'law/公寓條例.txt'),
    '公寓細則': ('公寓大廈管理條例施行細則', 'law/公寓細則.txt'),
    '都市計畫法': ('都市計畫法', 'law/都市計畫法.txt'),
    '非都管制規則': ('非都市土地使用管制規則', 'law/非都市土地使用管制規則.txt'),
    '消保法': ('消費者保護法', 'law/消保法.txt'),
    '民事訴訟法': ('民事訴訟法', 'law/民事訴訟法.txt'),
    '消保法細則': ('消費者保護法施行細則', 'law/消保法細則.txt'),
    '公證法': ('公證法', 'law/公證法.txt'),
    '平均地權條例': ('平均地權條例', 'law/平均地權條例.txt'),
    '所得稅法細則': ('所得稅法施行細則', 'law/所得稅法細則.txt'),
    '扣繳率標準': ('各類所得扣繳率標準', 'law/扣繳率標準.txt'),
    '二代健保辦法': ('全民健康保險扣取及繳納補充保險費辦法', 'law/二代健保辦法.txt'),
}
try:
    from laws_extra import LAWS as _X
    LAWS.update(_X)
except ImportError:
    pass

_cache = {}
def arts(code):
    if code not in _cache:
        d = {}
        for blk in open(LAWS[code][1], encoding='utf-8').read().split('\n\n'):
            ls = blk.strip().split('\n')
            if ls and ls[0].startswith('第'):
                d[re.sub(r'\s', '', ls[0])] = ls[1:]
        _cache[code] = d
    return _cache[code]

def cite(ref):
    if ref.startswith('='):  # 手寫出處（原文未收錄時才用，白話註解要註明）
        return ref[1:]
    m = re.fullmatch(r'(\S+) ([\d\-]+)(?:#([\d,]+))?', ref.strip())
    assert m, f'引用格式錯: {ref}'
    code, no, sel = m.groups()
    lines = arts(code).get(f'第{no}條')
    assert lines, f'找不到 {code} 第{no}條'
    if sel:
        idx = [int(x) for x in sel.split(',')]
        assert all(1 <= i <= len(lines) for i in idx), f'行號超出 {ref}（共{len(lines)}行）'
        lines = [lines[i - 1] for i in idx]
    unit = LAWS[code][2] if len(LAWS[code]) > 2 else '條'
    return f'【{LAWS[code][0]} 第{no}{unit}】\n' + '\n'.join(lines)

MARK = re.compile(r'^(（[一二三四五六七八九十]+）|\([一二三四五六七八九十]+\)|[一二三四五六七八九十]+、|\d+[\.、])')


def _bg(t):
    t = re.sub(r'[\s，。、：；（）()「」『』＿_\-\d]', '', t)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _score(line, ctx):
    b = _bg(line)
    return len(b & ctx) / (len(b) ** 0.5 + 1)


def _best_sentence(line, ctx):
    parts = [p for p in re.split(r'(?<=[。；])', line) if p.strip()]
    if len(parts) <= 1:
        return line
    best = max(parts, key=lambda p: _score(p, ctx))
    return ('…' if best != parts[0] else '') + best.strip() + ('…' if best != parts[-1] else '')


def key_cite(ref, ctx):
    """回傳 (標題, 只留最關鍵一行, 分數)"""
    m = re.fullmatch(r'(\S+) ([\d\-]+)(?:#([\d,]+))?', ref.strip())
    code, no, sel = m.groups()
    lines = arts(code).get(f'第{no}條')
    idx = [int(x) for x in sel.split(',')] if sel else list(range(1, len(lines) + 1))
    sl = [lines[i - 1] for i in idx]
    unit = LAWS[code][2] if len(LAWS[code]) > 2 else '條'
    head = f'【{LAWS[code][0]} 第{no}{unit}】'
    cand = [l for l in sl if not (re.search(r'[：:]$', l) and len(l) < 70)] or sl
    best = max(cand, key=lambda l: _score(l, ctx))
    if len(best) > 110:
        best = _best_sentence(best, ctx)
    if MARK.match(best):
        intro = next((l for l in sl if not MARK.match(l)), None)
        if intro and intro != best:
            best = (intro[:30] + ('…' if len(intro) > 30 else '')) + '\n' + best
    return head, best, _score(best, ctx)


try:
    from expl_src.fix import FIX  # 交叉審核後的逐題修正（最後套用，優先權最高）
except ModuleNotFoundError:
    FIX = {}


def build(chap):
    mod = importlib.import_module(f'expl_src.c{chap}')
    try:
        O = importlib.import_module(f'expl_src.opt{chap}').O
    except ModuleNotFoundError:
        O = {}
    try:
        T = importlib.import_module(f'expl_src.talk{chap}').T
    except ModuleNotFoundError:
        T = {}
    bank = {q['id']: q for q in json.load(open('data/bank.json', encoding='utf-8'))['qs']}
    out = {}
    for qid, refs, note, *rest in mod.E:
        q = bank[qid]
        ctx = _bg(q['q'] + q['o'][q['a']] + note)
        full = '\n\n'.join(cite(r) for r in refs)
        auto = [r for r in refs if not r.startswith('=')]
        manual = [r[1:] for r in refs if r.startswith('=')]
        if auto:
            ks = sorted((key_cite(r, ctx) for r in auto), key=lambda x: -x[2])[:2]
            law = '\n\n'.join(h + '\n' + b for h, b, _ in ks)
        else:
            law = '\n\n'.join(manual)
        out[qid] = {'law': law, 'note': note.strip()}
        if full != law:
            out[qid]['full'] = full
        if rest:
            out[qid]['flag'] = rest[0].strip()
        if qid in T:
            tn, to = T[qid]
            out[qid]['note'] = tn.strip()
            O = dict(O)
            if to is not None:
                O[qid] = to
        fx = FIX.get(qid, {})
        if 'note' in fx: out[qid]['note'] = fx['note'].strip()
        if 'flag' in fx:
            if fx['flag']: out[qid]['flag'] = fx['flag'].strip()
            else: out[qid].pop('flag', None)
        if 'law' in fx: out[qid]['law'] = fx['law'].strip()
        if 'opts' in fx:
            O = dict(O); O[qid] = fx['opts']
        if qid in O:
            wrong = [i for i in range(4) if i != q['a']]
            got = {}
            for part in O[qid].split('|'):
                k, v = part.split(':', 1)
                got['ABCD'.index(k.strip())] = v.strip()
            assert set(got) == set(wrong), f'{qid} 選項說明字母不對：需要 {["ABCD"[i] for i in wrong]}，寫了 {["ABCD"[i] for i in got]}'
            out[qid]['opts'] = [got.get(i, '') for i in range(4)]
    json.dump(out, open(f'expl/c{chap}.json', 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'c{chap}: {len(out)} 題，選項說明 {sum(1 for v in out.values() if "opts" in v)} 題')


if __name__ == '__main__':
    for c in sys.argv[1:]:
        build(c)
