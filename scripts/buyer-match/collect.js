/* 買方配案系統 — 資料收集器 v6
 *
 * 用法：在 agent.foundi.info/tool/property/list（已登入）的 DevTools Console 貼上執行，然後：
 *   FDBM.run()          // 增量跑：只展開新出現的物件，沒有新物件的客需直接跳過
 *   FDBM.run({full:1})  // 全跑：忽略上次結果，整批重掃（第一次用這個）
 *   FDBM.progress()     // 看進度
 *   FDBM.dumpState()    // 取出 base64 結果（從 localStorage 重建，中斷也不會丟）→ data.json → node build_page.js
 *   FDBM.holes()        // 檢查有沒有「0 張卡卻寫成功」的客需（會害下次增量靜靜跳過）
 *   FDBM.run({only:['某客需']}) // 只重跑指定客需，忽略上次結果（補漏用）
 *
 * 設計重點（都是踩過坑才長這樣，改之前先看）：
 * 1. 只讀畫面上已渲染的 DOM。內部 API 回應是 foundiprotocol 加密的，不去解它。
 * 2. 一律用 textContent，不用 innerText —— innerText 會強迫整頁重新排版，
 *    卡片一多就把主執行緒卡死（v2 就是這樣停擺的）。
 * 3. 卡片展開後「關不掉」（App 把 mat-expansion-panel 的收合鎖住了）。
 *    所以要切到別的客需再切回來，讓 Angular 重新渲染清單 = 全部歸零。但每次切換都是額外搜尋、
 *    會撞「超過查詢次數限制」，所以現在改成盡量一次展開 20~28 張（MAXOPEN=30）才重置，
 *    頁面變慢（LAG_MS）才提前重置。⚠️ 展開很多張會不會卡，2026-09-19 改的當下還沒實測。
 * 4. 「本次銷售刊登」一頁只有 5 筆，會分頁；不翻頁會漏掉永慶/台慶的連結。
 * 5. 官網判定用「徽章文字」(永慶/台慶/永義/有巢氏)，不用網域白名單 —— 網域用猜的會靜靜漏件。
 * 6. 下架判定：物件如果不再出現在該客需的搜尋結果裡，就從結果移除。
 *    （跨網域直接測連結會被瀏覽器 CORS 擋掉，測不到真實狀態）
 * 7. 擬人化節奏：這支沒有走內部 API、資料量也不大，速度不是重點——所有等待都吃隨機抖動，
 *    客需之間插隨機停頓，每 8~10 個客需再插一次長休息。別為了「跑快一點」改回固定間隔。
 */
