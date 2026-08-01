#!/usr/bin/env python3
r"""把 output/ 的結果打包成「資料直接嵌在檔案裡」的 HTML 看板。

為什麼要這個：門市電腦是有線網路（192.168.1.x），手機是 WiFi（192.168.168.x），
公司把兩個網段隔開了 → 手機連不到電腦上跑的 webview_server.py。
改成產生單檔 HTML，不靠網路相通。

兩種輸出格式（同一份模板，避免兩邊維護會走鐘）：
    standalone  完整 HTML（含 <html><head>），可直接雙擊開、或丟 OneDrive／GitHub Pages
    artifact    只有內容片段（Claude Artifact 發布用，外層骨架由平台補）

用法：
    python build_static_view.py                          # standalone → 配案看板.html
    python build_static_view.py --format artifact --out artifact.html
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import manifest

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_OUT = BASE_DIR / "配案看板.html"


def collect() -> dict:
    """把 manifest + 每個結果檔的內容，全部讀成一包可以嵌進 HTML 的資料。"""
    data = manifest.load()
    groups: dict[str, list] = {}
    for group, bucket in data.items():
        rows = []
        for entry in bucket.values():
            record = entry.get("full") or entry.get("latest")
            if not record:
                continue
            path = OUTPUT_DIR / record["file"]
            if not path.exists():
                print(f"[WARN] 結果檔不見了，跳過：{record['file']}")
                continue
            text = path.read_text(encoding="utf-8")
            blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
            rows.append(
                {
                    "customer": entry["customer"],
                    "need": entry["need"],
                    "timestamp": record["timestamp"],
                    "hits": record["hits"],
                    "is_full": entry.get("full") is not None,
                    "blocks": blocks,
                }
            )
        rows.sort(key=lambda r: r["customer"])
        if rows:
            groups[group] = rows
    return groups


# ── 設計取向 ────────────────────────────────────────────────────
# 這是「工具」不是「文件」：手機上單手掃視、點兩下就要能複製貼給客戶。
# 配色錨在永慶自家的橘（#E85D04，比純橘沉一點、長時間看不刺眼），中性色全部
# 往暖偏一點點，跟橘同一個色溫，不用純灰（純灰配暖橘會顯得髒）。
# 數字一律 tabular-nums，列表右側的「筆數」才會對齊、掃視得快。
STYLE = r"""
:root {
  --ground: #FAF8F6; --panel: #FFFFFF; --ink: #1A1614; --ink-soft: #6E645C;
  --line: #E7E0D9; --accent: #E85D04; --on-accent: #FFFFFF;
  --fresh: #2D7D4F; --danger: #C4402B;
  --shadow: 0 1px 2px rgba(60,40,20,.06), 0 1px 8px rgba(60,40,20,.04);
}
@media (prefers-color-scheme: dark) {
  :root {
    --ground: #15120F; --panel: #201C18; --ink: #F1ECE6; --ink-soft: #9E938A;
    --line: #332C25; --accent: #FF8A3D; --on-accent: #1A1207;
    --fresh: #5FBF87; --danger: #FF7A63;
    --shadow: 0 1px 3px rgba(0,0,0,.5);
  }
}
/* 檢視者自己的主題切換要贏過系統偏好，兩個方向都要蓋 */
:root[data-theme="light"] {
  --ground: #FAF8F6; --panel: #FFFFFF; --ink: #1A1614; --ink-soft: #6E645C;
  --line: #E7E0D9; --accent: #E85D04; --on-accent: #FFFFFF;
  --fresh: #2D7D4F; --danger: #C4402B;
  --shadow: 0 1px 2px rgba(60,40,20,.06), 0 1px 8px rgba(60,40,20,.04);
}
:root[data-theme="dark"] {
  --ground: #15120F; --panel: #201C18; --ink: #F1ECE6; --ink-soft: #9E938A;
  --line: #332C25; --accent: #FF8A3D; --on-accent: #1A1207;
  --fresh: #5FBF87; --danger: #FF7A63;
  --shadow: 0 1px 3px rgba(0,0,0,.5);
}

* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
body {
  margin: 0; background: var(--ground); color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC",
               "Noto Sans TC", "Microsoft JhengHei", sans-serif;
  font-size: 15px; line-height: 1.5; padding-bottom: 48px;
  -webkit-text-size-adjust: 100%;
}
.num { font-variant-numeric: tabular-nums; }

