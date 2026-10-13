/* 買方配案系統 — 產生彙總頁
 * 用法: node scripts/buyer-match/build_page.js <data.json> <out.html>
 * data.json = collect.js 跑完 FDBM.dump() 解 base64 後的內容
 */
const fs = require('fs');
const crypto = require('crypto');

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

const BADGE_PRIORITY = ['永慶', '台慶', '永義', '有巢氏'];
const rank = (b) => { const i = BADGE_PRIORITY.indexOf(b); return i < 0 ? 99 : i; };
/* 物件編號：官網網址 /house/7476129 那串。改價不會變，永慶/台慶/永義/有巢氏官網也是同一個號碼 */
const listingNo = (u) => (String(u || '').match(/\/house\/(\d+)/) || [])[1] || String(u || '');
const num = (x) => parseFloat(String(x || '').replace(/,/g, ''));
/* 坪數＝總價÷單價（KEIS 摘要沒有坪數欄）。總價欄抓錯（抓到社區名）就算不出來，只靠編號 */
const pingOf = (it) => { const t = num(it.totalPrice), u = num(it.unitPrice); return /萬/.test(it.totalPrice) && t > 0 && u > 0 ? t / u : NaN; };
/* 同一戶判定（10-14 使用者定的）：同編號、KEIS 同一張卡，或「同區＋同路名＋同樓層＋坪數差 3% 內」——
   後者抓的是委託給好幾家仲介、各自開了不同編號的同一戶（吉昌街一戶 19 個編號）。各家量的坪數會差一點，所以給 3% */
const PING_TOL = 0.03;
function sameUnit(a, b) {
  if (listingNo(a.url) === listingNo(b.url)) return true;
  if (a.fp && a.fp === b.fp) return true;          // KEIS 自己就放在同一張卡（同地址同價）
  if (!a.floor || a.district !== b.district || a.road !== b.road || a.floor !== b.floor) return false;
  const pa = pingOf(a), pb = pingOf(b);
  return pa > 0 && pb > 0 && Math.abs(pa - pb) / Math.min(pa, pb) <= PING_TOL;
}
/* 把同一戶併成一張卡：顯示最便宜的那筆（同價優先永慶），其他家只列「另有 N 家刊登＋價格範圍」 */
function mergeSameUnit(items) {
  const parent = items.map((_, i) => i);
  const root = (i) => (parent[i] === i ? i : (parent[i] = root(parent[i])));
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) if (sameUnit(items[i], items[j])) parent[root(j)] = root(i);
  const groups = {};
  items.forEach((it, i) => (groups[root(i)] = groups[root(i)] || []).push(it));
  return Object.values(groups).map((g) => {
    const byPrice = g.slice().sort((a, b) => (num(a.totalPrice) || 1e9) - (num(b.totalPrice) || 1e9) || rank(a.badge) - rank(b.badge));
    const nos = [...new Set(g.map((x) => listingNo(x.url)))];
    const prices = [...new Set(g.map((x) => num(x.totalPrice)).filter((x) => x > 0))].sort((a, b) => a - b);
    const chg = g.find((x) => x.chg);
    return Object.assign({}, byPrice[0], {
      k: [...new Set(g.map((x) => x.k))].join(' '),
      isNew: g.every((x) => x.isNew),              // 已知的那戶多了一家刊登不算新案
      whenDays: Math.min(...g.map((x) => x.whenDays)),
      others: nos.length - 1,
      range: prices.length > 1 ? prices[0].toLocaleString() + '–' + prices[prices.length - 1].toLocaleString() + '萬' : '',
      chg: chg ? chg.chg : null,
    });
  });
}

/* NEW／改價：每個客需記住看過哪些物件編號、上次多少錢（seen.json，本機、已 gitignore）。
   collect.js 的 isNew 是用「地址＋價格」比的，改價也會變 NEW；這裡改成同編號就不是新案，改價另外標。
   第一次還沒有 seen.json 時沿用 collect.js 的 isNew 當起點 */
