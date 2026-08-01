#!/usr/bin/env python3
"""買方配案結果看板：本機網頁，手機/電腦都能連進來看＋複製。

只讀 output/ 和 manifest.json，不碰 Chrome、不碰 i智慧/房地，跟查詢流程完全分開跑。

用法：
    python webview_server.py            # 預設 0.0.0.0:5001，手機跟電腦都連得到
    python webview_server.py --port 5002

手機連法：跟電腦在同一個 WiFi，瀏覽器打 http://<這台電腦的區網IP>:5001

⚠️ 只在區網內用（沒有帳密保護）。這份資料含真實客戶姓名/需求跟業務員聯絡方式，
不要把這個 port 對外開放（路由器連接埠轉發／DDNS 之類），僅限同一個 WiFi 底下使用。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from flask import Flask, Response, abort, jsonify, request

import manifest

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

app = Flask(__name__)


def _entry_for_display(entry: dict) -> dict:
    """挑 full（完整清單）或退而求其次用 latest（可能只是當天新案），
    附上 is_full 讓前端能標「僅新案」提醒使用者這不是完整清單。"""
    record = entry.get("full") or entry.get("latest")
    if record is None:
        return None
    return {
        "customer": entry["customer"],
        "need": entry["need"],
        "key": f"{entry['customer']}／{entry['need']}",
        "file": record["file"],
        "timestamp": record["timestamp"],
        "hits": record["hits"],
        "is_full": entry.get("full") is not None,
    }


@app.get("/api/manifest")
def api_manifest():
    data = manifest.load()
    groups = {}
    for group, bucket in data.items():
        rows = []
        for entry in bucket.values():
            row = _entry_for_display(entry)
            if row:
                rows.append(row)
        rows.sort(key=lambda r: r["customer"])
        if rows:
            groups[group] = rows
    return jsonify({"groups": groups})


@app.get("/api/cards")
def api_cards():
    filename = request.args.get("file", "")
    # 防路徑穿越：只准純檔名，且必須真的落在 output/ 底下
    safe_name = Path(filename).name
    path = (OUTPUT_DIR / safe_name).resolve()
    if not safe_name.endswith(".txt") or path.parent != OUTPUT_DIR.resolve() or not path.exists():
        abort(404)
    text = path.read_text(encoding="utf-8")
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return jsonify({"blocks": blocks})


@app.get("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


INDEX_HTML = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>買方配案看板</title>
<style>
  :root {
    --bg: #f5f5f7; --panel: #ffffff; --text: #1c1c1e; --muted: #6b6b70;
    --border: #e2e2e5; --accent: #ff6a00; --accent-text: #ffffff;
    --danger: #e14b4b; --shadow: 0 1px 3px rgba(0,0,0,.08);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #17171a; --panel: #232326; --text: #f2f2f3; --muted: #9a9aa0;
      --border: #35353a; --accent: #ff8a3d; --accent-text: #1a1a1a;
      --danger: #ff6b6b; --shadow: 0 1px 4px rgba(0,0,0,.4);
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang TC", "Microsoft JhengHei", sans-serif;
    padding-bottom: 40px;
  }
  header {
    position: sticky; top: 0; z-index: 10; background: var(--bg);
    padding: 14px 14px 0; border-bottom: 1px solid var(--border);
  }
  h1 { font-size: 18px; margin: 0 0 10px; }
  .tabs { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 10px; }
  .tab {
    flex: none; padding: 7px 14px; border-radius: 999px; border: 1px solid var(--border);
    background: var(--panel); color: var(--text); font-size: 14px; cursor: pointer; white-space: nowrap;
  }
  .tab.active { background: var(--accent); color: var(--accent-text); border-color: var(--accent); font-weight: 600; }
  main { padding: 14px; max-width: 900px; margin: 0 auto; }
  .row {
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px;
    padding: 12px 14px; margin-bottom: 8px; cursor: pointer; box-shadow: var(--shadow);
    display: flex; justify-content: space-between; align-items: center; gap: 10px;
  }
  .row:active { opacity: .7; }
  .row-main { min-width: 0; }
  .row-title { font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .row-sub { font-size: 12px; color: var(--muted); margin-top: 2px; }
  .badge { flex: none; font-size: 12px; color: var(--muted); text-align: right; }
  .badge .n { font-size: 16px; font-weight: 700; color: var(--text); }
  .warn-chip {
    display: inline-block; margin-top: 4px; font-size: 11px; padding: 1px 6px;
    border-radius: 6px; background: rgba(255,138,61,.18); color: var(--accent);
  }
  .toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
  .back-btn, .copyall-btn, .refresh-btn {
    border: 1px solid var(--border); background: var(--panel); color: var(--text);
    border-radius: 8px; padding: 8px 12px; font-size: 14px; cursor: pointer;
  }
  .copyall-btn { background: var(--accent); color: var(--accent-text); border-color: var(--accent); font-weight: 600; margin-left: auto; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
  .card {
    position: relative; background: var(--panel); border: 1px solid var(--border);
    border-radius: 12px; padding: 14px 14px 48px; box-shadow: var(--shadow);
  }
  .card pre {
    white-space: pre-wrap; word-break: break-word; font-family: inherit; font-size: 14px;
    line-height: 1.55; margin: 0;
  }
  .dismiss-btn {
    position: absolute; top: 8px; right: 8px; width: 26px; height: 26px; border-radius: 50%;
    border: none; background: rgba(128,128,128,.18); color: var(--muted);
    font-size: 15px; line-height: 1; cursor: pointer;
  }
  .dismiss-btn:hover { background: var(--danger); color: #fff; }
  .card-copy-btn {
    position: absolute; left: 14px; right: 14px; bottom: 14px;
    border: 1px solid var(--accent); background: transparent; color: var(--accent);
    border-radius: 8px; padding: 7px 0; font-size: 13px; cursor: pointer; font-weight: 600;
  }
  .card-copy-btn.copied { background: var(--accent); color: var(--accent-text); }
  .empty { color: var(--muted); text-align: center; padding: 40px 0; font-size: 14px; }
  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--text); color: var(--bg); padding: 8px 16px; border-radius: 8px;
    font-size: 13px; opacity: 0; pointer-events: none; transition: opacity .2s;
  }
  .toast.show { opacity: .95; }
  #view-list, #view-cards { display: none; }
  #view-list.active, #view-cards.active { display: block; }
</style>
</head>
<body>
<header>
  <h1>🏠 買方配案看板</h1>
  <div class="tabs" id="tabs"></div>
</header>
<main>
  <div id="view-list">
    <div class="toolbar">
      <button class="refresh-btn" onclick="loadManifest()">🔄 重新整理</button>
    </div>
    <div id="list"></div>
  </div>
  <div id="view-cards">
    <div class="toolbar">
      <button class="back-btn" onclick="showList()">← 返回列表</button>
      <button class="copyall-btn" onclick="copyAll()">📋 全部複製</button>
    </div>
    <div id="cardsMeta" class="row-sub" style="margin-bottom:10px;"></div>
    <div class="grid" id="grid"></div>
    <div class="empty" id="gridEmpty" style="display:none;">卡片都處理完了 🎉</div>
  </div>
</main>
<div class="toast" id="toast"></div>

<script>
let manifestData = null;
let currentGroup = null;
let currentKey = null;
let currentFile = null;

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 1400);
}

async function copyText(text) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) { /* fall through */ }
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    if (ok) return true;
  } catch (e) { /* fall through */ }
  window.prompt('自動複製失敗，長按下面文字手動複製：', text);
  return false;
}

async function loadManifest() {
  const res = await fetch('/api/manifest');
  manifestData = (await res.json()).groups;
  renderTabs();
}

function renderTabs() {
  const tabsEl = document.getElementById('tabs');
  const groupNames = Object.keys(manifestData);
  tabsEl.innerHTML = '';
  if (!groupNames.length) {
    tabsEl.innerHTML = '<span style="color:var(--muted);font-size:14px;">還沒有任何查詢結果</span>';
    return;
  }
  if (!currentGroup || !groupNames.includes(currentGroup)) {
    currentGroup = groupNames[0];
  }
  for (const g of groupNames) {
    const btn = document.createElement('button');
    btn.className = 'tab' + (g === currentGroup ? ' active' : '');
    btn.textContent = g + '（' + manifestData[g].length + '）';
    btn.onclick = () => { currentGroup = g; renderTabs(); showList(); };
    tabsEl.appendChild(btn);
  }
  renderList();
}

function renderList() {
  const listEl = document.getElementById('list');
  const rows = manifestData[currentGroup] || [];
  listEl.innerHTML = '';
  if (!rows.length) {
    listEl.innerHTML = '<div class="empty">這個群組還沒有結果</div>';
    return;
  }
  for (const r of rows) {
    const row = document.createElement('div');
    row.className = 'row';
    row.onclick = () => openCards(r);
    const ts = (r.timestamp || '').replace('T', ' ');
    row.innerHTML = `
      <div class="row-main">
        <div class="row-title">${escapeHtml(r.customer)}／${escapeHtml(r.need)}</div>
        <div class="row-sub">${ts}</div>
        ${r.is_full ? '' : '<span class="warn-chip">僅新案，非完整清單</span>'}
      </div>
      <div class="badge"><span class="n">${r.hits}</span> 筆</div>
    `;
    listEl.appendChild(row);
  }
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function showList() {
  document.getElementById('view-list').classList.add('active');
  document.getElementById('view-cards').classList.remove('active');
}

function dismissedKey(file) { return 'dismissed:' + file; }

function getDismissed(file) {
  try { return new Set(JSON.parse(localStorage.getItem(dismissedKey(file)) || '[]')); }
  catch (e) { return new Set(); }
}

function saveDismissed(file, set) {
  localStorage.setItem(dismissedKey(file), JSON.stringify([...set]));
}

async function openCards(row) {
  currentKey = row.key;
  currentFile = row.file;
  document.getElementById('cardsMeta').textContent =
    row.customer + '／' + row.need + '　共 ' + row.hits + ' 筆' +
    (row.is_full ? '' : '（僅新案，非完整清單）');
  const res = await fetch('/api/cards?file=' + encodeURIComponent(row.file));
  const data = await res.json();
  renderCards(data.blocks || []);
  document.getElementById('view-list').classList.remove('active');
  document.getElementById('view-cards').classList.add('active');
}

function renderCards(blocks) {
  const grid = document.getElementById('grid');
  const dismissed = getDismissed(currentFile);
  grid.innerHTML = '';
  let shown = 0;
  blocks.forEach((text, idx) => {
    if (dismissed.has(idx)) return;
    shown++;
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.idx = idx;

    const dismissBtn = document.createElement('button');
    dismissBtn.className = 'dismiss-btn';
    dismissBtn.textContent = '✕';
    dismissBtn.title = '不要這筆';
    dismissBtn.onclick = () => {
      const d = getDismissed(currentFile);
      d.add(idx);
      saveDismissed(currentFile, d);
      card.remove();
      checkEmpty();
    };

    const pre = document.createElement('pre');
    pre.textContent = text;

    const copyBtn = document.createElement('button');
    copyBtn.className = 'card-copy-btn';
    copyBtn.textContent = '📋 複製這筆';
    copyBtn.onclick = async () => {
      await copyText(text);
      copyBtn.textContent = '✓ 已複製';
      copyBtn.classList.add('copied');
      setTimeout(() => { copyBtn.textContent = '📋 複製這筆'; copyBtn.classList.remove('copied'); }, 1200);
    };

    card.appendChild(dismissBtn);
    card.appendChild(pre);
    card.appendChild(copyBtn);
    grid.appendChild(card);
  });
  checkEmpty();
}

function checkEmpty() {
  const grid = document.getElementById('grid');
  document.getElementById('gridEmpty').style.display = grid.children.length ? 'none' : 'block';
}

async function copyAll() {
  const grid = document.getElementById('grid');
  const texts = [...grid.querySelectorAll('.card pre')].map(p => p.textContent);
  if (!texts.length) { toast('沒有可複製的卡片'); return; }
  await copyText(texts.join('\n\n'));
  toast('已複製 ' + texts.length + ' 筆到剪貼簿');
}

loadManifest().then(showList);
</script>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser(description="買方配案結果看板（本機網頁）")
    ap.add_argument("--port", type=int, default=5001)
    ap.add_argument("--host", default="0.0.0.0", help="預設 0.0.0.0 讓手機連得到；只想自己電腦看就設 127.0.0.1")
    args = ap.parse_args()
    print(f"[INFO] 買方配案看板啟動：http://{args.host}:{args.port}（同 WiFi 手機也連得到）")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