.masthead {
  position: sticky; top: 0; z-index: 20; background: var(--ground);
  border-bottom: 1px solid var(--line); padding: 12px 16px 0;
}
.masthead h1 {
  font-size: 16px; font-weight: 700; margin: 0; letter-spacing: -.01em;
  display: flex; align-items: baseline; gap: 8px;
}
.built {
  font-size: 11px; color: var(--ink-soft); margin: 2px 0 10px;
  font-variant-numeric: tabular-nums;
}
.groupbar { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 10px; scrollbar-width: none; }
.groupbar::-webkit-scrollbar { display: none; }
.grouppill {
  flex: none; padding: 6px 14px; border-radius: 999px; border: 1px solid var(--line);
  background: var(--panel); color: var(--ink); font-size: 14px; font-weight: 500;
  cursor: pointer; white-space: nowrap; font-family: inherit;
}
.grouppill[aria-pressed="true"] {
  background: var(--accent); color: var(--on-accent); border-color: var(--accent); font-weight: 700;
}
.grouppill:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

main { padding: 14px 16px; max-width: 940px; margin: 0 auto; }

/* 列表：左邊是誰要什麼，右邊是有幾筆——右側數字對齊，一眼掃完 */
.needrow {
  width: 100%; text-align: left; font-family: inherit; color: inherit;
  background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 12px 14px; margin-bottom: 8px; cursor: pointer; box-shadow: var(--shadow);
  display: flex; justify-content: space-between; align-items: center; gap: 12px;
}
.needrow:active { transform: scale(.995); }
.needrow-main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.needrow-title {
  display: block; font-size: 15px; font-weight: 600; letter-spacing: -.005em;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.needrow-meta {
  display: block; font-size: 11.5px; color: var(--ink-soft);
  font-variant-numeric: tabular-nums;
}
.chip-partial + .needrow-meta, .needrow-main > .chip-partial { align-self: flex-start; }
.count { flex: none; text-align: right; color: var(--ink-soft); font-size: 11px; }
.count b { display: block; font-size: 19px; color: var(--ink); font-variant-numeric: tabular-nums; }
.chip-partial {
  display: inline-block; font-size: 10.5px; font-weight: 600;
  padding: 2px 7px; border-radius: 5px; letter-spacing: .02em;
  background: rgba(232, 93, 4, .15); color: var(--accent);
}
@media (prefers-color-scheme: dark) { .chip-partial { background: rgba(255, 138, 61, .18); } }
:root[data-theme="dark"] .chip-partial { background: rgba(255, 138, 61, .18); }
:root[data-theme="light"] .chip-partial { background: rgba(232, 93, 4, .15); }

.actionbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.btn {
  border: 1px solid var(--line); background: var(--panel); color: var(--ink);
  border-radius: 8px; padding: 8px 13px; font-size: 14px; cursor: pointer; font-family: inherit;
}
.btn-primary {
  background: var(--accent); color: var(--on-accent); border-color: var(--accent);
  font-weight: 700; margin-left: auto;
}
.drill-meta { font-size: 12.5px; color: var(--ink-soft); margin-bottom: 12px; }

.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(258px, 1fr)); gap: 10px; }
.propcard {
  position: relative; background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: 13px 40px 50px 14px; box-shadow: var(--shadow);
}
.propcard pre {
  white-space: pre-wrap; overflow-wrap: anywhere; font-family: inherit;
  font-size: 13.5px; line-height: 1.55; margin: 0; font-variant-numeric: tabular-nums;
}
.x-btn {
  position: absolute; top: 7px; right: 7px; width: 30px; height: 30px; border-radius: 50%;
  border: none; background: rgba(128, 122, 114, .16);
  color: var(--ink-soft); font-size: 15px; line-height: 1; cursor: pointer; font-family: inherit;
}
.x-btn:hover, .x-btn:active { background: var(--danger); color: #fff; }
.copy-btn {
  position: absolute; left: 14px; right: 14px; bottom: 13px;
  border: 1px solid var(--accent); background: transparent; color: var(--accent);
  border-radius: 7px; padding: 8px 0; font-size: 13px; cursor: pointer;
  font-weight: 700; font-family: inherit;
}
.copy-btn[data-done="1"] { background: var(--accent); color: var(--on-accent); }

.blank { color: var(--ink-soft); text-align: center; padding: 44px 0; font-size: 14px; }
.toast {
  position: fixed; bottom: 22px; left: 50%; transform: translateX(-50%);
  background: var(--ink); color: var(--ground); padding: 9px 17px; border-radius: 8px;
  font-size: 13px; opacity: 0; pointer-events: none; transition: opacity .18s; z-index: 60;
}
.toast[data-show="1"] { opacity: .96; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; } .needrow:active { transform: none; } }

