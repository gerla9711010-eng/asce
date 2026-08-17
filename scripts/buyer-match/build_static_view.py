"""把 `run_yc_links.py` 寫的 output/latest_run.json 轉成單檔靜態看板 HTML。

給 `~/kh-market-tool/update.py --deploy-only` 撿去部署到
https://yc-tools.pages.dev/buyer-match/（發布鏈路見 docs/reference.md）。
只依賴標準函式庫＋純 HTML/CSS/JS（no CDN），deploy 出去就是單一自包含檔案。

2026-08-17：加分頁籤（按群組 A買／B買／C買／其他切換，不要一頁塞所有客戶）、
複製內容改標題＋開價＋連結（不是只有裸連結）、多筆複製項目間留空行（不要擠在一起）。
"""

from __future__ import annotations

import html
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
RUN_JSON_PATH = OUTPUT_DIR / "latest_run.json"
HTML_PATH = OUTPUT_DIR / "配案看板.html"


def _esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def _js_str(s: str) -> str:
    """安全內嵌進 <script> 的 JSON 字串（擋掉 </script 提前關閉腳本區塊）。"""
    return json.dumps(s, ensure_ascii=False).replace("</", "<\\/")


def _item_copy_text(c: dict) -> str:
    """單一案件的複製內容：標題（含大樓/社區名）、開價、連結，一行一個。"""
    title = c.get("full_title") or c.get("title") or ""
    lines = [title]
    if c.get("price"):
        lines.append(f"開價 {c['price']}")
    lines.append(c.get("yc_link", ""))
    return "\n".join(lines)


def _section_html(cust: str, need: str, candidates: list[dict]) -> tuple[str, list[str]]:
    """回傳 (這個子條件的 HTML, 這個子條件裡每筆找到案件的複製文字清單)。"""
    found = [c for c in candidates if c.get("yc_link")]
    rows = []
    for c in candidates:
        display_title = _esc(c.get("full_title") or c.get("title", ""))
        subtitle = _esc(c.get("subtitle", ""))
        link = c.get("yc_link")
        if link:
            link_esc = _esc(link)
            price = _esc(c.get("price", ""))
            price_html = f'<span class="price">開價 {price}</span>' if price else ""
            new_badge = '<span class="badge-new">🆕 新</span>' if c.get("is_new") else ""
            item_copy = _esc(_item_copy_text(c))
            rows.append(f"""
      <div class="row row-found">
        <div class="row-main">
          {new_badge}<a href="{link_esc}" target="_blank" rel="noopener">{display_title}</a>
          <span class="subtitle">{subtitle}{(' ｜ ' + price_html) if price_html else ''}</span>
        </div>
        <button class="copy-btn" data-copy="{item_copy}">複製</button>
      </div>""")
        else:
            note = _esc(c.get("note", "") or "沒有永慶連結")
            rows.append(f"""
      <div class="row row-empty">
        <div class="row-main">
          <span class="title-empty">{display_title}</span>
          <span class="subtitle">{subtitle}</span>
        </div>
        <span class="note">{note}</span>
      </div>""")

    item_texts = [_item_copy_text(c) for c in found]
    section_copy_payload = _esc("\n\n".join(item_texts))
    new_count = sum(1 for c in found if c.get("is_new"))
    header_note = f"找到 {len(found)}／{len(candidates)} 筆" if candidates else "沒有候選"
    if new_count:
        header_note += f"，🆕 {new_count} 筆新"

    section_html = f"""
  <section class="need-block">
    <div class="need-header">
      <div>
        <strong>{_esc(cust)}</strong>
        <span class="need-name">／{_esc(need)}</span>
        <span class="count">{header_note}</span>
      </div>
      {f'<button class="copy-btn copy-batch" data-copy="{section_copy_payload}">整批複製（{len(found)}筆）</button>' if found else ''}
    </div>
    <div class="rows">{''.join(rows)}</div>
  </section>"""
    return section_html, item_texts