const SEEN_PATH = require('path').join(__dirname, 'seen.json');
const RUN = R.finishedAt || R.startedAt || '';
let SEEN = null;
try { SEEN = JSON.parse(fs.readFileSync(SEEN_PATH, 'utf8')); } catch (e) {}
const BOOT = !SEEN;
SEEN = SEEN || {};
function track(client, demand, it) {
  const id = client + '|' + demand + '|' + listingNo(it.url);
  const price = /萬/.test(it.totalPrice) ? it.totalPrice : '';
  let r = SEEN[id];
  if (!r) r = SEEN[id] = { first: BOOT && !it.isNew ? 'old' : RUN, price, run: RUN };
  else if (r.run !== RUN) {                      // 同一份 data.json 重產頁面不會重複判定
    if (price && r.price && price !== r.price) { r.prev = r.price; r.changed = RUN; }
    if (price) r.price = price;
    r.run = RUN;
  }
  const chg = r.changed === RUN && r.prev ? { from: r.prev, to: r.price, down: num(r.price) < num(r.prev) } : null;
  return Object.assign({}, it, { isNew: r.first === RUN, chg });
}

/* --mask：公開網址用的版本，客戶名打碼。「66604陳漢強」→「66604陳○○」——編號＋姓氏自己認得出是誰，
   外人對不到本人。客需名稱裡出現同一個名字也一起換掉。桌面那份不加 --mask，維持全名 */
const MASK = process.argv.includes('--mask');
/* 複製次數的 key：客戶＋物件編號的雜湊（存到 Cloudflare D1 的只有這串，沒有客戶名）。
   用編號不用價格，改價後次數還在；用打碼前的名字算，--mask 開關不會讓次數歸零 */
for (const o of R.out || []) { o.rawClient = o.client; o.rawDemand = o.demand; }
const copyKey = (client, it) => crypto.createHash('sha1').update(client + '|' + listingNo(it.url)).digest('hex').slice(0, 12);
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
  /* 0 筆的客需也要留一張卡（顯示「無物件」），不然客戶整個從頁面消失，看起來像漏跑 */
  const f = (folders[o.folder] = folders[o.folder] || {});
  const c = (f[o.client] = f[o.client] || {});
  const items = (o.items || []).map((it) => Object.assign(track(o.rawClient, o.rawDemand, it), { k: copyKey(o.rawClient, it) }));
  c[o.demand] = (c[o.demand] || []).concat(items);
}
for (const f of Object.values(folders)) for (const c of Object.values(f)) for (const d of Object.keys(c)) c[d] = mergeSameUnit(c[d]);
fs.writeFileSync(SEEN_PATH, JSON.stringify(SEEN), 'utf8');
const ORDER = ['A買', 'B買', 'C買'];

