/* 買方配案系統 — 產生彙總頁
 * 用法: node scripts/buyer-match/build_page.js <data.json> <out.html>
 * data.json = collect.js 跑完 FDBM.dump() 解 base64 後的內容
 */
const fs = require('fs');

const dataPath = process.argv[2] || 'scripts/buyer-match/data.json';
const outPath = process.argv[3] || 'scripts/buyer-match/buyer-match.html';
const R = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* 複製訊息格式
 * 大樓  : 案名 / 社區名稱 / 總價 / 單價 / 網址
 * 其餘  : 案名 / 路名+類型(樓層) / 總價 / 網址
 * 每欄一行，開頭加 "- "
 */
function copyText(it) {
  const L = [];
  L.push(it.name || '(無案名)');
  if (it.kind === '大樓') {
    if (it.community) L.push(it.community);
    L.push(it.totalPrice);
    if (it.unitPrice) L.push(it.unitPrice);
  } else {
    const floor = it.floor ? '(' + it.floor + ')' : '';
    L.push((it.road || '') + (it.kind || '') + floor);
    L.push(it.totalPrice);
  }
  L.push(it.url);
  return L.filter(Boolean).map((x) => '- ' + x).join('\n');
}

/* 收集器存的是 UTC ISO，顯示要換成台灣時間，不然看起來像 8 小時前跑的 */
function localTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso).replace('T', ' ').slice(0, 16);
  const p = (n) => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
}

/* 同一間房子會在永慶/台慶/永義/有巢氏各有一個官網連結 —— 每間只留一個，優先永慶。
   沒有永慶刊登的（別家加盟店的案子）就往後遞補，不要整間漏掉。 */
const BADGE_PRIORITY = ['永慶', '台慶', '永義', '有巢氏'];
const rank = (b) => { const i = BADGE_PRIORITY.indexOf(b); return i < 0 ? 99 : i; };
function oneLinkPerProperty(items) {
  const by = {};
  for (const it of items) { const k = it.fp || it.url; (by[k] = by[k] || []).push(it); }
  return Object.keys(by).map((k) => by[k].slice().sort((a, b) => rank(a.badge) - rank(b.badge))[0]);
}

/* 攤平成 folder > client > demand > items */
const folders = {};
for (const o of R.out || []) {
  if (!o.items || !o.items.length) continue;
  const f = (folders[o.folder] = folders[o.folder] || {});
  const c = (f[o.client] = f[o.client] || {});
  c[o.demand] = oneLinkPerProperty((c[o.demand] || []).concat(o.items));
}
const ORDER = ['A買', 'B買', 'C買'];

let totalItems = 0, totalDemands = 0, totalClients = 0;
let body = '';
for (const fname of ORDER) {
  const f = folders[fname];
  if (!f) continue;
  const clientNames = Object.keys(f);
  let fCount = 0, fHtml = '';
  for (const cname of clientNames) {
    totalClients++;
    const demands = f[cname];
    let cCount = 0, cHtml = '';
    for (const dname of Object.keys(demands)) {
      totalDemands++;
      const items = demands[dname].slice().sort((a, b) => a.whenDays - b.whenDays);
      cCount += items.length;
      const rows = items.map((it) => {
        const t = copyText(it);
        return `<li class="item" data-copy="${esc(t)}">
  <div class="badge b-${esc(it.badge)}">${esc(it.badge)}</div>
  <div class="meta">
    <a class="name" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.name || '(無案名)')}</a>${it.isNew ? '<span class="new">NEW</span>' : ''}
    <div class="sub">${esc([it.district, it.road, it.community].filter(Boolean).join(' · '))}</div>
    <div class="sub">${esc([it.kind, it.floor, it.layout, it.age].filter(Boolean).join(' · '))}</div>
    <div class="price">${esc(it.totalPrice)}${it.unitPrice ? ' <span class="unit">' + esc(it.unitPrice) + '</span>' : ''}</div>
  </div>
  <div class="right"><span class="when">${esc(it.when)}</span><button class="cp" type="button">複製</button></div>
</li>`;
      }).join('\n');
      cHtml += `<section class="demand">
  <h4>${esc(dname)} <span class="n">${items.length}</span>
    <button class="cp grp" type="button" data-copy="${esc(items.map(copyText).join('\n\n'))}">複製這組</button></h4>
  <ul class="items">${rows}</ul>
</section>`;
    }
    totalItems += cCount;
    fCount += cCount;
    fHtml += `<details class="client">
  <summary>${esc(cname)} <span class="n">${cCount}</span></summary>
  <div class="cbody">
    <button class="cp grp" type="button" data-copy="${esc(Object.keys(demands).map((d) => demands[d].map(copyText).join('\n\n')).join('\n\n'))}">複製此客戶全部</button>
    ${cHtml}
  </div>
</details>`;
  }
  body += `<details class="folder" open>
  <summary><b>${esc(fname)}</b> <span class="n">${clientNames.length} 位客戶 · ${fCount} 筆</span></summary>
  ${fHtml}
</details>`;
}

