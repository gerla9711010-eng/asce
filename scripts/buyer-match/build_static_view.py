"""把 `run_yc_links.py` 寫的 output/latest_run.json 轉成單檔靜態看板 HTML。

給 `~/kh-market-tool/update.py --deploy-only` 撿去部署到
https://yc-tools.pages.dev/buyer-match/（發布鏈路見 docs/reference.md）。
只依賴標準函式庫＋純 HTML/CSS/JS（no CDN），deploy 出去就是單一自包含檔案。
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


def _section_html(group: str, cust: str, need: str, candidates: list[dict]) -> str:
    found = [c for c in candidates if c.get("yc_link")]
    rows = []
    for c in candidates:
        title = _esc(c.get("title", ""))
        subtitle = _esc(c.get("subtitle", ""))
        link = c.get("yc_link")
        if link:
            link_esc = _esc(link)
            rows.append(f"""
      <div class="row row-found">
        <div class="row-main">
          <a href="{link_esc}" target="_blank" rel="noopener">{title}</a>
          <span class="subtitle">{subtitle}</span>
        </div>
        <button class="copy-btn" data-copy="{link_esc}">複製連結</button>
      </div>""")
        else:
            note = _esc(c.get("note", "") or "沒有永慶連結")
            rows.append(f"""
      <div class="row row-empty">
        <div class="row-main">
          <span class="title-empty">{title}</span>
          <span class="subtitle">{subtitle}</span>
        </div>
        <span class="note">{note}</span>
      </div>""")

    links_block = "\n".join(c["yc_link"] for c in found)
    section_copy_payload = _esc(links_block)
    header_note = f"找到 {len(found)}／{len(candidates)} 筆" if candidates else "沒有候選"

    return f"""
  <section class="need-block">
    <div class="need-header">
      <div>
        <span class="badge">{_esc(group)}</span>
        <strong>{_esc(cust)}</strong>
        <span class="need-name">／{_esc(need)}</span>
        <span class="count">{header_note}</span>
      </div>
      {f'<button class="copy-btn copy-batch" data-copy="{section_copy_payload}">整批複製（{len(found)}筆）</button>' if found else ''}
    </div>
    <div class="rows">{''.join(rows)}</div>
  </section>"""


def build() -> Path:
    if not RUN_JSON_PATH.exists():
        raise FileNotFoundError(f"找不到 {RUN_JSON_PATH}，要先跑過一次 run_yc_links.py")

    data = json.loads(RUN_JSON_PATH.read_text(encoding="utf-8"))
    generated_at = data.get("generated_at", "")
    groups = data.get("groups", [])

    all_found_lines = []
    sections_html = []
    total_candidates = 0
    total_found = 0
    for g in groups:
        group_name = g.get("group", "")
        for cust_job in g.get("customers", []):
            cust = cust_job.get("customer", "")
            need = cust_job.get("need", "")
            candidates = cust_job.get("candidates", [])
            total_candidates += len(candidates)
            found = [c for c in candidates if c.get("yc_link")]
            total_found += len(found)
            if found:
                all_found_lines.append(f"【{cust}／{need}】")
                all_found_lines.extend(f"{c['title']} {c['yc_link']}" for c in found)
                all_found_lines.append("")
            sections_html.append(_section_html(group_name, cust, need, candidates))

    all_found_payload = _esc("\n".join(all_found_lines).strip())
    body_sections = "\n".join(sections_html) if sections_html else '<p class="empty">這輪沒有任何子條件有候選資料。</p>'

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
  .badge {{
    background: var(--border); color: var(--muted); font-size: 0.75rem;
    padding: 2px 8px; border-radius: 999px; margin-right: 6px;
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
  .row-main a:hover {{ text-decoration: underline; }}
  .title-empty {{ color: var(--muted); }}
  .subtitle {{ color: var(--muted); font-size: 0.8rem; }}
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
  <div class="meta">資料更新於 {_esc(generated_at)} ｜ 共 {total_candidates} 筆候選，{total_found} 筆有永慶連結</div>
  <div class="toolbar">
    <button class="copy-btn copy-all" data-copy="{all_found_payload}">複製全部連結（{total_found}筆）</button>
  </div>
  {body_sections}
</div>

<div id="fallback">
  <div class="box">
    <p>這個瀏覽器擋掉了自動複製，長按下面文字框 → 全選 → 拷貝：</p>
    <textarea id="fallback-text" readonly></textarea>
    <button class="copy-btn" onclick="document.getElementById('fallback').classList.remove('show')">關閉</button>
  </div>
</div>

<script>
document.querySelectorAll('.copy-btn[data-copy]').forEach(btn => {{
  btn.addEventListener('click', async () => {{
    const text = btn.getAttribute('data-copy');
    try {{
      await navigator.clipboard.writeText(text);
      const orig = btn.textContent;
      btn.textContent = '已複製 ✓';
      btn.classList.add('copied');
      setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 1500);
    }} catch (e) {{
      const ta = document.getElementById('fallback-text');
      ta.value = text;
      document.getElementById('fallback').classList.add('show');
      ta.focus();
      ta.select();
    }}
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
