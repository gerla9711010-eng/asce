# confirm_wizard.py — 產出售屋表前的逐項確認 wizard
#
# 用法（在 main thread 呼叫）：
#   wiz = ConfirmWizard(parent_tk, data)
#   new_data = wiz.run()
#   if new_data is not None:           # None = 使用者取消
#       fill_excel(new_data, out_path)
#
# 規則：
#   - 每個視窗左右各一個 ◀/▶ 箭頭做上一步/下一步（第 1 步 ◀ 反灰不可按）
#   - 輸入型（數字/文字/下拉）按 Enter = ▶；欄位清空按 ▶ = 該欄不填
#   - 勾選型（Radio）：數字鍵 1/2/3… 或滑鼠點選 = 選定直接跳下一步；
#     未選按 Enter 不前進（防一路 Enter 誤跳）；真的要留空用滑鼠點 ▶
#   - ◀ 上一步不會弄丟已輸入的內容：回退時靜默存檔，數字格式打到一半也不擋
#   - 貸款三步（有無/金額/銀行）預填謄本解析值，只確認不重問；選「無」清金額銀行
#   - 訴求重點：「先不填」清空全部訴求重點欄位；「填寫完畢」存目前欄、保留其餘已填欄位
#   - 條件式：車位「無」之後不再問車位細節；機械才問上中下橫移
#   - 全部走完 → 總覽確認頁：逐欄核對，「改」跳回該步，「確認產出」才出檔

import tkinter as tk
from tkinter import ttk, messagebox


# ── 高雄捷運 / 輕軌站表（2024 改名後最新版） ──
MRT_RED = [
    '', 'R3 小港', 'R4 高雄國際機場', 'R4A 草衙', 'R5 前鎮高中', 'R6 凱旋',
    'R7 獅甲', 'R8 三多商圈', 'R9 中央公園', 'R10 美麗島', 'R11 高雄車站',
    'R12 後驛', 'R13 凹子底', 'R14 巨蛋', 'R15 生態園區', 'R16 左營(高鐵)',
    'R17 世運', 'R18 油廠國小', 'R19 楠梓科技園區', 'R20 後勁', 'R21 都會公園',
    'R22 青埔', 'R22A 橋頭糖廠', 'R23 橋頭火車站', 'R24 岡山高醫', 'RK1 岡山車站',
]
MRT_ORANGE = [
    '', 'O1 哈瑪星', 'O2 鹽埕埔', 'O4 前金', 'O5 美麗島', 'O6 信義國小',
    'O7 文化中心', 'O8 五塊厝', 'O9 苓雅運動園區', 'O10 衛武營', 'O11 鳳山西',
    'O12 鳳山', 'O13 大東', 'O14 鳳山國中', 'OT1 大寮',
]
LRT = [
    '', 'C1 籬仔內', 'C2 凱旋瑞田', 'C3 前鎮之星', 'C4 凱旋中華', 'C5 夢時代',
    'C6 經貿園區', 'C7 軟體園區', 'C8 高雄展覽館', 'C9 旅運中心', 'C10 光榮碼頭',
    'C11 真愛碼頭', 'C12 駁二大義', 'C13 駁二蓬萊', 'C14 哈瑪星',
    'C15 壽山公園', 'C16 文武聖殿', 'C17 鼓山區公所', 'C18 鼓山', 'C19 馬卡道',
    'C20 臺鐵美術館', 'C21A 內惟藝術中心', 'C21 美術館', 'C22 聯合醫院',
    'C23 龍華國小', 'C24 愛河之心', 'C25 新上國小', 'C26 大順民族',
    'C27 灣仔內(大順鼎山)', 'C28 高雄高工', 'C29 樹德家商', 'C30 科工館',
    'C31 聖功醫院(道明中學)', 'C32 凱旋公園', 'C33 衛生局', 'C34 五權國小',
    'C35 凱旋武昌', 'C36 凱旋二聖', 'C37 輕軌機廠',
]