(function () {
  const OFFICIAL = ['永慶', '台慶', '永義', '有巢氏'];
  const FOLDERS = ['A買', 'B買', 'C買'];
  const MAXOPEN = 30;     // 展開中的卡超過這個數就提前重置（原 8，那是保險不是量出來的；每次重置＝額外搜尋，會撞查詢上限）
  const LAG_MS = 1500;    // 讀一張卡的同步解析超過這個毫秒＝頁面變慢，提前重置
  const STATE_KEY = 'FDBM_STATE';
  /* 背景分頁會被 Chrome 把 setTimeout 降速 4~5 倍（看起來像卡住）。
     Worker 裡的計時器不受節流 → 一律走 Worker，建不起來才退回 setTimeout。 */
  const TW = (() => {
    try {
      const src = 'onmessage=function(e){setTimeout(function(){postMessage(e.data.id)},e.data.ms)}';
      const w = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
      const waiting = new Map();
      let seq = 0;
      w.onmessage = (e) => { const f = waiting.get(e.data); if (f) { waiting.delete(e.data); f(); } };
      return (ms) => new Promise((r) => { const i = ++seq; waiting.set(i, r); w.postMessage({ id: i, ms }); });
    } catch (e) { return null; }
  })();
  const rawSleep = (ms) => (TW ? TW(ms) : new Promise((r) => setTimeout(r, ms)));
  const rand = (min, max) => min + Math.random() * (max - min);
  /* 擬人化：每個等待都乘上 0.7~1.5 的隨機抖動，避免固定節奏被當成腳本。 */
  let SLOW = 3; // 全域減速倍率，FDBM.run({slow:N}) 可覆蓋
  const sleep = (ms) => rawSleep(rand(ms * 0.7, ms * 1.5) * SLOW);
  /* 給明確的「人在停頓」情境用（客需之間、長休息），直接給範圍，只吃減速倍率。 */
  const pause = (min, max) => rawSleep(rand(min, max) * SLOW);

  const R = {
    log: [], done: 0, total: 0, cards: 0, expanded: 0, skipped: 0,
    hostsSeen: {}, out: [], running: false, mode: '',
    startedAt: null, finishedAt: null, cur: '', idx: 0, stop: false, limitText: '', lag: 0,
  };

  const T = (el, sel) => { const e = el.querySelector(sel); return e ? e.textContent.trim() : ''; };
  const leaves = (el) => [...el.querySelectorAll('*')]
    .filter((e) => e.children.length === 0 && e.textContent.trim())
    .map((e) => e.textContent.trim());
  const openCount = () => document.querySelectorAll('fd-property-detail').length;
  const note = (m) => { R.log.push(new Date().toTimeString().slice(0, 8) + ' ' + m); if (R.log.length > 500) R.log.splice(0, 250); };

  /* 撞上限時網站右上角會跳提示條「超過查詢次數限制 請升級專業會員或聯絡客服」（2026-09-19 實見）。
     字樣直接掃整個 body，不依賴提示條的容器 class；碰到就要停手，不然腳本會照樣一張張點下去。 */
  function limitHit() {
    const t = document.body.textContent || '';
    const m = t.match(/超過查詢次數限制.{0,30}/);
    if (m) { R.limitText = m[0]; return true; }
    return false;
  }

  function resultCount() {
    const e = document.querySelector('.result-summary');
    if (e) {
      const m = e.textContent.match(/共\s*([\d,]+)\s*筆/);
      if (m) return parseInt(m[1].replace(/,/g, ''), 10);
    }
    /* 真的 0 筆時（常見於關鍵字搜尋）畫面不會渲染 .result-summary，
       只會顯示這句話——沒有這道判斷會被當成撞上限，誤判成失敗（2026-09-21 杏湖社區踩到）。 */
    if ((document.querySelector('div.main-body-container')?.textContent || '').includes('找不到符合的物件')) return 0;
    return null;
  }

  /* ---------- 客需側欄 ---------- */
  async function openPanel() {
    for (let i = 0; i < 6; i++) {
      if (document.querySelector('mat-nested-tree-node')) return true;
      const b = [...document.querySelectorAll('button,div,span')]
        .filter((e) => e.textContent.trim() === '客需條件' && e.children.length < 3);
      if (b.length) b[b.length - 1].click();
      await sleep(1200);
    }
    return !!document.querySelector('mat-nested-tree-node');
  }

  /* 每次跑都重讀 → 資料夾成員增減、搬動會自動同步 */
  function readTree() {
    const out = []; let f = null, c = null;
    for (const n of document.querySelectorAll('mat-nested-tree-node')) {
      const lvl = +n.getAttribute('aria-level');
      const lbl = (n.querySelector(':scope > .tree-node-row .mdc-button__label, :scope > .tree-node-row .folder-title-text')?.textContent || '').trim();
      if (lvl === 1) { f = { folder: lbl, clients: [] }; out.push(f); }
      else if (lvl === 2 && f) { c = { client: lbl, entries: [] }; f.clients.push(c); }
      else if (lvl === 3 && c) c.entries.push({ demand: lbl, id: n.id });
    }
    return out;
  }

  async function load(id) {
    await openPanel();
    const n = document.getElementById(id);
    if (!n) return false;
    const b = n.querySelector('button.entry-title');
    if (!b) return false;
    b.click();
    for (let i = 0; i < 24; i++) { await sleep(500); if (document.querySelector('fd-property-panel')) break; }
    await sleep(700);
    return true;
  }

  /* ---------- 解析 ---------- */
  function agoDays(s) {
    if (!s) return 99999;
    let m;
    if (/剛剛|分鐘前/.test(s)) return 0;
    if ((m = s.match(/(\d+)\s*小時前/))) return +m[1] / 24;
    if (/昨天/.test(s)) return 1;
    if (/前天/.test(s)) return 2;
    if ((m = s.match(/(\d+)\s*天前/))) return +m[1];
    if ((m = s.match(/(\d+)\s*個?月前/))) return +m[1] * 30;
    if ((m = s.match(/(\d+)\s*年前/))) return +m[1] * 365;
    return 99999;
  }

  function summary(p) {
    const s = p.querySelector('fd-property-summary');
    if (!s) return null;
    const lv = leaves(s);
    const pa = T(s, '.subtitle').split(/\s+/);
    const kl = lv.find((t) => /^[^\s,]+,[^\s,]+$/.test(t) && /樓|透天|公寓|華廈|套房|店面|廠|地/.test(t)) || '';
    return {
      title: T(s, '.title'), subtitle: T(s, '.subtitle'),
      district: pa[1] || '', road: pa[2] || '', community: T(s, '.anchor-minor'),
      totalPrice: T(s, '.highlight'), unitPrice: lv.find((t) => /萬\/坪$/.test(t)) || '',
      floor: lv.find((t) => /樓$/.test(t) && (t.includes('/共') || t.includes('全棟'))) || '',
      age: lv.find((t) => /^[\d.]+年$/.test(t)) || '',
      layout: lv.find((t) => /房.*廳.*衛/.test(t)) || '',
      kind: kl.split(',')[0] || '',
    };
  }

  /* 不用展開就能算的物件指紋 —— 增量比對與下架判定都靠它 */
  const fingerprint = (p) => {
    const s = p.querySelector('fd-property-summary');
    return s ? [T(s, '.title'), T(s, '.subtitle'), T(s, '.highlight')].join('¦') : '';
  };

  function listingRows(p) {
    return [...p.querySelectorAll('fd-listing-info')].map((r) => {
      const badge = T(r, '.list-img-label');
      const a = r.querySelector('a[href^="http"]');
      let url = '', host = '';
      if (a) { try { const u = new URL(a.href); url = a.href; host = u.hostname; } catch (e) {} }
      const L = leaves(r);
      const price = L.find((x) => /^[\d,]+萬/.test(x)) || '';
      const when = L.find((x) => /刊登$/.test(x)) || '';
      const store = L.find((x) => /加盟店|直營|分店/.test(x)) || '';
      const name = L.find((x) => x !== badge && x !== price && x !== when && x !== store && x !== '暫無圖片' && !/^\d+$/.test(x)) || '';
      return { badge, name, store, price, when, whenDays: agoDays(when), url, host };
    });
  }

  /* 刊登清單一頁 5 筆，要翻完才不會漏掉官網連結 */
  async function allListingRows(p) {
    const all = [], seen = new Set();
    for (let i = 0; i < 15; i++) {
      listingRows(p).forEach((r) => {
        const k = r.badge + '|' + r.url + '|' + r.name + '|' + r.when;
        if (!seen.has(k)) { seen.add(k); all.push(r); }
      });
      const pag = p.querySelector('mat-paginator');
      if (!pag) break;
      const m = (T(pag, '.mat-mdc-paginator-range-label') || '').match(/第\s*(\d+)\s*頁，共\s*(\d+)\s*頁/);
      if (!m || +m[1] >= +m[2]) break;
      const nx = pag.querySelector('.mat-mdc-paginator-navigation-next');
      if (!nx || nx.disabled || nx.getAttribute('aria-disabled') === 'true') break;
      nx.click();
      await sleep(900);
    }
    return all;
  }

  async function ensureCards(min, cap = 150) {
    const box = document.querySelector('div.main-body-container');
    let last = -1, stable = 0;
    for (let i = 0; i < 50; i++) {
      const n = document.querySelectorAll('fd-property-panel').length;
      if (n >= Math.min(min, cap)) break;
      if (n === last) { stable++; if (stable >= (n === 0 ? 12 : 3)) break; } else { stable = 0; last = n; }
      if (box) box.scrollTop = box.scrollHeight;
      await sleep(800);
    }
    if (box) box.scrollTop = 0;
    await sleep(200);
    return document.querySelectorAll('fd-property-panel').length;
  }

  async function readCard(p, items) {
    if (limitHit()) throw new Error('上限訊息：' + R.limitText);
    if (!p.querySelector('fd-property-detail')) {
      (p.querySelector('mat-expansion-panel-header') || p.querySelector('fd-property-summary')).click();
      for (let w = 0; w < 25; w++) { await sleep(300); if (p.querySelector('fd-property-detail')) break; }
    }
    await sleep(600);
    if (limitHit()) throw new Error('上限訊息：' + R.limitText);
    if (!p.querySelector('fd-property-detail')) throw new Error('卡片展不開（疑似撞上限）');
    const t0 = performance.now();
    summary(p); listingRows(p);
    R.lag = performance.now() - t0;
    const s = summary(p), rows = await allListingRows(p), fp = fingerprint(p);
    rows.forEach((r) => { if (r.host) R.hostsSeen[r.host] = (R.hostsSeen[r.host] || 0) + 1; });
    rows.filter((r) => OFFICIAL.includes(r.badge) && r.url).forEach((o) => items.push({
      fp, kind: s?.kind || '', road: s?.road || '', district: s?.district || '',
      community: s?.community || '', totalPrice: s?.totalPrice || o.price, unitPrice: s?.unitPrice || '',
      floor: s?.floor || '', age: s?.age || '', layout: s?.layout || '',
      name: o.name || s?.title || '', badge: o.badge, url: o.url,
      when: o.when, whenDays: o.whenDays, store: o.store || '',
    }));
    R.cards++; R.expanded++;
  }

  /* ---------- 上次結果 ---------- */
  const keyOf = (t) => t.folder + '/' + t.client + '/' + t.demand;
  function loadState() { try { return JSON.parse(localStorage.getItem(STATE_KEY)) || { demands: {} }; } catch (e) { return { demands: {} }; } }
  function saveState(st) { try { localStorage.setItem(STATE_KEY, JSON.stringify(st)); } catch (e) { note('state 存不進去: ' + e.message); } }

  /* ---------- 主流程 ---------- */
  async function run(opts) {
    opts = opts || {};
    if (opts.slow > 0) SLOW = opts.slow;
    if (R.running) return;
    R.running = true; R.stop = false;
    R.mode = opts.full ? 'full' : 'incremental';
    R.startedAt = new Date().toISOString();
    R.out = []; R.done = 0; R.cards = 0; R.expanded = 0; R.skipped = 0;

    try {
    await openPanel();
    let list = [];
    readTree().filter((f) => FOLDERS.includes(f.folder))
      .forEach((f) => f.clients.forEach((c) => c.entries.forEach((e) =>
        list.push({ folder: f.folder, client: c.client, demand: e.demand, id: e.id }))));
    /* only:['客需名','客需名'] → 只重跑指定客需（補漏用，其餘 state 原封不動） */
    if (opts.only && opts.only.length) list = list.filter((t) => opts.only.includes(t.demand));
    R.total = list.length;
    if (!list.length) { note('讀不到任何客需（客需樹沒展開？），中止，不動 state'); return; }

    const state = opts.full ? { demands: {} } : loadState();
    const breakEvery = 8 + Math.floor(Math.random() * 3); // 每 8~10 個客需長休息一次

    for (let k = opts.from || 0; k < Math.min(list.length, opts.to || list.length); k++) {
      if (R.stop) { note('收到停止指令'); break; }
      if (limitHit()) { R.stop = true; note('偵測到上限訊息，停手：' + R.limitText); break; }
      const t = list[k];
      R.idx = k;
      R.cur = keyOf(t);

      if (k > (opts.from || 0)) {
        const done = k - (opts.from || 0);
        if (done % breakEvery === 0) { note('長休息'); await pause(5000, 15000); }
        else await pause(800, 3000);
      }
      const alt = (list[(k + 1) % list.length].id === t.id ? list[(k + 2) % list.length] : list[(k + 1) % list.length]).id;
      const prev = (opts.only && opts.only.length) ? null : state.demands[keyOf(t)];
      let total = null, fps = [], items = [];

      try {
        if (!(await load(t.id))) throw new Error('客需不見了');
        /* load() 只等「畫面出現任一張卡」或逾時，不保證卡片/摘要真的已經換成這個客需的資料——
           所以 total 故意晚一步，等 ensureCards() 的穩定判斷跑完才讀，縮小讀到舊客需殘留畫面的機率。 */
        let N = await ensureCards(999);
        total = resultCount();
        /* bad 有兩種：total>0(或null) 卻一張卡都沒渲染出來；或 total===0 卻還殘留 >0 張卡
           （很可能是上一個客需還沒清掉的舊卡片）。兩種都先重試一次，還是兜不起來就丟出去，
           寧可保護 state 也不要存進串錯客需的資料。 */
        let bad = total === 0 ? N > 0 : !N;
        if (bad) {
          await sleep(total === 0 ? 1500 : 4000);
          N = await ensureCards(999);
          total = resultCount();
          bad = total === 0 ? N > 0 : !N;
        }
        if (!bad && total === 0 && N === 0) {
          /* 空結果多驗一次：客需剛切換的瞬間，摘要跟卡片有機率同時巧合讀到 0——
             其實是新客需真正的資料還沒跑出來，不是真的 0 筆。等久一點再讀一次，
             兩次都讀到 0/0 才採信，不然會把明明有資料的客需誤判成空的、洗掉 state。 */
          await sleep(2000);
          N = await ensureCards(999);
          total = resultCount();
          bad = total === 0 ? N > 0 : !N;
        }
        /* total===0 且 N===0（雙重驗過的真空結果）要放行，讓下面把舊資料清空，不能當失敗跳過——
           不然這個客需一旦真的變成 0 筆命中，state 裡的舊清單就永遠清不掉，變成陰魂不散的下架物件。
           total===null（撞到「超過查詢次數限制」時畫面沒有 .result-summary）永遠不可信。 */
        if (total == null || bad) throw new Error('一張卡都沒渲染出來（共' + (total == null ? '?' : total) + '筆，畫面 ' + N + ' 張卡）');
        const panels0 = [...document.querySelectorAll('fd-property-panel')];
        fps = panels0.map(fingerprint);
        const fpSet = new Set(fps);

        /* 上次已經看過的物件 → 只留下這次還在清單裡的（不在的 = 下架） */
        const kept = prev ? (prev.items || []).filter((i) => fpSet.has(i.fp)).map((i) => Object.assign({}, i, { isNew: false })) : [];
        const known = new Set(prev ? (prev.cards || []) : []);
        const targets = [];
        fps.forEach((fp, i) => { if (!known.has(fp)) targets.push(i); });

        if (prev && targets.length === 0) {
          /* 沒有新物件 → 整個客需跳過，不展開任何卡 */
          R.skipped++;
          items = kept;
          note('跳過（無新物件）' + keyOf(t));
        } else {
          const fresh = [];
          for (let ti = 0; ti < targets.length; ) {
            if (R.stop) throw new Error('已停止，此客需不存檔');
            const chunk = 20 + Math.floor(Math.random() * 9); // 20~28，別用固定值
            if (ti > 0) { await load(alt); await load(t.id); }
            const end = Math.min(ti + chunk, targets.length);
            const need = targets[end - 1] + 1;
            await ensureCards(need);
            const panels = [...document.querySelectorAll('fd-property-panel')];
            let j = ti;
            for (; j < end; j++) {
              const p = panels[targets[j]];
              if (!p) continue;
              await readCard(p, fresh);
              if (openCount() >= MAXOPEN || R.lag > LAG_MS) { j++; break; }
            }
            ti = j;
          }
          fresh.forEach((i) => { i.isNew = !!prev; });
          items = kept.concat(fresh);
        }

        const seen = new Set();
        items = items.filter((i) => { const kk = i.url + '|' + i.badge; if (seen.has(kk)) return false; seen.add(kk); return true; });
        items.sort((a, b) => a.whenDays - b.whenDays);

        state.demands[keyOf(t)] = { folder: t.folder, client: t.client, demand: t.demand, total, cards: fps, items, at: new Date().toISOString() };
        R.out.push(Object.assign({}, t, { total, cards: fps, items }));
      } catch (e) {
        R.out.push(Object.assign({}, t, { error: String((e && e.message) || e), cards: fps, items: [] }));
        note('客需失敗 ' + t.demand + ': ' + e);
        if (total == null || /上限|展不開/.test(String((e && e.message) || e))) { R.stop = true; note('疑似撞查詢上限，自動停手（此客需不存檔）'); }
      }
      R.done++;
      saveState(state);
    }

    /* 這次樹上已經沒有的客需 → 從 state 清掉，避免舊資料復活
       （只重跑部分客需時不能清，否則會把沒跑到的全砍掉） */
    if (!(opts.only && opts.only.length) && !R.stop) {
      const alive = new Set(list.map(keyOf));
      Object.keys(state.demands).forEach((k) => { if (!alive.has(k)) delete state.demands[k]; });
    }
    saveState(state);
    } finally {
      R.running = false;
      R.finishedAt = new Date().toISOString();
      R.cur = '';
    }
  }

  window.FDBM = {
    R,
    run(opts) { run(opts); return 'started'; },
    progress() {
      return {
        mode: R.mode, done: R.done, total: R.total, cards: R.cards, skipped: R.skipped,
        items: R.out.reduce((a, o) => a + (o.items ? o.items.length : 0), 0),
        running: R.running, stop: R.stop, limitText: R.limitText, cur: R.cur, err: R.log.slice(-2),
      };
    },
    stop() { R.stop = true; return 'stopping'; },
    reset() { localStorage.removeItem(STATE_KEY); return 'state cleared'; },
    dump() { return btoa(unescape(encodeURIComponent(JSON.stringify(R)))); },
    /* 產頁面一律用這支：R.out 每次 run() 會清空，中斷就沒了；state 是逐個客需存下來的 */
    dumpState() {
      const st = loadState();
      const keys = Object.keys(st.demands || {});
      const out = keys.map((k) => {
        const d = st.demands[k], seg = k.split('/');
        return {
          folder: d.folder || seg[0] || '', client: d.client || seg[1] || '',
          demand: d.demand || seg.slice(2).join('/') || '',
          total: d.total == null ? null : d.total, cards: d.cards || [], items: d.items || [], at: d.at || '',
        };
      });
      const ats = out.map((o) => o.at).filter(Boolean).sort();
      const J = { mode: 'state', out, demands: out.length, startedAt: ats[0] || '', finishedAt: ats[ats.length - 1] || '' };
      return btoa(unescape(encodeURIComponent(JSON.stringify(J))));
    },
    /* 只渲染到 0 張卡卻寫成功的客需 → 下次增量會被當成「沒有新物件」跳過，等於靜靜漏件 */
    holes() {
      const st = loadState();
      return Object.keys(st.demands || {})
        .filter((k) => { const d = st.demands[k]; return (!d.cards || !d.cards.length) && d.total; })
        .map((k) => k + ' (共' + st.demands[k].total + '筆卻 0 張卡)');
    },
  };
  return 'FDBM v6 ready (worker timer + dumpState + 擬人化節奏)';
})();