#screen-list, #screen-cards { display: none; }
#screen-list[data-on="1"], #screen-cards[data-on="1"] { display: block; }

.fallback { position: fixed; inset: 0; background: rgba(0,0,0,.62); z-index: 90;
  display: none; align-items: center; justify-content: center; padding: 20px; }
.fallback[data-on="1"] { display: flex; }
.fallback-card { background: var(--panel); border-radius: 12px; padding: 16px; width: 100%; max-width: 560px; }
.fallback p { margin: 0 0 9px; font-size: 13px; color: var(--ink-soft); }
.fallback textarea {
  width: 100%; height: 44vh; font: inherit; font-size: 13px; border: 1px solid var(--line);
  border-radius: 8px; padding: 10px; background: var(--ground); color: var(--ink);
  -webkit-user-select: text; user-select: text;
}
"""

BODY = r"""
<header class="masthead">
  <h1>買方配案</h1>
  <div class="built">資料更新於 __BUILT_AT__</div>
  <div class="groupbar" id="groupbar"></div>
</header>

<main>
  <div id="screen-list" data-on="1">
    <div id="needlist"></div>
  </div>

  <div id="screen-cards">
    <div class="actionbar">
      <button class="btn" id="btn-back">← 返回</button>
      <button class="btn" id="btn-restore">↺ 復原叉掉的</button>
      <button class="btn btn-primary" id="btn-copyall">全部複製</button>
    </div>
    <div class="drill-meta" id="drillmeta"></div>
    <div class="cards" id="cards"></div>
    <div class="blank" id="cards-blank" style="display:none">這組都篩完了</div>
  </div>
</main>

<div class="toast" id="toast" role="status" aria-live="polite"></div>

<div class="fallback" id="fallback">
  <div class="fallback-card">
    <p>這個瀏覽器擋掉了自動複製。長按下面文字 → 全選 → 拷貝</p>
    <textarea id="fallback-text" readonly></textarea>
    <button class="btn btn-primary" id="btn-fallback-close" style="width:100%;margin-top:10px">關閉</button>
  </div>
</div>
"""

SCRIPT = r"""
const DATA = __DATA_JSON__;
let group = null, row = null;

const $ = id => document.getElementById(id);
const esc = s => (s || '').replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.dataset.show = '1';
  setTimeout(() => t.dataset.show = '0', 1500);
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) {}
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;top:-9999px';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    ta.remove();
    if (ok) return true;
  } catch (e) {}
  // 用 file:// 開的時候不算安全內容，兩條路都可能失敗 → 給一個可以手動長按複製的框，
  // 不要讓使用者完全拿不到文字。
  $('fallback-text').value = text;
  $('fallback').dataset.on = '1';
  return false;
}

const keyOf = r => 'x:' + group + '|' + r.customer + '|' + r.need;
const getX = r => { try { return new Set(JSON.parse(localStorage.getItem(keyOf(r)) || '[]')); } catch (e) { return new Set(); } };
const setX = (r, s) => { try { localStorage.setItem(keyOf(r), JSON.stringify([...s])); } catch (e) {} };

function renderGroups() {
  const bar = $('groupbar'), names = Object.keys(DATA);
  bar.innerHTML = '';
  if (!names.length) {
    bar.innerHTML = '<span style="color:var(--ink-soft);font-size:14px;padding-bottom:10px">還沒有查詢結果</span>';
    return;
  }
  if (!group || !names.includes(group)) group = names[0];
  names.forEach(g => {
    const b = document.createElement('button');
    b.className = 'grouppill';
    b.setAttribute('aria-pressed', String(g === group));
    b.innerHTML = esc(g) + ' <span class="num">' + DATA[g].length + '</span>';
    b.onclick = () => { group = g; renderGroups(); showList(); };
    bar.appendChild(b);
  });
  renderList();
}