def _build_steps(is_rental=False):
    # 租賃案金額是月租不是總價：標籤要跟著換，不然趕件時容易填成總價
    #（填進去的 key 同樣是 price → N3，數字流向不變，只有顯示文字不同）
    steps = [
        {'title': '月租' if is_rental else '總價', 'type': 'number',
         'prompt': ('月租（萬）：' if is_rental else '總價（萬）：'),
         'key': 'price', 'unit': '萬',
         # 金額防呆（軟提醒）：租賃>100萬疑似填成元、買賣<10萬疑似單位錯
         'sanity': ((lambda v: f'月租 {v} 萬？單位是「萬」，是不是填成元了？' if v > 100 else None)
                    if is_rental else
                    (lambda v: f'總價 {v} 萬？金額偏低，確定單位是「萬」嗎？' if v < 10 else None))},
    ] + _mortgage_steps() + [
        {'title': '格局 - 房', 'type': 'number',
         'prompt': '格局：幾房？', 'key': 'layout_rooms', 'unit': '房'},
        {'title': '格局 - 廳', 'type': 'number',
         'prompt': '格局：幾廳？', 'key': 'layout_halls', 'unit': '廳'},
        {'title': '格局 - 衛', 'type': 'number',
         'prompt': '格局:幾衛？', 'key': 'layout_baths', 'unit': '衛'},

        {'title': '朝向', 'type': 'two_text',
         'prompts': ['落地窗朝向', '大門朝向'],
         'keys': ['window_facing', 'door_facing'],
         'hint': '輸入「南」「北」「東」「西」等;可只填一個或全略過。'},

        {'title': '警衛', 'type': 'choice',
         'prompt': '警衛：', 'key': 'guard',
         'options': [('無', '無'), ('日班', '日'), ('24H', '24H')]},

        {'title': '管理費', 'type': 'number',
         'prompt': '管理費（元/月）：', 'key': 'mgmt_fee', 'unit': '元'},

        {'title': '電梯', 'type': 'two_number_inline',
         'prompt': '電梯：',
         'keys': ['elevator_units', 'elevator_count'],
         'suffixes': ['戶', '部']},

        {'title': '市場', 'type': 'text',
         'prompt': '市場：', 'key': 'market_nearby'},

        {'title': '公園', 'type': 'text',
         'prompt': '公園：', 'key': 'park_nearby'},

        {'title': '捷運 / 輕軌', 'type': 'three_dropdown',
         'prompt': '捷運 / 輕軌（不選則空白）：',
         'prompts': ['紅線', '橘線', '輕軌'],
         'keys': ['mrt_red', 'mrt_orange', 'lrt'],
         'options_list': [MRT_RED, MRT_ORANGE, LRT]},

        {'title': '機車停車', 'type': 'text',
         'prompt': '機車停車：', 'key': 'moto_parking'},

        {'title': '現況', 'type': 'choice',
         'prompt': '現況：', 'key': 'current_status',
         'options': [('空屋', '空屋'), ('自住', '自住'), ('租賃', '租賃')]},

        {'title': '面前道路', 'type': 'number',
         'prompt': '面前道路（米）：', 'key': 'road_width', 'unit': '米'},

        # ── 車位 wizard 子流程 ──
        {'title': '車位 - 有無', 'type': 'choice',
         'prompt': '車位：', 'key': '_parking_yn',
         'options': [('有', '有'), ('無', '無')]},

        {'title': '車位 - 位置', 'type': 'choice',
         'prompt': '車位位置：', 'key': '_parking_pos',
         'options': [('地上', '地上'), ('地下', '地下')],
         'show': lambda d: d.get('_parking_yn') == '有'},

        {'title': '車位 - 樓層', 'type': 'number',
         'prompt': '車位在第幾層？', 'key': '_parking_floor', 'unit': '層',
         'show': lambda d: d.get('_parking_yn') == '有'},

        {'title': '車位 - 編號', 'type': 'text',
         'prompt': '車位編號：', 'key': 'parking_no',
         'show': lambda d: d.get('_parking_yn') == '有'},

        {'title': '車位 - 類型', 'type': 'choice',
         'prompt': '車位類型：', 'key': '_parking_type',
         'options': [('平面式', '平面'), ('機械式', '機械')],
         'show': lambda d: d.get('_parking_yn') == '有'},

        {'title': '車位 - 機械層位', 'type': 'choice',
         'prompt': '機械車位層位：', 'key': '_parking_mech',
         'options': [('上層', '上'), ('中層', '中'),
                     ('下層', '下'), ('橫移', '橫移')],
         'show': lambda d: d.get('_parking_yn') == '有'
                          and d.get('_parking_type') == '機械'},

        {'title': '入口型式', 'type': 'choice',
         'prompt': '入口型式：', 'key': '_entrance_type',
         'options': [('坡道式', '坡道'), ('機械升降式', '升降')],
         'show': lambda d: d.get('_parking_yn') == '有'},
    ]

    # 訴求重點 5 欄（售屋表 AL30/32/34/36/38）：逐欄輸入，
    # 「先不填 / 填寫完畢」，同土地表的作法
    for i in range(BLDG_SELLING_SLOTS):
        steps.append({
            'title': f'訴求重點 {i + 1}/{BLDG_SELLING_SLOTS}',
            'type': 'selling', 'key': f'sp_{i}',
            'idx': i + 1, 'total': BLDG_SELLING_SLOTS,
        })
    return steps


