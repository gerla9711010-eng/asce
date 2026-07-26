# zone_query.py - 高雄市土地使用分區自動查詢

import time
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

URL = 'https://urban-web.kcg.gov.tw/KDA/web_page/UBA020200.jsp'

# 行政區對應下拉選單文字
DISTRICT_MAP = {
    '楠梓區': '楠梓區',
    '三民區': '三民區',
    '苓雅區': '苓雅區',
    '前鎮區': '前鎮區',
    '鳳山區': '鳳山區',
    '左營區': '左營區',
    '鼓山區': '鼓山區',
    '仁武區': '仁武區',
    '大社區': '大社區',
    '小港區': '小港區',
    '岡山區': '岡山區',
    '橋頭區': '橋頭區',
    '燕巢區': '燕巢區',
    '梓官區': '梓官區',
}


def _make_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--disable-gpu')
    opts.add_argument('--window-size=1280,800')
    # 有需要無頭模式時取消下方注解
    # opts.add_argument('--headless=new')
    driver = webdriver.Chrome(options=opts)
    return driver


def query_zone(district: str, section: str, land_no: str,
               driver: webdriver.Chrome = None) -> dict:
    """
    查詢高雄市土地使用分區
    回傳 dict:
      {
        'zone':      '第三種住宅區',   # 或 None
        'raw_text':  '...',            # 原始查詢結果文字
        'error':     None,             # 有錯誤時填字串
      }
    """
    own_driver = driver is None
    if own_driver:
        driver = _make_driver()

    result = {'zone': None, 'raw_text': '', 'error': None}

    try:
        driver.get(URL)
        wait = WebDriverWait(driver, 15)

        # 選行政區
        sel_dist = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//select[contains(@name,'district') or contains(@id,'district') or contains(@id,'District')]")
        ))
        Select(sel_dist).select_by_visible_text(district)
        time.sleep(0.8)

        # 選地段
        sel_sec = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//select[contains(@name,'section') or contains(@id,'section') or contains(@id,'Section')]")
        ))
        # 地段名可能含「段」「小段」，做模糊比對
        options = Select(sel_sec).options
        matched = None
        for opt in options:
            if section.replace('段', '').replace('小段', '') in opt.text.replace('段', '').replace('小段', ''):
                matched = opt.text
                break
        if matched:
            Select(sel_sec).select_by_visible_text(matched)
        else:
            # 找不到就直接用原始名稱
            Select(sel_sec).select_by_visible_text(section)
        time.sleep(0.5)

        # 填地號
        inp = driver.find_element(By.XPATH,
            "//input[contains(@name,'landNo') or contains(@id,'landNo') or contains(@id,'LandNo') or contains(@placeholder,'地號')]"
        )
        inp.clear()
        inp.send_keys(land_no.replace('-', ''))   # 有些系統不要 dash

        # 點查詢按鈕
        btn = driver.find_element(By.XPATH,
            "//img[contains(@src,'search') or contains(@alt,'查詢')] | //input[@type='button'] | //a[contains(@title,'查詢')]"
        )
        btn.click()
        time.sleep(2)

        # 抓結果
        body = driver.find_element(By.TAG_NAME, 'body').text
        result['raw_text'] = body

        # 解析使用分區
        zone = _parse_zone(body)
        result['zone'] = zone

    except Exception as e:
        result['error'] = str(e)
    finally:
        if own_driver:
            driver.quit()

    return result


def _parse_zone(text: str) -> str | None:
    """從查詢結果頁面文字萃取使用分區"""
    # 常見格式：「第三種住宅區」「第一種商業區」「工業區」
    patterns = [
        r'使用分區[：:\s]*([第一二三四五六七八九十\d]*種?[\u4e00-\u9fa5]+區)',
        r'土地使用分區[：:\s]*([第一二三四五六七八九十\d]*種?[\u4e00-\u9fa5]+區)',
        r'([第一二三四五六七八九十\d]+種[\u4e00-\u9fa5]+區)',
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


def parse_zone_to_fields(zone_str: str) -> dict:
    """
    將使用分區字串轉換為 fill_sale.py 所需欄位
    回傳:
      usage_zone      : '住宅區' / '商業區' / '工業區' / None
      usage_zone_type : '三' / '一' / None（第幾種）
      special_zone    : None（或特殊用地名）
    """
    if not zone_str:
        return {'usage_zone': None, 'usage_zone_type': None, 'special_zone': None}

    NUM_MAP = {'一': '一', '二': '二', '三': '三', '四': '四', '五': '五',
               '六': '六', '七': '七', '八': '八', '九': '九', '十': '十',
               '1': '一', '2': '二', '3': '三', '4': '四', '5': '五'}

    result = {'usage_zone': None, 'usage_zone_type': None, 'special_zone': None}

    if '住宅' in zone_str:
        result['usage_zone'] = '住宅區'
        m = re.search(r'第([一二三四五六七八九十\d]+)種', zone_str)
        if m:
            result['usage_zone_type'] = NUM_MAP.get(m.group(1), m.group(1))
    elif '商業' in zone_str:
        result['usage_zone'] = '商業區'
        m = re.search(r'第([一二三四五六七八九十\d]+)種', zone_str)
        if m:
            result['usage_zone_type'] = NUM_MAP.get(m.group(1), m.group(1))
    elif '工業' in zone_str:
        result['usage_zone'] = '工業區'
        m = re.search(r'第([一二三四五六七八九十\d]+)種', zone_str)
        if m:
            result['usage_zone_type'] = NUM_MAP.get(m.group(1), m.group(1))
    else:
        # 特殊用地
        result['special_zone'] = zone_str

    return result


if __name__ == '__main__':
    # 測試用
    import sys
    dist    = sys.argv[1] if len(sys.argv) > 1 else '楠梓區'
    section = sys.argv[2] if len(sys.argv) > 2 else '援中段一小段'
    no      = sys.argv[3] if len(sys.argv) > 3 else '0022-0000'
    r = query_zone(dist, section, no)
    print('查詢結果:', r)
    print('解析欄位:', parse_zone_to_fields(r['zone']))
