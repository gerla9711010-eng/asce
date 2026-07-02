# bot_104.py — Selenium 駕駛 104woo，搜尋謄本門牌、抓社區導覽資料
#
# 流程：
#   bot = Bot104()                       # 開 Chrome 到登入頁
#   bot.open_login()
#   ...使用者手動登入...
#   data = bot.search_and_fetch(address) # 自動搜尋→點社區→開社區導覽→抓資料
#   bot.close()
#
# data = {community_name, builder, total_units, school_primary, school_junior,
#         special_zone, guard, floor_low_high}  或 None（查無）

import re
import time
import urllib.parse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


LOGIN_URL = 'https://www.104woo.com.tw/price/index.asp?aver=104&sno=1'

# 寫死的登入帳密（自動登入用）
ACCOUNT  = '0921030914'
PASSWORD = '888168'

# 高雄市土地使用分區查詢（免登入）
ZONING_URL = 'https://urban-web.kcg.gov.tw/KDA/web_page/UBA020200.jsp'

# 高雄市行政區（依 select 選項）
KH_DISTRICTS = {'新興區','三民區','前金區','苓雅區','鹽埕區','鼓山區','旗津區','前鎮區',
                '楠梓區','小港區','左營區','鳳山區','仁武區','鳥松區','梓官區','大社區',
                '岡山區','路竹區','阿蓮區','田寮區','燕巢區','橋頭區','彌陀區','永安區',
                '湖內區','大寮區','林園區','大樹區','旗山區','美濃區','六龜區','內門區',
                '杉林區','甲仙區','桃源區','茂林區','茄萣區'}


def _full_to_half(s: str) -> str:
    if not s:
        return s
    tr = str.maketrans('０１２３４５６７８９', '0123456789')
    return s.translate(tr)


def parse_address(addr: str) -> dict:
    """從謄本地址抽出 city/district/road/number"""
    addr = _full_to_half(addr or '')
    out = {'city': '', 'district': '', 'road': '', 'number': '', 'keyword': ''}
    rest = addr
    # 縣市（至多 3 字 + 市/縣）
    m = re.match(r'([一-龥]{1,3}[市縣])', rest)
    if m:
        out['city'] = m.group(1); rest = rest[m.end():]
    # 行政區（至多 3 字 + 區/鎮/市/鄉）
    m = re.match(r'([一-龥]{1,3}[區鎮市鄉])', rest)
    if m:
        out['district'] = m.group(1); rest = rest[m.end():]
    # 路名（到 路/街/大道/巷 為止）
    m = re.match(r'([一-龥一二三四五六七八九十]+?(?:路|街|大道|巷))', rest)
    if m:
        out['road'] = m.group(1); rest = rest[m.end():]
    # 號碼（允許「258之6號」「258-6號」「258號」，只取主號 258）
    m = re.match(r'(\d+)(?:\s*[之\-]\s*\d+)?\s*號', rest)
    if m:
        out['number'] = m.group(1)
    out['keyword'] = (out['road'] + out['number']) if out['road'] else (addr or '')
    return out


def _td_label_map(driver) -> dict:
    """掃所有 <td>，若文字結尾為「：」則下一個 <td> 為值"""
    cells = driver.find_elements(By.TAG_NAME, 'td')
    texts = []
    for c in cells:
        try: texts.append((c.text or '').strip())
        except Exception: texts.append('')
    m = {}
    for i, t in enumerate(texts):
        if re.search(r'[：:]\s*$', t):
            k = re.sub(r'[：:]\s*$', '', t).strip()
            if k and k not in m and i + 1 < len(texts):
                m[k] = texts[i + 1].strip()
    return m, texts


def _clean(s):  return re.sub(r'[★☆■]', '', re.sub(r'\s+', '', s or '')).strip()
def _num(s):
    m = re.search(r'\d+', s or '')
    return int(m.group()) if m else None


# 社區導覽頁的綠色標籤集合（用來判斷哪一列是「標籤列」）
_GRID_LABELS = {'建照號碼','使照號碼','發照月份','樓層','公設比','棟戶數',
                '開工日期','竣工日期','土地使用分區','構造種類','基地面積',
                '建築設計高度','起造人','設計人','監造人','承造人',
                '國小學區','國中學區'}