BLDG_SELLING_SLOTS = 5   # 售屋表訴求重點欄數（AL30/32/.../38）
SELLING_SLOTS = 9        # 土地表訴求重點欄數（AD29/31/.../45），收集迴圈也用這個上限


def _mortgage_steps():
    """貸款（他項權利）確認三步——建物表、土地表共用。
    以前完全沒確認步驟、全靠謄本解析：解析漏抓時表格直接勾「無設定」，
    是成品最不容易發現的錯。有無/金額/銀行都預填解析值，看一眼 Enter 就過。"""
    return [
        {'title': '貸款', 'type': 'choice',
         'prompt': '貸款（他項權利）：', 'key': '_mortgage_yn',
         'options': [('有', '有'), ('無', '無')]},
        {'title': '貸款金額', 'type': 'number',
         'prompt': '貸款金額（萬）：', 'key': 'mortgage_amount', 'unit': '萬',
         'show': lambda d: d.get('_mortgage_yn') == '有'},
        {'title': '貸款銀行', 'type': 'text',
         'prompt': '貸款銀行：', 'key': 'mortgage_bank',
         'show': lambda d: d.get('_mortgage_yn') == '有'},
    ]


def _build_land_steps(is_rental=False):
    """土地表確認步驟。
    建蔽率/容積率日後由 v523 自動查詢預填（查到就帶入、可改）；查不到則手動。
    寬度/深度手動。訴求重點 9 欄逐欄輸入（見 'selling' 型）。"""
    steps = [
        {'title': '案名', 'type': 'text', 'prompt': '案名：', 'key': 'case_name'},
        {'title': '鑰匙編號', 'type': 'text',
         'prompt': '鑰匙編號（可留空）：', 'key': 'key_no'},   # 填 AL2，之前從沒人問、永遠空白
    ]
    if is_rental:
        steps += [
            {'title': '租金', 'type': 'number',
             'prompt': '租金（萬）：', 'key': 'price', 'unit': '萬',
             'sanity': lambda v: f'租金 {v} 萬？單位是「萬」，是不是填成元了？' if v > 100 else None},
            {'title': '押金', 'type': 'number',
             'prompt': '押金（萬）：', 'key': 'deposit', 'unit': '萬'},
        ]
    else:
        steps += [
            {'title': '總價', 'type': 'number',
             'prompt': '總價款（萬）：', 'key': 'price', 'unit': '萬',
             'sanity': lambda v: f'總價 {v} 萬？金額偏低，確定單位是「萬」嗎？' if v < 10 else None},
        ]
    steps += _mortgage_steps()
    steps += [
        {'title': '建蔽率', 'type': 'number',
         'prompt': '建蔽率（%）：', 'key': 'coverage_ratio', 'unit': '%'},
        {'title': '容積率', 'type': 'number',
         'prompt': '容積率（%）：', 'key': 'floor_ratio', 'unit': '%'},
        {'title': '寬度', 'type': 'number',
         'prompt': '寬度（米）：', 'key': 'land_width', 'unit': '米'},
        {'title': '深度', 'type': 'number',
         'prompt': '深度（米）：', 'key': 'land_depth', 'unit': '米'},
        {'title': '用途', 'type': 'text',
         'prompt': '用途：', 'key': 'usage_type'},
        {'title': '面前道路', 'type': 'number',
         'prompt': '面前道路（米）：', 'key': 'road_width', 'unit': '米'},

        # 地上建物：有 → 問房廳衛；無 → 跳過
        {'title': '地上建物', 'type': 'choice',
         'prompt': '是否有地上建物？', 'key': '_has_building',
         'options': [('有', '有'), ('無', '無')]},
        {'title': '格局 - 房', 'type': 'number',
         'prompt': '幾房？', 'key': 'lot_rooms', 'unit': '房',
         'show': lambda d: d.get('_has_building') == '有'},
        {'title': '格局 - 廳', 'type': 'number',
         'prompt': '幾廳？', 'key': 'lot_halls', 'unit': '廳',
         'show': lambda d: d.get('_has_building') == '有'},
        {'title': '格局 - 衛', 'type': 'number',
         'prompt': '幾衛浴？', 'key': 'lot_baths', 'unit': '衛',
         'show': lambda d: d.get('_has_building') == '有'},

        {'title': '現況', 'type': 'choice',
         'prompt': '現況：', 'key': 'current_status',
         'options': [('空地', '空地'), ('建物', '建物'), ('租賃', '租賃')]},
    ]

    # 訴求重點 9 欄：逐欄輸入，「先不填 / 填寫完畢」
    for i in range(SELLING_SLOTS):
        steps.append({
            'title': f'訴求重點 {i + 1}/{SELLING_SLOTS}',
            'type': 'selling', 'key': f'sp_{i}',
            'idx': i + 1, 'total': SELLING_SLOTS,
        })
    return steps