function renderList() {
  const el = $('needlist'), rows = DATA[group] || [];
  el.innerHTML = '';
  if (!rows.length) { el.innerHTML = '<div class="blank">這組還沒有結果</div>'; return; }
  rows.forEach(r => {
    const b = document.createElement('button');
    b.className = 'needrow';
    b.innerHTML =
      '<span class="needrow-main">' +
        '<span class="needrow-title">' + esc(r.customer) + '　' + esc(r.need) + '</span>' +
        '<span class="needrow-meta">' + esc((r.timestamp || '').replace('T', ' ').slice(0, 16)) + '</span>' +
        (r.is_full ? '' : '<span class="chip-partial">僅新案</span>') +
      '</span>' +
      '<span class="count"><b>' + r.hits + '</b>筆</span>';
    b.onclick = () => openRow(r);
    el.appendChild(b);
  });
}

function showList() {
  $('screen-list').dataset.on = '1';
  $('screen-cards').dataset.on = '0';
  scrollTo(0, 0);
}

function openRow(r) {
  row = r;
  $('drillmeta').textContent =
    r.customer + '　' + r.need + '　共 ' + r.hits + ' 筆' + (r.is_full ? '' : '（僅新案）');
  renderCards();
  $('screen-list').dataset.on = '0';
  $('screen-cards').dataset.on = '1';
  scrollTo(0, 0);
}

function renderCards() {
  const wrap = $('cards'), hidden = getX(row);
  wrap.innerHTML = '';
  row.blocks.forEach((text, i) => {
    if (hidden.has(i)) return;
    const card = document.createElement('div');
    card.className = 'propcard';

    const x = document.createElement('button');
    x.className = 'x-btn';
    x.textContent = '✕';
    x.title = '篩掉這筆';
    x.setAttribute('aria-label', '篩掉這筆');
    x.onclick = () => { const s = getX(row); s.add(i); setX(row, s); card.remove(); blankCheck(); };

    const pre = document.createElement('pre');
    pre.textContent = text;

    const c = document.createElement('button');
    c.className = 'copy-btn';
    c.textContent = '複製這筆';
    c.onclick = async () => {
      if (await copyText(text)) {
        c.textContent = '已複製';
        c.dataset.done = '1';
        setTimeout(() => { c.textContent = '複製這筆'; c.dataset.done = '0'; }, 1200);
      }
    };

    card.append(x, pre, c);
    wrap.appendChild(card);
  });
  blankCheck();
}

const blankCheck = () =>
  $('cards-blank').style.display = $('cards').children.length ? 'none' : 'block';

$('btn-back').onclick = showList;
$('btn-restore').onclick = () => { setX(row, new Set()); renderCards(); toast('已復原'); };
$('btn-copyall').onclick = async () => {
  const t = [...document.querySelectorAll('#cards .propcard pre')].map(p => p.textContent);
  if (!t.length) return toast('沒有可複製的');
  if (await copyText(t.join('\n\n'))) toast('已複製 ' + t.length + ' 筆');
};
$('btn-fallback-close').onclick = () => $('fallback').dataset.on = '0';

renderGroups();
showList();
"""

STANDALONE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>買方配案看板</title>
<style>__STYLE__</style>
</head>
<body>
__BODY__
<script>__SCRIPT__</script>
</body>
</html>
"""

ARTIFACT = """<title>買方配案看板</title>
<style>__STYLE__</style>
__BODY__
<script>__SCRIPT__</script>
"""


def build(out_path: Path, fmt: str) -> Path:
    groups = collect()
    total = sum(len(rows) for rows in groups.values())
    shell = STANDALONE if fmt == "standalone" else ARTIFACT
    html = (
        shell.replace("__STYLE__", STYLE)
        .replace("__BODY__", BODY.replace("__BUILT_AT__", datetime.now().strftime("%Y-%m-%d %H:%M")))
        .replace("__SCRIPT__", SCRIPT.replace("__DATA_JSON__", json.dumps(groups, ensure_ascii=False)))
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"[INFO] 已產生看板（{fmt}）：{out_path}")
    print(f"[INFO] {len(groups)} 個群組、{total} 個客戶/客需、共 {sum(r['hits'] for rows in groups.values() for r in rows)} 筆")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="把配案結果打包成單檔 HTML 看板")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--format", choices=["standalone", "artifact"], default="standalone")
    args = ap.parse_args()
    build(Path(args.out), args.format)


if __name__ == "__main__":
    main()