def _grid_pairs(driver) -> dict:
    """社區導覽頁：標籤列在上、數值列在下、同欄對位。回傳 {標籤: 值}。"""
    rows = []
    for tr in driver.find_elements(By.TAG_NAME, 'tr'):
        tds = tr.find_elements(By.XPATH, './td')
        texts = [re.sub(r'[ 　]+', ' ', (td.text or '')).strip() for td in tds]
        if any(texts):
            rows.append(texts)

    def _label_of(cell):
        cs = cell.replace(' ', '')
        for L in _GRID_LABELS:
            if cs.startswith(L):
                return L
        return None

    pairs = {}
    for i, row in enumerate(rows):
        nonempty = [c for c in row if c]
        if not nonempty:
            continue
        labels = [_label_of(c) for c in nonempty]
        # 整列非空格皆為標籤才算標籤列
        if all(labels) and i + 1 < len(rows):
            vals = rows[i + 1]
            if len(vals) == len(row):
                for k, v in zip(row, vals):
                    L = _label_of(k)
                    if L and L not in pairs:
                        pairs[L] = v.strip()
    return pairs


def _community_name(driver) -> str:
    """標題列像「左營區　新上里12鄰　花賞」，社區名是最後一段。"""
    try:
        for f in driver.find_elements(By.XPATH, "//font[@color='#C40000' or @color='#c40000']"):
            t = (f.text or '').strip()
            if t and '行情' not in t:
                return t
    except Exception:
        pass
    return ''


def _builder_clean(s: str) -> str:
    """起造人「京城建設股份有限公司\n蔡天贊」→「京城建設」。"""
    s = (s or '').split('\n')[0].strip()
    s = re.sub(r'(股份)?有限公司.*$', '', s)
    s = re.sub(r'股份.*$', '', s)
    return s.strip()