class ConfirmWizard:
    def __init__(self, parent, data: dict, log=print, steps=None):
        self.parent = parent
        self.data = dict(data)
        self.log = log
        self.steps = steps if steps is not None else _build_steps()
        self.idx = 0
        # 貸款有無：把解析結果（bool mortgage）預填成 choice 的值，精靈只確認不重問
        if any(s.get('key') == '_mortgage_yn' for s in self.steps):
            self.data.setdefault('_mortgage_yn',
                                 '有' if self.data.get('mortgage') else '無')

    def run(self):
        n = len(self.steps)
        while 0 <= self.idx < n:
            step = self.steps[self.idx]
            # 條件式 step:不該顯示就跳過
            if step.get('show') and not step['show'](self.data):
                self.idx += 1
                continue
            is_first = (self.idx == 0)
            # 進度計數只算「目前會顯示」的步驟：車位選「無」後被跳過的細節
            # 不佔分母，標題 (7/22) 才對得上實際要走的視窗數
            visible = [i for i, s in enumerate(self.steps)
                       if not s.get('show') or s['show'](self.data)]
            cur = visible.index(self.idx) + 1 if self.idx in visible else self.idx + 1
            dlg = StepDialog(self.parent, step, self.data, cur, len(visible),
                              is_first=is_first)
            self.parent.wait_window(dlg)
            r = dlg.result
            if r == 'next':
                self.idx += 1
            elif r == 'finish':      # 訴求重點「填寫完畢／先不填」→ 直接結束產出
                break
            elif r == 'back':
                self.idx -= 1
                while self.idx >= 0:
                    s = self.steps[self.idx]
                    if not s.get('show') or s['show'](self.data):
                        break
                    self.idx -= 1
                if self.idx < 0:
                    self.idx = 0
            else:
                self.log('🚫 已取消產出')
                return None

        # ── 總覽確認頁：產出前把所有欄位攤開看一次，錯的點「改」跳回該步 ──
        if not self._summary_confirm():
            self.log('🚫 已取消產出')
            return None

        # 貸款 choice 值回寫成 fill_excel 用的欄位；選「無」清掉金額/銀行，
        # 不然解析預填的殘值還是會被填進表
        yn = self.data.pop('_mortgage_yn', None)
        if yn is not None:
            self.data['mortgage'] = (yn == '有')
            if yn != '有':
                self.data.pop('mortgage_amount', None)
                self.data.pop('mortgage_bank', None)

        # 合併捷運/輕軌 → mrt_nearby（給 fill_excel 用）
        parts = [self.data.pop('mrt_red', None),
                 self.data.pop('mrt_orange', None),
                 self.data.pop('lrt', None)]
        parts = [p for p in parts if p]
        if parts:
            self.data['mrt_nearby'] = '、'.join(parts)

        # 訴求重點 sp_0..sp_N → selling_points（依序、去空白）
        sps = []
        for i in range(SELLING_SLOTS):
            v = self.data.pop(f'sp_{i}', None)
            if v:
                sps.append(v)
        if sps:
            self.data['selling_points'] = sps
        return self.data

    def _summary_confirm(self) -> bool:
        """總覽 → 確認產出 True；取消 False；點「改」開該步視窗改完回總覽。"""
        while True:
            dlg = SummaryDialog(self.parent, self.steps, self.data)
            self.parent.wait_window(dlg)
            r = dlg.result
            if r == 'ok':
                return True
            if isinstance(r, tuple) and r[0] == 'edit':
                step = self.steps[r[1]]
                # 編輯模式：◀ 反灰（is_first），改完任何動作都回總覽
                edlg = StepDialog(self.parent, step, self.data,
                                  r[1] + 1, len(self.steps), is_first=True)
                self.parent.wait_window(edlg)
                if edlg.result == 'cancel':
                    return False
                continue
            return False