let totalItems = 0, totalDemands = 0, totalClients = 0, totalNew = 0;
const newBadge = (n) => n ? `<span class="newn">NEW ${n}</span>` : '';
let body = '', nav = '';
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
        return `<li class="item${it.isNew ? ' isnew' : ''}" data-k="${it.k}" data-copy="${esc(t)}">
  <div class="ihead"><label class="pickw"><input type="checkbox" class="pick" aria-label="選取這筆"></label><div class="badge b-${esc(it.badge)}">${esc(it.badge)}</div>${it.isNew ? '<span class="new">NEW</span>' : ''}${it.chg ? `<span class="chg${it.chg.down ? ' down' : ''}">${it.chg.down ? '降價' : '漲價'} ${esc(it.chg.from)}→${esc(it.chg.to)}</span>` : ''}<span class="sent" hidden></span><span class="when">${esc(it.when)}</span></div>
  <div class="meta">
    <a class="name" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.name || '(無案名)')}</a>
    <div class="sub">${esc([it.district, it.road, it.community].filter(Boolean).join(' · '))}</div>
    <div class="sub">${esc([it.kind, it.floor, it.layout, it.age].filter(Boolean).join(' · '))}</div>
    <div class="price">${esc(it.totalPrice)}${it.unitPrice ? ' <span class="unit">' + esc(it.unitPrice) + '</span>' : ''}</div>
    ${it.others ? `<div class="sub more">另有 ${it.others} 家刊登${it.range ? ' · ' + esc(it.range) : ''}</div>` : ''}
  </div>
  <div class="right"><button class="cp" type="button">複製</button></div>
</li>`;
      }).join('\n');
      cHtml += `<section class="demand${dNew ? ' hasnew' : ''}">
  <h4>${esc(dname)} <span class="n">${items.length}</span>${newBadge(dNew)}
    ${items.length ? `<button class="cp grp" type="button" data-copy="${esc(items.map(copyText).join('\n\n'))}">複製這組</button>` : ''}</h4>
  ${items.length ? `<ul class="items">${rows}</ul>` : '<p class="none">無物件</p>'}
</section>`;
    }
    totalItems += cCount;
    fCount += cCount;
    fNew += cNew;
    totalNew += cNew;
    fHtml += `<details class="client${cNew ? ' hasnew' : ''}">
  <summary><span class="cname" title="點名字複製客戶名稱">${esc(cname)}</span> <span class="n">${cCount}</span>${newBadge(cNew)}<span class="sentn" hidden></span></summary>
  <div class="cbody">
    ${cHtml}
  </div>
</details>`;
  }
  /* 左邊一格一個資料夾，中間只顯示點到的那個 */
  nav += `<button type="button" class="tile${fNew ? ' hasnew' : ''}" data-f="${esc(fname)}">
  <b>${esc(fname)}</b><span class="n">${clientNames.length} 位客戶<br>${fCount} 筆</span>${newBadge(fNew)}
</button>`;
  body += `<section class="folder" data-f="${esc(fname)}" hidden>
  <h2>${esc(fname)} <span class="n">${clientNames.length} 位客戶 · ${fCount} 筆</span>${newBadge(fNew)}</h2>
  <div class="clients">${fHtml}</div>
</section>`;
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
body{background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Noto Sans TC","Segoe UI",sans-serif;margin:0}
/* 左欄三個正方形資料夾，從頁面頂端排到底端平均分（高度÷3＝邊長）；手機寬度不夠時改用 28vw 當邊長，不擠掉中間內容 */
.app{--tile:min(calc((100vh - 32px) / 3),28vw);--tile:min(calc((100dvh - 32px) / 3),28vw);display:flex;align-items:flex-start}
.side{position:sticky;top:0;flex:0 0 auto;height:100vh;height:100dvh;padding:8px;display:flex;flex-direction:column;gap:8px;border-right:1px solid var(--line);background:var(--bg);z-index:6}
.tile{width:var(--tile);height:var(--tile);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:6px;border-radius:14px;border:2px solid var(--line);background:var(--card);text-align:center;padding:6px}
.tile b{font-size:clamp(18px,calc(var(--tile) * .2),40px)}
.tile .n{font-size:clamp(11px,calc(var(--tile) * .075),15px);line-height:1.4}
.tile .newn{margin:0}
.tile.hasnew{border-color:#e8590c}
.tile.on{background:var(--accent);border-color:var(--accent);color:#fff}
.tile.on .n{color:#fffd}
.main{flex:1 1 auto;min-width:0;padding:0 12px 12px;max-width:1100px}
.folder h2{font-size:18px;margin:4px 0 6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
@media (max-width:600px){.items,.clients{grid-template-columns:minmax(0,1fr)!important}}
h1{font-size:19px;margin:4px 0 2px}
.top{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:5;margin-bottom:10px}
.stat{color:var(--dim);font-size:13px}
button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:7px;padding:5px 11px}
button.primary{background:var(--accent);color:#fff;border-color:transparent;font-weight:600}
button:active{transform:scale(.97)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0;overflow:hidden}
summary{cursor:pointer;padding:11px 13px;font-size:15px;user-select:none}
/* 資料夾裡的客戶也排兩欄方卡；點開的那位撐滿整列，裡面的物件卡才放得下 */
.clients{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.client{margin:0;background:var(--bg)}
.client[open]{grid-column:1/-1;background:var(--card)}
.client>summary{min-height:64px}
.client[open]>summary{min-height:0;border-bottom:1px solid var(--line)}
.n{color:var(--dim);font-size:12px;font-weight:400}
.cbody{padding:4px 11px 12px}
.demand{margin:10px 0}
.none{color:var(--dim);font-size:13px;margin:4px 0 0}
.demand h4{font-size:14px;margin:0 0 6px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--accent)}
.items{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.item{display:flex;flex-direction:column;gap:5px;padding:9px;border:1px solid var(--line);border-radius:10px;background:var(--bg)}
.ihead{display:flex;align-items:center;gap:6px;min-width:0}
.cname{text-decoration:underline dotted;text-underline-offset:4px;cursor:copy}
.badge{flex:0 0 auto;font-size:11px;padding:2px 6px;border-radius:5px;background:var(--chip);color:var(--dim);margin-top:2px}
.meta{flex:1 1 auto;min-width:0}
.name{color:var(--fg);font-weight:600;text-decoration:none;word-break:break-all}
.name:hover{color:var(--accent)}
.new{background:#e8590c;color:#fff;font-size:10px;font-weight:700;padding:1px 5px;border-radius:4px}
.newn{background:#e8590c;color:#fff;font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px;margin-left:8px}
.item.isnew{border-color:#e8590c;background:#e8590c12}
.demand.hasnew>h4{border-left:4px solid #e8590c;padding-left:8px}
.sub{color:var(--dim);font-size:12.5px}
.price{font-weight:700;margin-top:2px}
.unit{font-weight:400;color:var(--dim);font-size:12.5px}
.right{margin-top:auto;display:flex;justify-content:flex-end}
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
.when{margin-left:auto}
/* 複製過的物件：綠色「已複製 N 次」＋整張卡淡一點，一眼看出哪些傳過了 */
.sent{background:#2b8a3e;color:#fff;font-size:11px;font-weight:700;padding:1px 6px;border-radius:4px;white-space:nowrap}
.sentn{white-space:nowrap;display:inline-block;background:#2b8a3e;color:#fff;font-size:11px;font-weight:700;padding:1px 7px;border-radius:10px;margin-left:8px}
.sent[hidden],.sentn[hidden]{display:none}
.item.done{opacity:.6}
.chg{background:#c92a2a;color:#fff;font-size:10.5px;font-weight:700;padding:1px 5px;border-radius:4px;white-space:nowrap}
.chg.down{background:#1971c2}
.more{color:var(--accent)}
.item.done:hover,.item.done.sel{opacity:1}
</style>
<div class="app">
<nav class="side">${nav}</nav>
<main class="main">
<div class="top">
  <h1>買方配案</h1>
  <div class="stat">${totalClients} 位客戶 · ${totalDemands} 個客需 · <b>${totalItems}</b> 筆官網連結${totalNew ? ' · <span class="newn" style="margin-left:0">本次新增 ' + totalNew + '</span>' : ''}　|　更新 ${esc(localTime(R.finishedAt || R.startedAt))}</div>
  <div style="margin-top:7px"><button class="cp primary" type="button" data-copy="${esc(allText.join('\n\n'))}">一鍵全部複製</button></div>
</div>
${body || '<p class="stat">沒有抓到任何官網連結。</p>'}
</main>
</div>
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
document.addEventListener('click',e=>{const c=e.target.closest('.cname');
 if(c){e.preventDefault();cp(c.textContent,'已複製 '+c.textContent);return}  /* 點名字＝只複製客戶名稱；preventDefault 擋掉 summary 的展開 */
 const b=e.target.closest('button.cp');if(!b)return;
 const t=b.dataset.copy!==undefined?b.dataset.copy:(b.closest('.item')||{}).dataset?.copy;
 if(!t)return;cp(t);
 /* 計次：單筆、複製這組算；「一鍵全部複製」是整份備份，不算 */
 if(b.classList.contains('grp'))bump([...b.closest('.demand').querySelectorAll('.item')]);
 else if(!b.classList.contains('primary'))bump([b.closest('.item')].filter(Boolean))});
/* 切換資料夾：中間只顯示點到的那個，記住上次看的（存不了就從第一個開始） */
function openFolder(f){let hit=false;
 document.querySelectorAll('.folder').forEach(s=>{const on=s.dataset.f===f;s.hidden=!on;hit=hit||on});
 if(!hit)return false;
 document.querySelectorAll('.tile').forEach(t=>t.classList.toggle('on',t.dataset.f===f));
 try{localStorage.setItem('bm-folder',f)}catch(e){}
 scrollTo(0,0);return true}
document.querySelectorAll('.tile').forEach(t=>t.onclick=()=>openFolder(t.dataset.f));
{let last=null;try{last=localStorage.getItem('bm-folder')}catch(e){}
 const first=document.querySelector('.tile');if(!(last&&openFolder(last))&&first)openFolder(first.dataset.f)}
/* 複製次數：存在 Cloudflare（functions/api/copies.js），電腦和手機看到同一份。
   本機直接開檔案時沒有 /api，失敗就不顯示，不影響複製 */
let counts={};
function paint(){
 document.querySelectorAll('.item').forEach(li=>{const n=Math.max(0,...li.dataset.k.split(' ').map(k=>counts[k]||0)),b=li.querySelector('.sent');
  b.hidden=!n;b.textContent='已複製 '+n+' 次';li.classList.toggle('done',n>0)});
 document.querySelectorAll('.client').forEach(c=>{const all=[...new Set([...c.querySelectorAll('.item')].map(li=>li.dataset.k))];
  const done=all.filter(ks=>ks.split(' ').some(k=>counts[k])).length,b=c.querySelector('.sentn');b.hidden=!done;b.textContent='已複製 '+done+'/'+all.length})}
function loadCounts(){fetch('api/copies',{cache:'no-store'}).then(r=>r.ok?r.json():null).then(j=>{if(j){counts=j;paint()}}).catch(()=>{})}
function bump(items){const keys=[...new Set(items.flatMap(li=>(li.dataset.k||'').split(' ')).filter(Boolean))];if(!keys.length)return;
 keys.forEach(k=>counts[k]=(counts[k]||0)+1);paint();
 fetch('api/copies',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({keys})})
  .then(r=>r.ok?r.json():null).then(j=>{if(j){counts=j;paint()}}).catch(()=>{})}
loadCounts();
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')loadCounts()});
/* 勾選特定幾筆再一起複製 */
const bar=document.getElementById('bar'),cnt=document.getElementById('cnt');
function picked(){return [...document.querySelectorAll('.pick:checked')].map(x=>x.closest('.item'))}
function refresh(){const n=picked().length;cnt.textContent='已選 '+n+' 筆';bar.classList.toggle('on',n>0);document.body.classList.toggle('hasbar',n>0)}
document.addEventListener('change',e=>{if(!e.target.classList.contains('pick'))return;e.target.closest('.item').classList.toggle('sel',e.target.checked);refresh()});
document.getElementById('cpSel').onclick=()=>{const it=picked();if(!it.length)return;cp(it.map(x=>x.dataset.copy).join('\\n\\n'),'已複製 '+it.length+' 筆');bump(it)};
/* 點案名在頁內預覽，不另開分頁；手機按返回鍵＝關預覽。官網的 CSP frame-ancestors 允許被嵌入，
   哪天被擋了還有「另開視窗」可以用 */
const pv=document.getElementById('pv');let pvf=document.getElementById('pvf');
function freshFrame(){const n=pvf.cloneNode(false);n.removeAttribute('src');pvf.replaceWith(n);pvf=n}
function pvClose(){if(!pv.classList.contains('on'))return;pv.classList.remove('on');freshFrame()}
function pvShut(){const was=pv.classList.contains('on');pvClose();if(was&&history.state&&history.state.pv)history.back()}
document.addEventListener('click',e=>{const a=e.target.closest('a.name');if(!a||e.ctrlKey||e.metaKey||e.shiftKey)return;
 e.preventDefault();document.getElementById('pvt').textContent=a.textContent;document.getElementById('pvo').href=a.href;
 pvf.src=a.href;pv.classList.add('on');history.pushState({pv:1},'')});
document.getElementById('pvx').onclick=pvShut;
pv.addEventListener('click',e=>{if(e.target===pv)pvShut()});
addEventListener('popstate',pvClose);
function unpick(root){root.querySelectorAll('.pick:checked').forEach(x=>{x.checked=false;x.closest('.item').classList.remove('sel')});refresh()}
document.getElementById('clrSel').onclick=()=>unpick(document);
/* 收合客戶（或整個資料夾）＝清掉裡面的勾選，換下一位買方時不會連前一位的一起複製。toggle 不冒泡，要用 capture */
document.addEventListener('toggle',e=>{if(!e.target.open&&e.target.matches('details'))unpick(e.target)},true);
</script>`;

fs.writeFileSync(outPath, html, 'utf8');
console.log('wrote ' + outPath + ' — ' + totalItems + ' items / ' + totalDemands + ' demands / ' + totalClients + ' clients');