class Bot104:
    def __init__(self, log=print):
        self.log = log
        self.driver = None

    # 找不到登入框時，依序改開這些頁面重試
    LOGIN_FALLBACK_URLS = (
        'https://www.104woo.com.tw/price/login.asp?aver=104&sno=1',
        'https://www.104woo.com.tw/price/index.asp?aver=104&sno=1',
    )

    # ── 開瀏覽器到登入頁，並自動登入 ──
    def open_login(self) -> bool:
        opts = Options()
        opts.add_argument('--start-maximized')
        opts.add_experimental_option('excludeSwitches', ['enable-automation'])
        opts.add_experimental_option('useAutomationExtension', False)
        self.driver = webdriver.Chrome(options=opts)
        self.driver.get(LOGIN_URL)
        self.log('🌐 已開啟 104，正在自動登入…')
        return self.login()

    def _find_login_fields(self, timeout: int = 8):
        """回傳 (id_box, code_box)；找不到回傳 (None, None)。"""
        try:
            id_box = WebDriverWait(self.driver, timeout).until(
                EC.presence_of_element_located((By.NAME, 'id')))
            code_box = self.driver.find_element(By.NAME, 'code')
            return id_box, code_box
        except Exception:
            return None, None

    def _is_logged_in(self) -> bool:
        """頁面還有「會員登入」字樣 → 尚未登入；沒有 → 視為已登入。
        （index.asp 沒登入也有搜尋欄位，所以不能用 add1/asblo 判斷。）"""
        d = self.driver
        try:
            body = d.find_element(By.TAG_NAME, 'body').text
        except Exception:
            return False
        if not body.strip():
            return False
        return '會員登入' not in body

    def _go_to_login_form(self) -> bool:
        """點頁面上的「會員登入」連結進到登入表單（處理可能開新分頁）。"""
        d = self.driver
        before = set(d.window_handles)
        for xp in ("//a[contains(normalize-space(.),'會員登入')]",
                   "//a[contains(normalize-space(.),'登入')]",
                   "//a[contains(@href,'login')]",
                   "//img[contains(@src,'login')]/ancestor::a[1]"):
            els = d.find_elements(By.XPATH, xp)
            if not els:
                continue
            try:
                d.execute_script("arguments[0].click();", els[0])
                time.sleep(1.5)
                new = set(d.window_handles) - before
                if new:                       # 開了新分頁 → 切過去
                    d.switch_to.window(new.pop())
                    time.sleep(0.5)
                return True
            except Exception:
                continue
        return False

    def _dump_html(self, filename: str, note: str = ''):
        """把當下頁面 HTML 存到 output/，方便回傳除錯。"""
        try:
            import os as _os
            out_dir = _os.path.join(_os.path.dirname(__file__), 'output')
            _os.makedirs(out_dir, exist_ok=True)
            path = _os.path.join(out_dir, filename)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(f'<!-- URL: {self.driver.current_url} -->\n')
                if note:
                    f.write(f'<!-- NOTE: {note} -->\n')
                f.write(self.driver.page_source)
            self.log(f'   已存頁面 HTML：{path}（回傳給我可診斷）')
        except Exception as e:
            self.log(f'   （存 HTML 失敗：{e}）')

    # ── 自動填帳密並送出 ──
    def login(self, account: str = ACCOUNT, password: str = PASSWORD) -> bool:
        """自動登入 104。成功（或本來就已登入）回傳 True，否則 False。"""
        d = self.driver
        id_box, code_box = self._find_login_fields(timeout=6)

        # 目前頁沒有登入框 → 若已登入就結束；否則點「會員登入」進表單
        if not id_box:
            if self._is_logged_in():
                self.log('🔑 104 已在登入狀態（免登入）')
                return True
            if self._go_to_login_form():
                self.log('  已點「會員登入」，尋找登入表單…')
                id_box, code_box = self._find_login_fields(timeout=8)

        # 還是沒有 → 依序改開已知登入頁重試
        tried = 0
        while not id_box and tried < len(self.LOGIN_FALLBACK_URLS):
            url = self.LOGIN_FALLBACK_URLS[tried]; tried += 1
            self.log(f'  登入框未出現，改開 {url.rsplit("/", 1)[-1]} 再試…')
            d.get(url); time.sleep(1.5)
            id_box, code_box = self._find_login_fields(timeout=8)

        if not id_box:
            if self._is_logged_in():
                self.log('🔑 104 已在登入狀態（免登入）')
                return True
            self.log('⚠ 找不到登入欄位，也非已登入狀態 → 請在瀏覽器手動登入')
            self._dump_html('104_login_debug.html', '找不到 id/code 登入欄位')
            return False

        # 填帳密
        try:
            id_box.clear();   id_box.send_keys(account)
            code_box.clear(); code_box.send_keys(password)
        except Exception as e:
            self.log(f'⚠ 填入帳密失敗：{e}')
            return False

        # 送出：登入鈕是 <input type="image" src="login1.gif">，實體點擊偶被遮擋 → JS click
        try:
            btn = None
            for xp in ("//input[@type='image']",
                       "//input[@type='submit']",
                       "//form[@name='form1']//input[@type='image']"):
                els = d.find_elements(By.XPATH, xp)
                if els:
                    btn = els[0]; break
            if btn:
                d.execute_script("arguments[0].click();", btn)
            else:
                code_box.submit()
        except Exception as e:
            self.log(f'⚠ 送出登入失敗：{e}')
            return False

        time.sleep(2.5)
        # 確認真的登入了（頁面不再有「會員登入」）
        if self._is_logged_in():
            self.log(f'🔑 已自動登入 104（帳號 {account}）')
            return True
        self.log('⚠ 送出後仍未登入，帳密可能有誤（可在瀏覽器手動登入）')
        self._dump_html('104_login_debug.html', '送出後仍停在登入頁')
        return False

    # ── 主流程：搜尋 → 找社區 → 抓社區導覽 ──
    def search_and_fetch(self, address: str) -> dict | None:
        d = self.driver
        info = parse_address(address)
        self.log(f'🔍 解析地址：{info["city"]} {info["district"]} {info["road"]} {info["number"]}號')

        if info['district'] not in KH_DISTRICTS:
            self.log('⚠ 非高雄市行政區，跳過 104 查詢')
            return None

        # 確保在搜尋頁
        if 'index.asp' not in d.current_url and 'price' not in d.current_url:
            d.get(LOGIN_URL)
            time.sleep(1)

        wait = WebDriverWait(d, 15)

        # 選行政區
        try:
            sel = wait.until(EC.presence_of_element_located((By.NAME, 'asblo')))
            Select(sel).select_by_visible_text(info['district'])
        except Exception as e:
            self.log(f'⚠ 設定行政區失敗：{e}（不中斷，繼續嘗試搜尋）')

        # 填地址關鍵字（路名 + 號）
        try:
            inp = d.find_element(By.NAME, 'add1')
            inp.clear()
            inp.send_keys(info['keyword'])
        except Exception as e:
            self.log(f'⚠ 填地址欄失敗：{e}')
            return None

        # 按搜尋：實體點擊常被浮動元素攔截 → 改用 JS click（繞過遮擋）
        try:
            btn = None
            for xp in ("//input[@type='button' and @value='搜尋']",
                       "//input[@value='搜尋']",
                       "//input[@type='submit' and @value='搜尋']",
                       "//a[normalize-space(text())='搜尋']",
                       "//*[@onclick and contains(@onclick,'submit')]"):
                els = d.find_elements(By.XPATH, xp)
                if els:
                    btn = els[0]; break
            if not btn:
                self.log('⚠ 找不到搜尋按鈕')
                return None
            d.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
            time.sleep(0.3)
            d.execute_script("arguments[0].click();", btn)
        except Exception as e:
            self.log(f'⚠ 點搜尋失敗：{e}')
            return None

        self.log(f'⏳ 搜尋「{info["keyword"]}」中…')
        time.sleep(4)

        # 結果頁是表格：每一列 td 含「辛亥路250號…」純文字，
        # 同列另一格有「社區名」的 <a>（href 帶 lan_no），還有「明細」的 <a>。
        # 我們要的是社區名那顆，不是明細。
        target_lan_no = None
        target_reqno = None
        target_check104 = None
        community_name = ''
        road = info['road']; num = info['number']

        def _norm(s):
            return _full_to_half(s or '').replace(' ', '').replace('　', '')

        # 找含路名+號的 td
        hit_tds = []
        for td in d.find_elements(By.TAG_NAME, 'td'):
            try:
                t = _norm(td.text)
                if road and road in t and (not num or num in t):
                    hit_tds.append(td)
            except Exception:
                continue

        self.log(f'  命中含「{road}{num}」的儲存格 {len(hit_tds)} 筆')

        # 從每個命中 td 往上找 tr → tr 內找社區連結
        for td in hit_tds:
            try:
                tr = td.find_element(By.XPATH, './ancestor::tr[1]')
            except Exception:
                continue
            for a in tr.find_elements(By.TAG_NAME, 'a'):
                try:
                    href = a.get_attribute('href') or ''
                    onclick = a.get_attribute('onclick') or ''
                    text = (a.text or '').strip()
                    src = href + ' ' + onclick
                    # 跳過「明細」、空文字、含「明細」字樣的
                    if not text or '明細' in text or '漲' in text:
                        continue
                    m_lan = re.search(r'lan_no=([A-Za-z0-9]+)', src)
                    if m_lan:
                        target_lan_no = m_lan.group(1)
                        mr = re.search(r'reqno=([A-Za-z0-9]+)', src)
                        mc = re.search(r'check104=([A-Za-z0-9]+)', src)
                        if mr: target_reqno = mr.group(1)
                        if mc: target_check104 = mc.group(1)
                        community_name = text
                        self.log(f'  ✓ 命中社區：{text}（lan_no={target_lan_no}）')
                        break
                except Exception:
                    continue
            if target_lan_no:
                break

        if not target_lan_no:
            try:
                import os as _os
                dump = _os.path.join(_os.path.dirname(__file__), 'output', '104_debug.html')
                with open(dump, 'w', encoding='utf-8') as f:
                    f.write('<!-- URL: ' + d.current_url + ' -->\n')
                    f.write(d.page_source)
                self.log(f'⚠ 結果頁找不到社區連結。已存 HTML：{dump}')
            except Exception as e:
                self.log(f'⚠ 結果頁找不到社區連結（dump 失敗：{e}）')
            return None

        # 直接組社區導覽 URL
        url = ('https://www.104woo.com.tw/price/index2_ok9a.asp?'
               f'akind2=大樓&reqno={target_reqno}&lan_no={target_lan_no}'
               f'&envtype0=同棟成交&sblo={info["district"]}&aver=104&sno=1'
               + (f'&check104={target_check104}' if target_check104 else ''))
        self.log(f'📑 開啟社區導覽：lan_no={target_lan_no}')
        d.get(url)
        time.sleep(2)

        # 抓欄位：標籤列→數值列配對
        m = _grid_pairs(d)
        name = _community_name(d) or community_name
        if not m and not name:
            try:
                import os as _os
                dump = _os.path.join(_os.path.dirname(__file__), 'output', '104_community_debug.html')
                with open(dump, 'w', encoding='utf-8') as f:
                    f.write('<!-- URL: ' + d.current_url + ' -->\n')
                    f.write(d.page_source)
                self.log(f'⚠ 社區導覽頁解析失敗，已存 HTML：{dump}')
            except Exception:
                self.log('⚠ 社區導覽頁解析失敗')
            return None

        # 樓層：「地上24樓\n地下4樓」→ B4/24
        floor = ''
        fl = m.get('樓層', '')
        up = re.search(r'地上\s*(\d+)', fl)
        dn = re.search(r'地下\s*(\d+)', fl)
        if up:
            floor = ('B' + dn.group(1) if dn else '1') + '/' + up.group(1)

        # 棟戶數：「1棟共209戶」→ 209
        units = None
        mu = re.search(r'(\d+)\s*戶', m.get('棟戶數', ''))
        if mu:
            units = int(mu.group(1))

        # 警衛：此頁無管理方式欄，掃全頁文字當備援
        guard = ''
        try:
            body_text = d.find_element(By.TAG_NAME, 'body').text
            mg = re.search(r'管理方式[：:]\s*([^。\n]+)', body_text)
            if mg and re.search(r'24|飯店|全天', mg.group(1)):
                guard = '24H'
        except Exception:
            pass

        data = {
            'source': '104woo',
            'community_name': _clean(name),
            'builder':        _builder_clean(m.get('起造人', '')),
            'total_units':    units,
            'school_primary': _clean(m.get('國小學區', '')),
            'school_junior':  _clean(m.get('國中學區', '')),
            'special_zone':   _clean(m.get('土地使用分區', '')),
            'guard':          guard,
            'floor_low_high': floor,
        }
        self.log(f'✓ 抓到社區：{data["community_name"]}｜建商 {data["builder"]}｜'
                 f'{data["total_units"]}戶｜樓層 {data["floor_low_high"]}｜'
                 f'分區 {data["special_zone"]}｜國小 {data["school_primary"]}')
        return data

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass


def _normalize_land_no(land_no: str) -> str:
    """謄本地號常為「0123-0000」→ 官網要「123」；「0123-0001」→「123-1」。"""
    s = _full_to_half((land_no or '').strip())
    s = re.sub(r'[^\d\-]', '', s)
    if not s:
        return ''
    parts = s.split('-')
    try:
        main = str(int(parts[0]))
    except ValueError:
        return s
    if len(parts) >= 2:
        try:
            sub = int(parts[1])
        except ValueError:
            sub = 0
        if sub:
            return f'{main}-{sub}'
    return main


def _match_option(target: str, options: list) -> str | None:
    """在下拉選項中找最符合 target 的（用於地段）。回傳該選項可見文字。"""
    def norm(s):
        return re.sub(r'\s+', '', _full_to_half(s or ''))
    t = norm(target)
    if not t:
        return None
    texts = [(o, norm(o)) for o in options if norm(o)]
    for o, n in texts:                       # 完全相等
        if n == t:
            return o
    for o, n in texts:                       # 選項開頭=地段（含小段）
        if n.startswith(t) or t.startswith(n):
            return o
    for o, n in texts:                       # 互相包含
        if t in n or n in t:
            return o
    return None


def fetch_zoning(district: str, section: str, land_no: str,
                 driver=None, log=print) -> dict | None:
    """查高雄市土地使用分區。
    回傳 {'usage_zone': '住宅區/商業區/工業區/其他', 'special_zone': '原始分區文字'} 或 None。
    driver 有給就開新分頁查（查完關分頁、切回原視窗）；沒給就自己開無頭 Chrome。
    """
    district = (district or '').strip()
    section  = (section or '').strip()
    ln = _normalize_land_no(land_no)
    if not (district and section and ln):
        log(f'⚠ 使用分區查詢缺資料（區={district} 段={section} 號={ln}），跳過')
        return None

    own_driver = False
    original = None
    d = driver
    try:
        if d is None:
            opts = Options()
            opts.add_argument('--headless=new')
            opts.add_argument('--window-size=1280,900')
            d = webdriver.Chrome(options=opts)
            own_driver = True
        else:
            original = d.current_window_handle
            d.switch_to.new_window('tab')

        d.get(ZONING_URL)
        wait = WebDriverWait(d, 15)

        # 行政區
        sel_dist = Select(wait.until(EC.presence_of_element_located((By.ID, 'DIST'))))
        try:
            sel_dist.select_by_visible_text(district)
        except Exception:
            opt = _match_option(district, [o.text for o in sel_dist.options])
            if not opt:
                log(f'⚠ 使用分區：找不到行政區「{district}」，跳過')
                return None
            sel_dist.select_by_visible_text(opt)

        # 地段（AJAX 動態載入，等選項 > 1）
        land_el = d.find_element(By.ID, 'LAND')
        try:
            wait.until(lambda drv: len(Select(land_el).options) > 1)
        except Exception:
            log('⚠ 使用分區：地段未載入（AJAX 逾時），跳過')
            return None
        sel_land = Select(land_el)
        land_texts = [o.text for o in sel_land.options]
        opt = _match_option(section, land_texts)
        if not opt:
            log(f'⚠ 使用分區：地段「{section}」對不到下拉選項。可選：{land_texts[:30]}')
            return None
        sel_land.select_by_visible_text(opt)
        log(f'  使用分區查詢：{district} {opt} {ln}')

        # 地號
        num = d.find_element(By.ID, 'NUMBER')
        num.clear(); num.send_keys(ln)

        # 查詢（searchBtn 是 <a>，用 JS click）
        btn = d.find_element(By.ID, 'searchBtn')
        d.execute_script("arguments[0].click();", btn)

        # 等結果出現
        try:
            wait.until(lambda drv: any(
                (drv.find_element(By.ID, i).text or '').strip()
                for i in ('resultData02', 'resultData03')))
        except Exception:
            pass
        time.sleep(1.0)

        chunks = []
        for i in ('resultData', 'resultData02', 'resultData2', 'resultData03'):
            try:
                chunks.append((d.find_element(By.ID, i).text or '').strip())
            except Exception:
                pass
        text = '\n'.join(c for c in chunks if c)
        if not text:
            try:
                text = d.find_element(By.ID, 'UBA020200').text or ''
            except Exception:
                text = ''
        text = _full_to_half(text)

        result = _parse_zoning_text(text)
        if not result:
            try:
                import os as _os
                out_dir = _os.path.join(_os.path.dirname(__file__), 'output')
                _os.makedirs(out_dir, exist_ok=True)
                dump = _os.path.join(out_dir, 'zoning_debug.html')
                with open(dump, 'w', encoding='utf-8') as f:
                    f.write('<!-- URL: ' + d.current_url + ' -->\n')
                    f.write('<!-- TEXT: ' + text.replace('-->', '') + ' -->\n')
                    f.write(d.page_source)
                log(f'⚠ 使用分區：解析不到結果，已存 HTML：{dump}（回傳給我可校正）')
            except Exception:
                log('⚠ 使用分區：解析不到結果')
            return None

        log(f'✓ 使用分區：{result.get("special_zone") or result.get("usage_zone")}')
        return result

    except Exception as e:
        log(f'⚠ 使用分區查詢失敗：{e}')
        return None
    finally:
        try:
            if own_driver:
                d.quit()
            elif d is not None and original is not None:
                d.close()
                d.switch_to.window(original)
        except Exception:
            pass


def _parse_zoning_text(text: str) -> dict | None:
    """從查詢結果文字抽出使用分區。"""
    if not text:
        return None
    t = re.sub(r'\s+', '', text)
    # 細項：抓「使用分區：XXX」或「第○種住宅區」等完整詞
    special = ''
    m = re.search(r'使用分區[:：]?\s*([^\s。，,；;]+(?:區|用地|保護區|農業區))', t)
    if m:
        special = m.group(1)
    if not special:
        m = re.search(r'(第[一二三四五六七八九十]+種[住商工][^\s。，,；;]*區)', t)
        if m:
            special = m.group(1)
    if not special:
        m = re.search(r'([一-鿿]{0,8}(?:住宅區|商業區|工業區|農業區|保護區|風景區|行政區|文教區|機關用地|公園用地|學校用地|道路用地|其他[^\s。，,；;]*用地))', t)
        if m:
            special = m.group(1)

    # 大類：給 fill_excel 勾選用
    usage = ''
    src = special or t
    if '商業區' in src:
        usage = '商業區'
    elif '工業區' in src:
        usage = '工業區'
    elif '住宅區' in src:
        usage = '住宅區'

    if not (special or usage):
        return None
    return {'usage_zone': usage, 'special_zone': special}