const allText = [];
for (const fname of ORDER) {
  const f = folders[fname];
  if (!f) continue;
  allText.push('■ ' + fname);
  for (const cname of Object.keys(f)) {
    allText.push('▍' + cname);
    for (const dname of Object.keys(f[cname])) {
      allText.push('〔' + dname + '〕');
      allText.push(f[cname][dname].slice().sort((a, b) => a.whenDays - b.whenDays).map(copyText).join('\n\n'));
    }
  }
}

const html = `<title>買方配案</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--fg:#1b1b19;--dim:#6b6b66;--line:#e3e3de;--accent:#0b7285;--chip:#eef4f5}
:root:not([data-theme="light"]){}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#16171a;--card:#1e2024;--fg:#e8e8e4;--dim:#9a9a94;--line:#2e3136;--accent:#4dd0e1;--chip:#22303350}}
:root[data-theme="dark"]{--bg:#16171a;--card:#1e2024;--fg:#e8e8e4;--dim:#9a9a94;--line:#2e3136;--accent:#4dd0e1;--chip:#223033}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Noto Sans TC","Segoe UI",sans-serif;padding:12px;max-width:900px;margin:0 auto}
h1{font-size:19px;margin:4px 0 2px}
.top{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:5;margin-bottom:10px}
.stat{color:var(--dim);font-size:13px}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:7px;padding:5px 11px}
button.primary{background:var(--accent);color:#fff;border-color:transparent;font-weight:600}
button:active{transform:scale(.97)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;overflow:hidden}
summary{cursor:pointer;padding:11px 13px;font-size:15px;user-select:none}
.folder>summary{font-size:16px;background:var(--chip)}
.client>summary{border-top:1px solid var(--line)}
.n{color:var(--dim);font-size:12px;font-weight:400}
.cbody{padding:4px 11px 12px}
.demand{margin:10px 0}
.demand h4{font-size:14px;margin:0 0 6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--accent)}
.items{list-style:none;margin:0;padding:0}
.item{display:flex;gap:9px;align-items:flex-start;padding:9px 0;border-top:1px dashed var(--line)}
.badge{flex:0 0 auto;font-size:11px;padding:2px 6px;border-radius:5px;background:var(--chip);color:var(--dim);margin-top:2px}
.meta{flex:1 1 auto;min-width:0}
.name{color:var(--fg);font-weight:600;text-decoration:none;word-break:break-all}
.name:hover{color:var(--accent)}
.new{background:#e8590c;color:#fff;font-size:10px;font-weight:700;padding:1px 5px;border-radius:4px;margin-left:6px;vertical-align:2px}
.sub{color:var(--dim);font-size:12.5px}
.price{font-weight:700;margin-top:2px}
.unit{font-weight:400;color:var(--dim);font-size:12.5px}
.right{flex:0 0 auto;text-align:right;display:flex;flex-direction:column;gap:5px;align-items:flex-end}
.when{color:var(--dim);font-size:12px;white-space:nowrap}
.cp{font-size:12.5px;padding:4px 10px}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--accent);color:#fff;padding:8px 16px;border-radius:20px;opacity:0;transition:.2s;pointer-events:none;font-size:14px}
.toast.on{opacity:1}
@media(max-width:520px){.item{flex-wrap:wrap}.right{flex-direction:row;width:100%;justify-content:space-between}}
</style>
<div class="top">
  <h1>買方配案</h1>
  <div class="stat">${totalClients} 位客戶 · ${totalDemands} 個客需 · <b>${totalItems}</b> 筆官網連結　|　更新 ${esc(localTime(R.finishedAt || R.startedAt))}</div>
  <div style="margin-top:7px"><button class="cp primary" type="button" data-copy="${esc(allText.join('\n\n'))}">一鍵全部複製</button></div>
</div>
${body || '<p class="stat">沒有抓到任何官網連結。</p>'}
<div class="toast" id="t">已複製</div>
<script>
const toast=document.getElementById('t');
function show(m){toast.textContent=m;toast.classList.add('on');setTimeout(()=>toast.classList.remove('on'),1100)}
async function cp(text){try{await navigator.clipboard.writeText(text)}catch(e){const a=document.createElement('textarea');a.value=text;document.body.appendChild(a);a.select();document.execCommand('copy');a.remove()}show('已複製')}
document.addEventListener('click',e=>{const b=e.target.closest('button.cp');if(!b)return;
 const t=b.dataset.copy!==undefined?b.dataset.copy:(b.closest('.item')||{}).dataset?.copy;
 if(t)cp(t)});
</script>`;

fs.writeFileSync(outPath, html, 'utf8');
console.log('wrote ' + outPath + ' — ' + totalItems + ' items / ' + totalDemands + ' demands / ' + totalClients + ' clients');