def _summary_rows(steps, data):
    """組總覽列：[(step_index, 標題, 顯示值), ...]。
    被條件跳過的步驟不列；訴求重點只列已填的＋一格空的（想補就點那格的「改」）。"""
    rows = []
    empty_selling_added = False
    for i, s in enumerate(steps):
        if s.get('show') and not s['show'](data):
            continue
        if s['type'] == 'selling':
            v = data.get(s['key'])
            if v:
                rows.append((i, s['title'], str(v)))
            elif not empty_selling_added:
                empty_selling_added = True
                rows.append((i, s['title'], '—'))
            continue
        if 'keys' in s:
            vals = []
            if 'suffixes' in s:   # two_number_inline：12戶、2部
                for k, sfx in zip(s['keys'], s['suffixes']):
                    v = data.get(k)
                    if v not in (None, ''):
                        vals.append(f'{v}{sfx}')
            else:                 # two_text / three_dropdown
                labels = s.get('prompts') or [''] * len(s['keys'])
                for k, lbl in zip(s['keys'], labels):
                    v = data.get(k)
                    if v not in (None, ''):
                        vals.append(f'{lbl} {v}'.strip())
            rows.append((i, s['title'], '、'.join(vals) if vals else '—'))
        else:
            v = data.get(s['key'])
            unit = s.get('unit', '')
            rows.append((i, s['title'],
                         f'{v} {unit}'.strip() if v not in (None, '') else '—'))
    return rows


