# -*- coding: utf-8 -*-
"""第7頁距離用：OpenStreetMap 查座標，算本案到各地標的直線距離。

用法:  python geo.py "田中巷, 屏東市" "屏東演藝廳" "國仁醫院 屏東" ...
       第一個是本案，其餘是地標。結果寫 geo_result.txt（utf-8），同時印出。

- Nominatim 規定每秒最多 1 次，這裡每筆間隔 1.2 秒。User-Agent 不要放任何個人 email。
- 查不到或查到外縣市（例如「屏東科學園區」會回北京）就換關鍵字，改查附近的車站/路口，
  並在文案寫清楚是以哪個點計算（例：屏東科學園區（六塊厝）約5公里）。
- 一律寫「約 X 公尺／公里」，直線距離，不要寫成步行或車程分鐘數。
"""
import json
import math
import sys
import time
import urllib.parse
import urllib.request

UA = 'sale-report-skill/1.0'


def geocode(q):
    url = 'https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=tw&q=' \
          + urllib.parse.quote(q)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    hits = json.load(urllib.request.urlopen(req, timeout=20))
    if not hits:
        return None
    h = hits[0]
    return float(h['lat']), float(h['lon']), h['display_name']


def dist_m(a, b):
    lat = math.radians((a[0] + b[0]) / 2)
    dy = (a[0] - b[0]) * 111320
    dx = (a[1] - b[1]) * 111320 * math.cos(lat)
    return math.hypot(dx, dy)


def fmt(m):
    return '約%d公尺' % (round(m / 50) * 50) if m < 1000 else '約%.1f公里' % (m / 1000)


def main(args):
    out = []
    base = geocode(args[0])
    if not base:
        sys.exit('本案查不到座標：' + args[0])
    out.append('本案 %s → %.5f,%.5f %s' % (args[0], base[0], base[1], base[2]))
    for q in args[1:]:
        time.sleep(1.2)
        g = geocode(q)
        if not g:
            out.append('%s → 查不到' % q)
            continue
        out.append('%s → %s（%.5f,%.5f %s）' % (q, fmt(dist_m(base, g)), g[0], g[1], g[2][:40]))
    txt = '\n'.join(out)
    open('geo_result.txt', 'w', encoding='utf-8').write(txt + '\n')
    sys.stdout.buffer.write((txt + '\n').encode('utf-8'))


if __name__ == '__main__':
    main(sys.argv[1:])