def build() -> Path:
    if not RUN_JSON_PATH.exists():
        raise FileNotFoundError(f"找不到 {RUN_JSON_PATH}，要先跑過一次 run_yc_links.py")

    data = json.loads(RUN_JSON_PATH.read_text(encoding="utf-8"))
    generated_at = data.get("generated_at", "")
    groups = data.get("groups", [])

    total_candidates = 0
    total_found = 0
    total_new = 0
    tabs_html = []
    panels_html = []
    group_payloads = {}  # group_name -> {"text": str, "count": int}

    for gi, g in enumerate(groups):
        group_name = g.get("group", "") or "（未命名）"
        sections_html = []
        group_item_texts = []
        for cust_job in g.get("customers", []):
            cust = cust_job.get("customer", "")
            need = cust_job.get("need", "")
            candidates = cust_job.get("candidates", [])
            total_candidates += len(candidates)
            found = [c for c in candidates if c.get("yc_link")]
            total_found += len(found)
            total_new += sum(1 for c in found if c.get("is_new"))
            section_html, item_texts = _section_html(cust, need, candidates)
            sections_html.append(section_html)
            if item_texts:
                group_item_texts.append(f"【{cust}／{need}】\n" + "\n\n".join(item_texts))

        active = " active" if gi == 0 else ""
        hidden = "" if gi == 0 else " hidden"
        tabs_html.append(
            f'<button class="tab-btn{active}" data-group="{_esc(group_name)}">{_esc(group_name)}</button>'
        )
        body = "\n".join(sections_html) if sections_html else '<p class="empty">這組沒有客戶資料。</p>'
        panels_html.append(
            f'<div class="group-panel" data-group="{_esc(group_name)}"{hidden}>{body}</div>'
        )
        group_found_count = sum(
            len([c for c in cj.get("candidates", []) if c.get("yc_link")])
            for cj in g.get("customers", [])
        )
        group_payloads[group_name] = {
            "text": "\n\n".join(group_item_texts),
            "count": group_found_count,
        }

    new_summary = f"，🆕 {total_new} 筆新出現" if total_new else ""
    first_group = groups[0].get("group", "") if groups else ""
    first_payload = group_payloads.get(first_group, {"text": "", "count": 0})

    tabs_block = f'<div class="tabs">{"".join(tabs_html)}</div>' if len(groups) > 1 else ""
    panels_block = "\n".join(panels_html) if panels_html else '<p class="empty">這輪沒有任何子條件有候選資料。</p>'
    payloads_json = _js_str(json.dumps(group_payloads, ensure_ascii=False))

    html_doc = f"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>買方配案看板</title>