class SummaryDialog(tk.Toplevel):
    """產出前總覽：所有欄位一頁看完，錯的按「改」跳回該步，確認才產出。
    這是出成品前的最後一道防線——以前精靈走完直接出檔，填錯只能翻 Excel 手改。"""
    def __init__(self, parent, steps, data):
        super().__init__(parent)
        self.result = 'cancel'
        self.title('產出前總覽確認')
        self.transient(parent)
        self.grab_set()
        self.configure(padx=16, pady=12)

        ttk.Label(self, text='請核對以下內容，「—」代表該欄留空',
                  font=('Microsoft JhengHei', 12, 'bold')).pack(anchor='w', pady=(0, 8))

        rows = _summary_rows(steps, data)

        # 捲動容器：欄位多、小螢幕也放得下
        wrap = ttk.Frame(self)
        wrap.pack(fill='both', expand=True)
        canvas = tk.Canvas(wrap, width=440,
                           height=min(460, 30 * len(rows) + 8),
                           highlightthickness=0)
        sb = ttk.Scrollbar(wrap, orient='vertical', command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind('<Configure>',
                   lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.create_window((0, 0), window=inner, anchor='nw')
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side='left', fill='both', expand=True)
        sb.pack(side='right', fill='y')
        canvas.bind_all('<MouseWheel>',
                        lambda e: canvas.yview_scroll(-1 * (e.delta // 120), 'units'))

        for idx, title, val in rows:
            row = ttk.Frame(inner)
            row.pack(fill='x', pady=1)
            ttk.Label(row, text=title, width=13, foreground='#666',
                      font=('Microsoft JhengHei', 9)).pack(side='left')
            ttk.Button(row, text='改', width=3,
                       command=lambda i=idx: self._edit(i)).pack(side='right', padx=(6, 0))
            ttk.Label(row, text=val, font=('Microsoft JhengHei', 10),
                      wraplength=260, justify='left'
                      ).pack(side='left', fill='x', expand=True)

        bf = ttk.Frame(self)
        bf.pack(fill='x', pady=(10, 0))
        ttk.Button(bf, text='取消', command=self._on_cancel).pack(side='left')
        ttk.Button(bf, text='✔ 確認產出 (Enter)',
                   command=self._ok).pack(side='right')

        self.bind('<Return>', lambda e: self._ok())
        self.bind('<Escape>', lambda e: self._on_cancel())
        self.protocol('WM_DELETE_WINDOW', self._on_cancel)

        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 250
        y = parent.winfo_rooty() + 40
        self.geometry(f'+{max(0, x)}+{max(0, y)}')
        self.focus_set()

    def _close(self, result):
        self.result = result
        try:
            self.unbind_all('<MouseWheel>')   # 還原滾輪，不影響主視窗
        except Exception:
            pass
        self.destroy()

    def _edit(self, i):
        self._close(('edit', i))

    def _ok(self):
        self._close('ok')

    def _on_cancel(self):
        if messagebox.askyesno('取消', '取消整個產出流程？'):
            self._close('cancel')


class StepDialog(tk.Toplevel):
    def __init__(self, parent, step, data, cur_idx, total, is_first=False):
        super().__init__(parent)
        self.step = step
        self.data = data
        self.result = 'cancel'
        self.vars = []
        self.entries = []
        self.is_first = is_first

        self.title(f'確認 ({cur_idx}/{total}) - {step["title"]}')
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)
        self.configure(padx=12, pady=15)

        nav = ttk.Frame(self)
        nav.pack(fill='both', expand=True)

        self.btn_back = ttk.Button(nav, text='◀', width=3,
                                    command=self._on_back)
        self.btn_back.pack(side='left', fill='y', padx=(0, 12))
        if self.is_first:
            self.btn_back.state(['disabled'])

        self.btn_forward = ttk.Button(nav, text='▶', width=3,
                                       command=self._on_next)
        self.btn_forward.pack(side='right', fill='y', padx=(12, 0))

        center = ttk.Frame(nav)
        center.pack(side='left', fill='both', expand=True)

        ttk.Label(center, text=step.get('prompt', step['title']),
                  font=('Microsoft JhengHei', 12, 'bold')
                  ).pack(anchor='w', pady=(0, 8))

        self._build_body(center)
        self._build_buttons()

        self.bind('<Escape>', lambda e: self._on_cancel())
        self.bind('<Return>', lambda e: self._on_enter())

        self.protocol('WM_DELETE_WINDOW', self._on_cancel)

        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() // 2) - 220
        y = parent.winfo_rooty() + 80
        self.geometry(f'+{max(0, x)}+{max(0, y)}')

        if self.entries:
            try:
                self.entries[0].focus_set()
                if hasattr(self.entries[0], 'select_range'):
                    self.entries[0].select_range(0, 'end')
            except Exception:
                pass
        else:
            # choice 型沒有輸入框：視窗本身要拿到鍵盤焦點，Enter/數字鍵才接得到
            try:
                self.focus_set()
            except Exception:
                pass

    def _init_val(self, key):
        v = self.data.get(key)
        return '' if v is None else str(v)

    def _build_body(self, parent):
        s = self.step
        body = ttk.Frame(parent); body.pack(fill='x')
        t = s['type']

        if t == 'number':
            self._row_number(body, s['key'], s.get('unit'))

        elif t == 'text':
            self._row_text(body, s['key'], width=32)

        elif t == 'two_text':
            for prompt, key in zip(s['prompts'], s['keys']):
                self._row_text(body, key, label=prompt, width=22)
            if s.get('hint'):
                ttk.Label(parent, text=s['hint'], foreground='#888',
                          font=('Microsoft JhengHei', 9)
                          ).pack(anchor='w', pady=(4, 0))

        elif t == 'two_number_inline':
            row = ttk.Frame(body); row.pack(anchor='w', pady=4)
            for i, (key, sfx) in enumerate(zip(s['keys'], s['suffixes'])):
                v = tk.StringVar(value=self._init_val(key))
                self.vars.append((key, v, 'int'))
                e = ttk.Entry(row, textvariable=v, width=6)
                e.pack(side='left')
                self.entries.append(e)
                ttk.Label(row, text=' ' + sfx
                          + ('       ' if i == 0 else '')).pack(side='left')

        elif t == 'choice':
            v = tk.StringVar(value=self.data.get(s['key'], '') or '')
            self.vars.append((s['key'], v, 'str'))
            for i, (lbl, val) in enumerate(s['options'], 1):
                ttk.Radiobutton(body, text=f'{i}. {lbl}', variable=v, value=val,
                                command=lambda val=val: self._on_choice(val)
                                ).pack(anchor='w', pady=3)
                # 數字鍵快選：按 1/2/3… 直接選定並跳下一步，全程不用滑鼠
                if i <= 9:
                    self.bind(str(i), lambda e, val=val: self._on_choice(val))
            self._choice_hint = ttk.Label(
                parent, text='按數字鍵快選；要留空跳過請點 ▶',
                foreground='#888', font=('Microsoft JhengHei', 9))
            self._choice_hint.pack(anchor='w', pady=(4, 0))

        elif t == 'three_dropdown':
            for prompt, key, opts in zip(s['prompts'], s['keys'],
                                         s['options_list']):
                row = ttk.Frame(body)
                row.pack(anchor='w', pady=4, fill='x')
                ttk.Label(row, text=prompt, width=6).pack(side='left')
                v = tk.StringVar(value=self.data.get(key, '') or '')
                self.vars.append((key, v, 'str'))
                cb = ttk.Combobox(row, textvariable=v, values=opts,
                                  width=30, state='readonly')
                cb.pack(side='left')
                self.entries.append(cb)

        elif t == 'selling':
            self._row_text(body, s['key'], width=40)
            ttk.Label(parent,
                      text='▶／Enter＝存這欄繼續；填寫完畢＝存並產出；'
                           '先不填＝清空全部訴求重點並直接產出',
                      foreground='#888',
                      font=('Microsoft JhengHei', 9)).pack(anchor='w', pady=(4, 0))

    def _row_number(self, parent, key, unit=None):
        f = ttk.Frame(parent); f.pack(anchor='w', pady=4)
        v = tk.StringVar(value=self._init_val(key))
        self.vars.append((key, v, 'int'))
        e = ttk.Entry(f, textvariable=v, width=14); e.pack(side='left')
        self.entries.append(e)
        if unit:
            ttk.Label(f, text=' ' + unit).pack(side='left')

    def _row_text(self, parent, key, label=None, width=30):
        f = ttk.Frame(parent); f.pack(anchor='w', pady=4, fill='x')
        if label:
            ttk.Label(f, text=label, width=10).pack(side='left')
        v = tk.StringVar(value=self._init_val(key))
        self.vars.append((key, v, 'str'))
        e = ttk.Entry(f, textvariable=v, width=width); e.pack(side='left')
        self.entries.append(e)

    def _on_choice(self, val):
        self.data[self.step['key']] = val
        self.result = 'next'
        self.destroy()

    def _on_enter(self):
        """Enter 鍵專用入口：choice 未選就按 Enter → 不前進、提示一下。
        防的是一路 Enter 衝太快，把「車位有無」這種選項靜默跳過（表上有/無
        兩格都不塗，成品看不出漏）。真的要留空：滑鼠點 ▶（deliberate 動作）。"""
        s = self.step
        if s['type'] == 'choice' and self.vars:
            _, var, _ = self.vars[0]
            if not (var.get() or '').strip():
                self.bell()
                try:
                    self._choice_hint.config(
                        text='⚠ 尚未選擇：按數字鍵或點選項；要留空請點 ▶',
                        foreground='#c33')
                except Exception:
                    pass
                return
        self._on_next()

    def _on_next(self):
        if not self._commit():
            return
        # 金額防呆（軟提醒）：明顯可疑的金額問一聲，按「是」照樣過、「否」留在原視窗改
        s = self.step
        if s.get('sanity'):
            v = self.data.get(s['key'])
            if isinstance(v, (int, float)):
                msg = s['sanity'](v)
                if msg and not messagebox.askyesno('確認金額', msg):
                    return
        self.result = 'next'
        self.destroy()

    def _commit(self, silent=False) -> bool:
        for k, var, vt in self.vars:
            raw = (var.get() or '').strip()
            if not raw:
                self.data.pop(k, None)
                continue
            if vt == 'int':
                try:
                    self.data[k] = int(raw)
                except ValueError:
                    try:
                        self.data[k] = float(raw)
                    except ValueError:
                        if silent:
                            # ◀ 上一步:格式錯誤不擋回退,該欄維持回退前的原值
                            continue
                        messagebox.showerror('格式錯誤', '請輸入數字')
                        return False
            else:
                self.data[k] = raw
        return True

    def _on_finish(self):
        """訴求重點『填寫完畢』：存這欄、保留其餘已填欄位，結束產出。"""
        if not self._commit():
            return
        self.result = 'finish'
        self.destroy()

    def _on_finish_blank(self):
        """訴求重點『先不填』：清空全部訴求重點欄位，直接結束產出。"""
        total = self.step.get('total', 1)
        for i in range(total):
            self.data.pop(f'sp_{i}', None)
        self.result = 'finish'
        self.destroy()

    def _on_back(self):
        if self.is_first:
            return
        self._commit(silent=True)
        self.result = 'back'
        self.destroy()

    def _on_cancel(self):
        if messagebox.askyesno('取消', '取消整個產出流程？'):
            self.result = 'cancel'
            self.destroy()

    def _build_buttons(self):
        bf = ttk.Frame(self); bf.pack(pady=(12, 0), fill='x')

        # 訴求重點：先不填（只在第 1 欄）/ 填寫完畢 / 取消；上一步/下一步走左右箭頭
        if self.step['type'] == 'selling':
            if self.step.get('idx') == 1:
                ttk.Button(bf, text='先不填',
                           command=self._on_finish_blank).pack(side='left')
            ttk.Button(bf, text='取消',
                       command=self._on_cancel).pack(side='right')
            ttk.Button(bf, text='填寫完畢',
                       command=self._on_finish).pack(side='right', padx=4)
            return

        ttk.Button(bf, text='取消',
                   command=self._on_cancel).pack(side='right')
