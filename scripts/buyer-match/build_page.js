/* 買方配案系統 — 產生彙總頁
 * 用法: node scripts/buyer-match/build_page.js <data.json> <out.html>
 * data.json = collect.js 跑完 FDBM.dump() 解 base64 後的內容
 */
const fs = require('fs');

const args = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const dataPath = args[0] || 'scripts/buyer-match/data.json';
const outPath = args[1] || 'scripts/buyer-match/buyer-match.html';
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

/* --mask：公開網址用的版本，客戶名打碼。「66604陳漢強」→「66604陳○○」——編號＋姓氏自己認得出是誰，
   外人對不到本人。客需名稱裡出現同一個名字也一起換掉。桌面那份不加 --mask，維持全名 */
const MASK = process.argv.includes('--mask');
const maskName = (s) => {
  const m = String(s).match(/^(\d*)(.*)$/);
  return m[2] ? m[1] + m[2][0] + '○'.repeat(m[2].length - 1) : m[1];
};
if (MASK) {
  for (const o of R.out || []) {
    const name = String(o.client).replace(/^\d*/, '');
    const masked = maskName(o.client);
    if (name) o.demand = String(o.demand).split(name).join(masked.replace(/^\d*/, ''));
    o.client = masked;
  }
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

let totalItems = 0, totalDemands = 0, totalClients = 0, totalNew = 0;
const newBadge = (n) => n ? `<span class="newn">NEW ${n}</span>` : '';
let body = '';
for (const fname of ORDER) {
  const f = folders[fname];
  if (!f) continue;
  const clientNames = Object.keys(f);
  let fCount = 0, fNew = 0, fHtml = '';
  for (const cname of clientNames) {
    totalClients++;
    const demands = f[cname];
    let cCount = 0, cNew = 0, cHtml = '';
    for (const dname of Object.keys(demands)) {
      totalDemands++;
      const items = demands[dname].slice().sort((a, b) => a.whenDays - b.whenDays);
      cCount += items.length;
      const dNew = items.filter((it) => it.isNew).length;
      cNew += dNew;
      const rows = items.map((it) => {
        const t = copyText(it);
        return `<li class="item${it.isNew ? ' isnew' : ''}" data-copy="${esc(t)}">
  <label class="pickw"><input type="checkbox" class="pick" aria-label="選取這筆"></label>
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
      cHtml += `<section class="demand${dNew ? ' hasnew' : ''}">
  <h4>${esc(dname)} <span class="n">${items.length}</span>${newBadge(dNew)}
    <button class="cp grp" type="button" data-copy="${esc(items.map(copyText).join('\n\n'))}">複製這組</button></h4>
  <ul class="items">${rows}</ul>
</section>`;
    }
    totalItems += cCount;
    fCount += cCount;
    fNew += cNew;
    totalNew += cNew;
    fHtml += `<details class="client${cNew ? ' hasnew' : ''}">
  <summary>${esc(cname)} <span class="n">${cCount}</span>${newBadge(cNew)}</summary>
  <div class="cbody">
    <button class="cp grp" type="button" data-copy="${esc(Object.keys(demands).map((d) => demands[d].map(copyText).join('\n\n')).join('\n\n'))}">複製此客戶全部</button>
    ${cHtml}
  </div>
</details>`;
  }
  body += `<details class="folder${fNew ? ' hasnew' : ''}">
  <summary><b>${esc(fname)}</b> <span class="n">${clientNames.length} 位客戶 · ${fCount} 筆</span>${newBadge(fNew)}</summary>
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

const html = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>買方配案</title>
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
.newn{background:#e8590c;color:#fff;font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px;margin-left:8px}
.item.isnew{border-left:4px solid #e8590c;padding-left:8px;background:#e8590c12}
.demand.hasnew>h4{border-left:4px solid #e8590c;padding-left:8px}
.sub{color:var(--dim);font-size:12.5px}
.price{font-weight:700;margin-top:2px}
.unit{font-weight:400;color:var(--dim);font-size:12.5px}
.right{flex:0 0 auto;text-align:right;display:flex;flex-direction:column;gap:5px;align-items:flex-end}
.when{color:var(--dim);font-size:12px;white-space:nowrap}
.cp{font-size:12.5px;padding:4px 10px}
.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:var(--accent);color:#fff;padding:8px 16px;border-radius:20px;opacity:0;transition:.2s;pointer-events:none;font-size:14px}
.toast.on{opacity:1}
.pickw{flex:0 0 auto;display:flex;align-items:center;padding:2px 2px 0 0;cursor:pointer}
.pick{width:20px;height:20px;accent-color:var(--accent);cursor:pointer;margin:0}
.item.sel{background:color-mix(in srgb,var(--accent) 12%,transparent)}
.bar{position:fixed;left:0;right:0;bottom:0;background:var(--card);border-top:1px solid var(--line);padding:10px 12px calc(10px + env(safe-area-inset-bottom));display:none;gap:8px;align-items:center;justify-content:center;z-index:9;box-shadow:0 -4px 14px #0002}
.bar.on{display:flex}
.bar b{margin-right:4px}
body.hasbar{padding-bottom:80px}
.modal{position:fixed;inset:0;background:#0008;display:none;align-items:center;justify-content:center;z-index:20;padding:16px}
.modal.on{display:flex}
.modal .box{background:var(--card);border-radius:12px;padding:14px;width:100%;max-width:560px}
.modal textarea{width:100%;height:46vh;font:13px/1.5 monospace;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:8px;padding:8px}
.modal p{margin:0 0 8px;font-size:14px}
.pv{position:fixed;inset:0;background:#0008;display:none;z-index:15;align-items:flex-end;justify-content:center}
.pv.on{display:flex}
.pv .sheet{background:var(--card);width:100%;max-width:900px;height:88vh;border-radius:14px 14px 0 0;display:flex;flex-direction:column;overflow:hidden}
.pv .ph{display:flex;align-items:center;gap:8px;padding:9px 12px;border-bottom:1px solid var(--line)}
.pv .ph b{flex:1 1 auto;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pv .ph a{font-size:13px;color:var(--accent);white-space:nowrap}
.pv iframe{flex:1 1 auto;width:100%;border:0;background:#fff}
@media(max-width:520px){.item{flex-wrap:wrap}.right{flex-direction:row;width:100%;justify-content:space-between}}
</style>
<div class="top">
  <h1>買方配案</h1>
  <div class="stat">${totalClients} 位客戶 · ${totalDemands} 個客需 · <b>${totalItems}</b> 筆官網連結${totalNew ? ' · <span class="newn" style="margin-left:0">本次新增 ' + totalNew + '</span>' : ''}　|　更新 ${esc(localTime(R.finishedAt || R.startedAt))}</div>
  <div style="margin-top:7px"><button class="cp primary" type="button" data-copy="${esc(allText.join('\n\n'))}">一鍵全部複製</button></div>
</div>
${body || '<p class="stat">沒有抓到任何官網連結。</p>'}
<div class="toast" id="t">已複製</div>
<div class="bar" id="bar"><b id="cnt">已選 0 筆</b><button class="primary" type="button" id="cpSel">複製選取</button><button type="button" id="clrSel">清除</button></div>
<div class="pv" id="pv"><div class="sheet"><div class="ph"><b id="pvt"></b><a id="pvo" href="#" target="_blank" rel="noopener">另開視窗</a><button type="button" id="pvx">關閉</button></div><iframe id="pvf" title="物件預覽" referrerpolicy="no-referrer"></iframe></div></div>
<div class="modal" id="m"><div class="box"><p>這個畫面不允許自動複製。文字已全選，<b>長按 → 拷貝</b>（電腦按 Ctrl+C）：</p><textarea id="mt" readonly></textarea><div style="text-align:right;margin-top:8px"><button type="button" id="mclose">關閉</button></div></div></div>
<script>
const toast=document.getElementById('t');
function show(m){toast.textContent=m;toast.classList.add('on');setTimeout(()=>toast.classList.remove('on'),1300)}
/* 檔案預覽、內嵌頁面常常擋剪貼簿：依序試 Clipboard API → execCommand；都失敗就跳出全選好的文字框讓人手動拷貝，不能假裝成功 */
function legacyCopy(text){
  const a=document.createElement('textarea');a.value=text;a.setAttribute('readonly','');
  a.style.cssText='position:fixed;top:0;left:0;opacity:0;font-size:16px';document.body.appendChild(a);
  a.focus();a.select();a.setSelectionRange(0,text.length);
  let ok=false;try{ok=document.execCommand('copy')}catch(e){}
  a.remove();return ok;
}
function manual(text){const m=document.getElementById('m'),t=document.getElementById('mt');t.value=text;m.classList.add('on');setTimeout(()=>{t.focus();t.select();t.setSelectionRange(0,text.length)},50)}
async function cp(text,label){
  let ok=false;
  if(navigator.clipboard&&window.isSecureContext){try{await navigator.clipboard.writeText(text);ok=true}catch(e){}}
  if(!ok)ok=legacyCopy(text);
  if(ok)show(label||'已複製');else manual(text);
}
document.getElementById('mclose').onclick=()=>document.getElementById('m').classList.remove('on');
document.addEventListener('click',e=>{const b=e.target.closest('button.cp');if(!b)return;
 const t=b.dataset.copy!==undefined?b.dataset.copy:(b.closest('.item')||{}).dataset?.copy;
 if(t)cp(t)});
/* 勾選特定幾筆再一起複製 */
const bar=document.getElementById('bar'),cnt=document.getElementById('cnt');
function picked(){return [...document.querySelectorAll('.pick:checked')].map(x=>x.closest('.item'))}
function refresh(){const n=picked().length;cnt.textContent='已選 '+n+' 筆';bar.classList.toggle('on',n>0);document.body.classList.toggle('hasbar',n>0)}
document.addEventListener('change',e=>{if(!e.target.classList.contains('pick'))return;e.target.closest('.item').classList.toggle('sel',e.target.checked);refresh()});
document.getElementById('cpSel').onclick=()=>{const it=picked();if(!it.length)return;cp(it.map(x=>x.dataset.copy).join('\\n\\n'),'已複製 '+it.length+' 筆')};
/* 點案名在頁內預覽，不另開分頁；手機按返回鍵＝關預覽。官網的 CSP frame-ancestors 允許被嵌入，
   哪天被擋了還有「另開視窗」可以用 */
const pv=document.getElementById('pv'),pvf=document.getElementById('pvf');
function pvClose(){if(!pv.classList.contains('on'))return;pv.classList.remove('on');pvf.src='about:blank'}
document.addEventListener('click',e=>{const a=e.target.closest('a.name');if(!a||e.ctrlKey||e.metaKey||e.shiftKey)return;
 e.preventDefault();document.getElementById('pvt').textContent=a.textContent;document.getElementById('pvo').href=a.href;
 pvf.src=a.href;pv.classList.add('on');history.pushState({pv:1},'')});
document.getElementById('pvx').onclick=()=>history.back();
pv.addEventListener('click',e=>{if(e.target===pv)history.back()});
addEventListener('popstate',pvClose);
function unpick(root){root.querySelectorAll('.pick:checked').forEach(x=>{x.checked=false;x.closest('.item').classList.remove('sel')});refresh()}
document.getElementById('clrSel').onclick=()=>unpick(document);
/* 收合客戶（或整個資料夾）＝清掉裡面的勾選，換下一位買方時不會連前一位的一起複製。toggle 不冒泡，要用 capture */
document.addEventListener('toggle',e=>{if(!e.target.open&&e.target.matches('details'))unpick(e.target)},true);
</script>`;

fs.writeFileSync(outPath, html, 'utf8');
console.log('wrote ' + outPath + ' — ' + totalItems + ' items / ' + totalDemands + ' demands / ' + totalClients + ' clients');