<style>
  :root {{
    --bg: #0f1216; --panel: #171b21; --border: #262c35; --text: #e8ebef;
    --muted: #8b93a1; --accent: #4f8cff; --found: #35c46a; --empty: #4a5261;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px 16px 80px; background: var(--bg); color: var(--text);
    font-family: -apple-system, "Segoe UI", "Noto Sans TC", sans-serif; line-height: 1.5;
  }}
  .wrap {{ max-width: 860px; margin: 0 auto; }}
  h1 {{ font-size: 1.3rem; margin: 0 0 4px; }}
  .meta {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 16px; }}
  .tabs {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px; }}
  .tab-btn {{
    background: var(--panel); color: var(--muted); border: 1px solid var(--border);
    border-radius: 8px; padding: 7px 14px; font-size: 0.9rem; cursor: pointer;
  }}
  .tab-btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .toolbar {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 20px; }}
  .copy-btn {{
    background: var(--accent); color: #fff; border: none; border-radius: 6px;
    padding: 6px 12px; font-size: 0.85rem; cursor: pointer; white-space: nowrap;
  }}
  .copy-btn:active {{ opacity: 0.7; }}
  .copy-btn.copied {{ background: var(--found); }}
  .copy-all {{ font-size: 0.95rem; padding: 8px 16px; }}
  .need-block {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 14px; margin-bottom: 14px;
  }}
  .need-header {{
    display: flex; justify-content: space-between; align-items: center;
    flex-wrap: wrap; gap: 8px; margin-bottom: 8px;
  }}
  .need-name {{ color: var(--muted); }}
  .count {{ color: var(--muted); font-size: 0.8rem; margin-left: 8px; }}
  .row {{
    display: flex; justify-content: space-between; align-items: center;
    gap: 10px; padding: 7px 0; border-top: 1px solid var(--border);
  }}
  .row:first-child {{ border-top: none; }}
  .row-main {{ display: flex; flex-direction: column; min-width: 0; }}
  .row-main a {{ color: var(--found); text-decoration: none; font-weight: 500; }}
  .badge-new {{
    display: inline-block; background: #ff6b3d; color: #fff; font-size: 0.7rem;
    font-weight: 600; padding: 1px 6px; border-radius: 999px; margin-right: 6px;
  }}
  .row-main a:hover {{ text-decoration: underline; }}
  .title-empty {{ color: var(--muted); }}
  .subtitle {{ color: var(--muted); font-size: 0.8rem; }}
  .price {{ color: var(--muted); font-size: 0.8rem; }}
  .note {{ color: var(--empty); font-size: 0.8rem; white-space: nowrap; }}
  .empty {{ color: var(--muted); }}
  #fallback {{
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,.6);
    align-items: center; justify-content: center; padding: 20px;
  }}
  #fallback.show {{ display: flex; }}
  #fallback textarea {{
    width: 100%; max-width: 600px; height: 60vh; background: var(--panel);
    color: var(--text); border: 1px solid var(--border); border-radius: 8px; padding: 12px;
  }}
  #fallback .box {{ display: flex; flex-direction: column; gap: 8px; max-width: 600px; width: 100%; }}
  #fallback p {{ color: var(--muted); font-size: 0.85rem; margin: 0; }}
  #fallback button {{ align-self: flex-end; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>買方配案看板</h1>
  <div class="meta">資料更新於 {_esc(generated_at)} ｜ 共 {total_candidates} 筆候選，{total_found} 筆有永慶連結{new_summary}</div>
  {tabs_block}
  <div class="toolbar">
    <button id="copy-all-btn" class="copy-btn copy-all" data-copy="{_esc(first_payload['text'])}">複製全部連結（{_esc(first_group)}，{first_payload['count']}筆）</button>
  </div>
  {panels_block}
</div>

<div id="fallback">
  <div class="box">
    <p>這個瀏覽器擋掉了自動複製，長按下面文字框 → 全選 → 拷貝：</p>
    <textarea id="fallback-text" readonly></textarea>
    <button class="copy-btn" onclick="document.getElementById('fallback').classList.remove('show')">關閉</button>
  </div>
</div>

<script>
const GROUP_PAYLOADS = JSON.parse({payloads_json});

function doCopy(btn, text) {{
  navigator.clipboard.writeText(text).then(() => {{
    const orig = btn.textContent;
    btn.textContent = '已複製 ✓';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 1500);
  }}).catch(() => {{
    const ta = document.getElementById('fallback-text');
    ta.value = text;
    document.getElementById('fallback').classList.add('show');
    ta.focus();
    ta.select();
  }});
}}

document.querySelectorAll('.copy-btn[data-copy]').forEach(btn => {{
  btn.addEventListener('click', () => doCopy(btn, btn.getAttribute('data-copy')));
}});

document.querySelectorAll('.tab-btn').forEach(btn => {{
  btn.addEventListener('click', () => {{
    const g = btn.dataset.group;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.group-panel').forEach(p => {{ p.hidden = p.dataset.group !== g; }});
    const payload = GROUP_PAYLOADS[g] || {{text: '', count: 0}};
    const copyAllBtn = document.getElementById('copy-all-btn');
    copyAllBtn.setAttribute('data-copy', payload.text);
    copyAllBtn.textContent = `複製全部連結（${{g}}，${{payload.count}}筆）`;
  }});
}});
</script>
</body>
</html>
"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    HTML_PATH.write_text(html_doc, encoding="utf-8")
    return HTML_PATH


if __name__ == "__main__":
    path = build()
    print(f"已產生：{path}")
