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
import re
from datetime import datetime
from pathlib import Path

import manifest

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_OUT = BASE_DIR / "配案看板.html"


def _parse_block(text: str) -> dict:
    """把一段輸出文字拆成「顯示用內容 / 貼給客戶用的原文 / 新案或降價標記」。

    對應 buyer_match.format_block（標題行可能帶 🆕）跟 run_group_match._unit_block
    （降價會在最前面多塞一行 🔻 開頭的 note）這兩種寫法，兩邊格式都在同一支 repo，
    直接照那邊的字元標記解析，不用另外存結構化欄位。"""
    lines = text.split("\n")
    tag = None
    price_note = None
    if lines and lines[0].startswith("🔻"):
        tag = "repriced"
        price_note = lines[0].strip()
        lines = lines[1:]
    if lines and "🆕" in lines[0]:
        if tag is None:
            tag = "new"
        lines[0] = lines[0].replace("🆕 ", "").replace("🆕", "").strip()
    return {
        "raw": text,
        "display": "\n".join(lines).strip(),
        "tag": tag,
        "price_note": price_note,
    }


# 卡片排序：新上架 → 降價 → 其他（沒標記的）
TAG_ORDER = {"new": 0, "repriced": 1, None: 2}


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
            blocks = [_parse_block(b.strip()) for b in text.split("\n\n") if b.strip()]
            # 🆕 新上架排最前面、其次 🔻 降價，剩下的維持原本順序（穩定排序）。
            # 打開一個客戶就先看到「今天有什麼新東西可以打電話」，不用自己從頭掃。
            blocks.sort(key=lambda b: TAG_ORDER.get(b["tag"], 9))
            new_n = sum(1 for b in blocks if b["tag"] == "new")
            repriced_n = sum(1 for b in blocks if b["tag"] == "repriced")
            rows.append(
                {
                    "customer": entry["customer"],
                    "need": entry["need"],
                    "timestamp": record["timestamp"],
                    "hits": record["hits"],
                    "is_full": entry.get("full") is not None,
                    "new_n": new_n,
                    "repriced_n": repriced_n,
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

/* 客戶/客需清單：跟物件卡片同款固定兩欄矩形卡片——客戶一多，長長一條直向列表
   最容易看到疲勞，改成卡片格才會跟後面翻進去的物件卡片視覺一致、掃視省力。 */
#needlist { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
#needlist .blank { grid-column: 1 / -1; }
.needcard {
  position: relative; width: 100%; text-align: left; font-family: inherit; color: inherit;
  background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 16px 14px 48px; cursor: pointer; box-shadow: var(--shadow); min-height: 136px;
}
.needcard:active { transform: scale(.98); }
.needcard-cust {
  display: block; font-size: 19px; font-weight: 700; line-height: 1.35; overflow-wrap: anywhere;
}
.needcard-need {
  display: block; font-size: 16px; color: var(--ink-soft); margin-top: 5px; overflow-wrap: anywhere;
}
.needcard-meta {
  display: block; font-size: 12.5px; color: var(--ink-soft); margin-top: 9px;
  font-variant-numeric: tabular-nums;
}
.needcard-count {
  position: absolute; right: 12px; bottom: 11px; text-align: right; color: var(--ink-soft); font-size: 12.5px;
}
.needcard-count b { display: block; font-size: 23px; color: var(--ink); font-variant-numeric: tabular-nums; }
/* 卡片右上角那排標籤：🆕 幾筆新上架、🔻 幾筆降價、僅新案 */
.needcard-flags {
  position: absolute; top: 9px; right: 9px; display: flex; gap: 4px; align-items: center;
}
.chip-new, .chip-drop {
  display: inline-block; font-size: 11px; font-weight: 800; padding: 2px 7px;
  border-radius: 5px; font-variant-numeric: tabular-nums;
}
.chip-new { background: rgba(45, 125, 79, .14); color: var(--fresh); }
.chip-drop { background: rgba(196, 64, 43, .13); color: var(--danger); }

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

/* 固定兩欄矩形卡片：字才能放大又不會每張高度亂跳，掃視比較不累眼睛 */
.cards { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.propcard {
  position: relative; background: var(--panel); border: 1px solid var(--line);
  border-radius: 12px; padding: 20px 34px 52px 14px; box-shadow: var(--shadow);
  min-height: 150px; display: flex; flex-direction: column; justify-content: center;
  overflow: visible;
}
.cardbody { display: flex; flex-direction: column; gap: 3px; }
.textline {
  font-family: inherit; font-size: 15px; line-height: 1.5;
  overflow-wrap: anywhere; font-variant-numeric: tabular-nums;
}
.textline-title { font-weight: 700; font-size: 16px; }
.linkline {
  display: inline-flex; align-items: center; gap: 5px; align-self: flex-start;
  margin-top: 7px; border: 1px solid var(--accent); color: var(--accent); background: transparent;
  border-radius: 7px; padding: 5px 11px; font-size: 13px; font-weight: 700;
  cursor: pointer; font-family: inherit; text-decoration: none;
}
.linkrow { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-top: 7px; }
.linkrow .linkline { margin-top: 0; }
.linkcopy {
  border: 1px solid var(--line); background: transparent; color: var(--ink-soft);
  border-radius: 7px; padding: 5px 9px; font-size: 12.5px; cursor: pointer; font-family: inherit;
}
.linkcopy[data-done="1"] { border-color: var(--accent); color: var(--accent); font-weight: 700; }

.pricenote {
  color: var(--danger); font-weight: 800; font-size: 12.5px; margin-bottom: 6px;
  font-variant-numeric: tabular-nums;
}

/* 貼紙／印章：新案、降價一眼看到，不用逐行讀文字才知道 */
.stamp {
  position: absolute; top: -9px; left: 10px; z-index: 2;
  font-size: 11px; font-weight: 800; letter-spacing: .03em;
  padding: 4px 10px; border-radius: 4px; transform: rotate(-5deg);
  box-shadow: 0 2px 5px rgba(40,30,10,.18); border: 2px solid currentColor;
  background: var(--panel);
}
.stamp-new { color: var(--fresh); }
.stamp-repriced { color: var(--danger); }

/* 電腦螢幕：字整體放大一級、卡片寬一點。手機那邊維持原樣不動。
   （2026-08-05 使用者要求：電腦上看眼睛比較舒適） */
@media (min-width: 760px) {
  body { font-size: 17px; }
  main { max-width: 1180px; padding: 18px 20px; }
  .masthead h1 { font-size: 19px; }
  .built { font-size: 12.5px; }
  .grouppill { font-size: 15.5px; padding: 7px 17px; }
  #needlist { gap: 14px; }
  .needcard { padding: 19px 17px 54px; min-height: 152px; }
  .needcard-cust { font-size: 22px; }
  .needcard-need { font-size: 18px; }
  .needcard-meta { font-size: 13.5px; }
  .needcard-count b { font-size: 26px; }
  .cards { gap: 14px; }
  .propcard { padding: 24px 38px 58px 18px; min-height: 166px; }
  .textline { font-size: 17px; }
  .textline-title { font-size: 18.5px; }
  .linkline, .btn { font-size: 15px; }
  .copy-btn { font-size: 14.5px; padding: 9px 0; }
  .drill-meta { font-size: 14px; }
}

@media (max-width: 420px) {
  .cards { gap: 8px; }
  .propcard { padding: 18px 30px 48px 12px; }
  .textline { font-size: 14.5px; }
  .textline-title { font-size: 15.5px; }
  #needlist { gap: 8px; }
  .needcard { padding: 13px 12px 44px; min-height: 122px; }
  .needcard-cust { font-size: 17.5px; }
  .needcard-need { font-size: 14.5px; }
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

/* 連結預覽：點連結不切分頁，原地跳一個夠寬的視窗把內容嵌進來看 */
.linkmodal { position: fixed; inset: 0; background: rgba(0,0,0,.62); z-index: 92;
  display: none; align-items: center; justify-content: center; padding: 16px; }
.linkmodal[data-on="1"] { display: flex; }
.linkmodal-card {
  background: var(--panel); border-radius: 14px; overflow: hidden;
  width: min(94vw, 900px); height: min(88vh, 920px);
  display: flex; flex-direction: column; box-shadow: 0 8px 30px rgba(0,0,0,.35);
}
.linkmodal-bar {
  display: flex; align-items: center; gap: 8px; padding: 9px 10px;
  border-bottom: 1px solid var(--line); flex: none;
}
.linkmodal-url {
  flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 12px; color: var(--ink-soft); font-variant-numeric: tabular-nums;
}
.linkmodal-frame { flex: 1; width: 100%; border: 0; background: var(--ground); }
.linkmodal-fallback {
  flex: 1; display: none; align-items: center; justify-content: center; flex-direction: column;
  gap: 12px; padding: 24px; text-align: center; color: var(--ink-soft); font-size: 13.5px;
}
.linkmodal-fallback[data-on="1"] { display: flex; }

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

<div class="linkmodal" id="linkmodal">
  <div class="linkmodal-card">
    <div class="linkmodal-bar">
      <span class="linkmodal-url" id="linkmodal-url"></span>
      <a class="btn" id="linkmodal-open" target="_blank" rel="noopener">開新分頁</a>
      <button class="x-btn" id="linkmodal-close" style="position:static" aria-label="關閉">✕</button>
    </div>
    <iframe class="linkmodal-frame" id="linkmodal-frame" title="物件內容預覽"></iframe>
    <div class="linkmodal-fallback" id="linkmodal-fallback">
      <span>這個網站不給嵌入預覽，改開新分頁看內容</span>
    </div>
  </div>
</div>
"""

SCRIPT = r"""
const DATA = __DATA_JSON__;
let group = null, row = null;

// Claude Artifact 本身就跑在一層 iframe 裡（沙盒沒開 allow-popups），JS 呼叫
// window.open() 會被整個吃掉、按了沒反應；只有「使用者真的點到一個 <a target=_blank>」
// 才放行。所以在 Artifact 裡要放真的 <a> 連結讓瀏覽器原生處理，不能用 JS 開視窗。
// 桌面單檔 HTML 是最上層視窗，不受這限制，維持原本「原地彈窗預覽」。
const topLevel = (() => { try { return window.self === window.top; } catch (e) { return false; } })();

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
    b.className = 'needcard';
    // 有新上架就在客戶卡上直接標出來，不用一個一個點進去才知道誰有新東西
    const flags =
      (r.new_n ? '<span class="chip-new">新 ' + r.new_n + '</span>' : '') +
      (r.repriced_n ? '<span class="chip-drop">降 ' + r.repriced_n + '</span>' : '');
    b.innerHTML =
      '<span class="needcard-flags">' + flags +
      (r.is_full ? '' : '<span class="chip-partial">僅新案</span>') + '</span>' +
      '<span class="needcard-cust">' + esc(r.customer) + '</span>' +
      '<span class="needcard-need">' + esc(r.need) + '</span>' +
      '<span class="needcard-meta">' + esc((r.timestamp || '').replace('T', ' ').slice(0, 16)) + '</span>' +
      '<span class="needcard-count"><b>' + r.hits + '</b>筆</span>';
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
  row.blocks.forEach((blk, i) => {
    if (hidden.has(i)) return;
    const card = document.createElement('div');
    card.className = 'propcard';

    if (blk.tag) {
      const stamp = document.createElement('span');
      stamp.className = 'stamp stamp-' + blk.tag;
      stamp.textContent = blk.tag === 'new' ? '🆕 新案' : '🔻 降價';
      card.appendChild(stamp);
    }

    const x = document.createElement('button');
    x.className = 'x-btn';
    x.textContent = '✕';
    x.title = '篩掉這筆';
    x.setAttribute('aria-label', '篩掉這筆');
    x.onclick = () => { const s = getX(row); s.add(i); setX(row, s); card.remove(); blankCheck(); };

    const body = document.createElement('div');
    body.className = 'cardbody';
    if (blk.price_note) {
      const note = document.createElement('div');
      note.className = 'pricenote';
      note.textContent = blk.price_note;
      body.appendChild(note);
    }
    blk.display.split('\n').forEach((line, li) => {
      if (/^https?:\/\//.test(line.trim())) {
        const url = line.trim();
        // 連結那排：主按鈕（預覽或開新分頁）＋ 複製連結。
        // 電腦上用 claude.ai 開這份看板時，外站連結會被那層 iframe 攔下來、
        // 有時候按了像沒反應，所以一定要留一個「複製連結」的退路。
        const wrapLink = document.createElement('div');
        wrapLink.className = 'linkrow';
        if (topLevel) {
          const a = document.createElement('button');
          a.className = 'linkline';
          a.textContent = '🔗 看詳情／分享頁';
          a.onclick = (e) => { e.stopPropagation(); openLink(url); };
          wrapLink.appendChild(a);
        } else {
          // Artifact 裡：給真的 <a target=_blank>，讓瀏覽器原生處理開新分頁，
          // JS 的 window.open() 在這層沙盒會被吃掉、按了沒反應。
          const a = document.createElement('a');
          a.className = 'linkline';
          a.href = url;
          a.target = '_blank';
          a.rel = 'noopener noreferrer';
          a.textContent = '🔗 看詳情／分享頁';
          a.onclick = (e) => { e.stopPropagation(); };
          wrapLink.appendChild(a);
        }
        const cp = document.createElement('button');
        cp.className = 'linkcopy';
        cp.textContent = '複製連結';
        cp.onclick = async (e) => {
          e.stopPropagation();
          if (await copyText(url)) { cp.textContent = '已複製'; cp.dataset.done = '1';
            setTimeout(() => { cp.textContent = '複製連結'; cp.dataset.done = '0'; }, 1600); }
        };
        wrapLink.appendChild(cp);
        body.appendChild(wrapLink);
      } else {
        const d = document.createElement('div');
        d.className = 'textline' + (li === 0 ? ' textline-title' : '');
        d.textContent = line;
        body.appendChild(d);
      }
    });

    const c = document.createElement('button');
    c.className = 'copy-btn';
    c.textContent = '複製這筆';
    c.onclick = async () => {
      if (await copyText(blk.raw)) {
        c.textContent = '已複製';
        c.dataset.done = '1';
        setTimeout(() => { c.textContent = '複製這筆'; c.dataset.done = '0'; }, 1200);
      }
    };

    card.append(x, body, c);
    wrap.appendChild(card);
  });
  blankCheck();
}

const blankCheck = () =>
  $('cards-blank').style.display = $('cards').children.length ? 'none' : 'block';

let linkTimer = null;
function openLink(url) {
  $('linkmodal-url').textContent = url;
  $('linkmodal-open').href = url;
  $('linkmodal-fallback').dataset.on = '0';
  const frame = $('linkmodal-frame');
  frame.style.display = 'block';
  let loaded = false;
  frame.onload = () => { loaded = true; };
  frame.onerror = () => { frame.style.display = 'none'; $('linkmodal-fallback').dataset.on = '1'; };
  frame.src = url;
  $('linkmodal').dataset.on = '1';
  clearTimeout(linkTimer);
  // iframe 被目標網站的 X-Frame-Options 擋掉的時候不一定會觸發 onerror，
  // 用逾時當保底：時間到了還沒 load 完，就假設嵌不進來，改推薦開新分頁。
  linkTimer = setTimeout(() => {
    if (!loaded) { frame.style.display = 'none'; $('linkmodal-fallback').dataset.on = '1'; }
  }, 2500);
}
function closeLink() {
  $('linkmodal').dataset.on = '0';
  $('linkmodal-frame').src = 'about:blank';
  clearTimeout(linkTimer);
}

$('btn-back').onclick = showList;
$('btn-restore').onclick = () => { setX(row, new Set()); renderCards(); toast('已復原'); };
$('btn-copyall').onclick = async () => {
  const hidden = getX(row);
  const t = row.blocks.filter((_, i) => !hidden.has(i)).map(b => b.raw);
  if (!t.length) return toast('沒有可複製的');
  if (await copyText(t.join('\n\n'))) toast('已複製 ' + t.length + ' 筆');
};
$('btn-fallback-close').onclick = () => $('fallback').dataset.on = '0';
$('linkmodal-close').onclick = closeLink;
$('linkmodal').addEventListener('click', (e) => { if (e.target.id === 'linkmodal') closeLink(); });

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


def render(fmt: str = "standalone", groups: dict | None = None) -> str:
    """產生看板 HTML 字串。

    webview_server.py 也是叫這支——版面只有這一份，改一次三個入口
    （localhost 網頁／桌面單檔／手機 artifact）就一起跟著變。"""
    if groups is None:
        groups = collect()
    shell = STANDALONE if fmt == "standalone" else ARTIFACT
    return (
        shell.replace("__STYLE__", STYLE)
        .replace("__BODY__", BODY.replace("__BUILT_AT__", datetime.now().strftime("%Y-%m-%d %H:%M")))
        .replace("__SCRIPT__", SCRIPT.replace("__DATA_JSON__", json.dumps(groups, ensure_ascii=False)))
    )


def build(out_path: Path, fmt: str) -> Path:
    groups = collect()
    total = sum(len(rows) for rows in groups.values())
    html = render(fmt, groups)
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
