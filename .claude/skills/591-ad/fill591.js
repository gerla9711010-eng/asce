/* 591 出售表單一次填完。用法：把這整份貼進 mcp__claude-in-chrome__javascript_tool，
   最上面的 DATA 換成這件案子的值，一次呼叫填完整頁並回傳驗證結果。

   為什麼要這樣做：一格一格點擊打字慢到使用者會中斷（2026-09-19 實測）。
   591 是 React + antd，直接操作 DOM 事件比模擬滑鼠快一個數量級，而且不受捲動位移影響。

   ⚠️ 欄位一律用「該列的標籤＋單位」找（例：「主建物」列、「格局」列裡單位是「衛」那格），
   不要再用 input 的全域索引。2026-10-14 AA1072581 踩過：勾「含車位面積」會多插一列車位面積、
   勾管理費「有」又多一格，後面整排索引往後位移，管理費數字被灌進月繳下拉、捷運站被灌進公車站下拉、
   標題被灌進火車站。標籤是 antd `.ant-form-item-label`，單位是 input 旁邊的 addon/suffix。

   填寫順序是有意義的：
   1. 先點會讓版面多長格子的單選（含車位面積、管理費有/無），
   2. 再做下拉（三段地址、出售型態、朝向、車位類型），
   3. 最後填純文字欄位、回讀驗證並自動補回被重繪清掉的格子。

   沒有的欄位（例：透天沒有車位面積、大樓沒有土地坪數）在 DATA 裡留 null 就會跳過。 */

const DATA = {
  city: '高雄市', district: '前鎮區', street: '公正路',
  lane: '47', alley: '', no: '1', noSub: '', hideNo: true,
  floorType: '出售多層',      // '出售單層' | '出售多層'
  floorFrom: '1', floorTo: '3',  // 出售單層時 floorTo 是「之」那格，通常留空
  totalFloors: '3',
  community: '',              // 透天留空；大樓填了 591 常會自動改成它資料庫裡的社區名，以 591 帶出的為準
  rooms: '5', halls: '2', baths: '3', balcony: '',
  builtY: '66', builtM: '8', builtD: '30',   // 民國
  orientation: '坐東南朝西北', // 來源沒寫就 null
  areaTotal: '37.15',         // 權狀坪數
  areaMain: '37.15', areaAnnex: '0', areaPublic: '0',
  areaParking: null,          // 有車位才填
  parkingType: null,          // '平面式停車位' | '機械式停車位' | '平面式+機械式'
  parkingInPrice: null,       // 售價含車位？null＝跟著 areaParking。有車位但沒坪數（AA1072556）時設 true
  landArea: '19.96',          // 透天/店面必填，大樓留 null
  price: '1100',              // 萬元
  mgmtFee: null,              // null = 無管理費；有就填數字（元/月）
  mrt: 'C1籬仔內',
  title: '五甲瑞隆商圈 靜巷方正透天',
  desc: [
    '【五甲瑞隆商圈｜靜巷方正透天｜五房三衛】',
    '📍前鎮區公正路', '🏠5房2廳3衛', '📐建坪37.15坪／地坪19.96坪',
    '🏢1-3樓／全棟3層', '💰1100萬', '', '✨亮點',
    '・鬧中取靜，五甲、瑞隆生活圈匯聚，吃喝採買輕鬆解決',
  ],
  contract: '有簽訂',          // KEIS contract_type：一般委託→'有簽訂'；專任委託→'有簽訂專任約'
  amenities: [],              // 生活機能勾選，prep.py 依訴求重點產（例：['近便利商店','近公園綠地']）
  tags: [],                   // 特色標籤，prep.py 產（'明星學區'／'制震宅'／'重劃區'）
};

/* 文案結尾固定加聯絡方式，比照臉書發文（docs/reference.md「聯絡人固定」那條）。
   2026-10-14 使用者要求。腳本自動補，DATA.desc 不用自己寫這兩行；已經有了就不重複加。 */
const CONTACT = ['', '📞 薛先生 0912877583（同 LINE）', 'LINE：https://line.me/ti/p/kg1pMk4vX8'];

/* ---------- 以下不用改 ---------- */
const sleep = ms => new Promise(r => setTimeout(r, ms));
const norm = s => (s || '').replace(/\s+/g, '');
const log = [];

// 找標籤以 name 開頭的那一列（例：'格局' 對到「格局（現況）(說明)」）
function row(name) {
  return [...document.querySelectorAll('.ant-form-item')].find(fi => {
    const l = fi.querySelector('.ant-form-item-label');
    return l && norm(l.innerText).startsWith(name);
  }) || null;
}
function unitOf(el) {
  const w = el.closest('.ant-input-group-wrapper,.ant-input-number-group-wrapper,.ant-input-affix-wrapper') || el.parentElement;
  const u = w.querySelector('.ant-input-group-addon,.ant-input-suffix,.ant-input-number-group-addon');
  return u ? u.innerText.trim() : '';
}
/* 某一列裡的純文字格（排除下拉的 search input、街道面板的搜尋框）。
   ⚠️ 不能用 `input[type=text]` 選：antd InputNumber（坪數、房廳衛、年月日、總樓層、管理費）
   根本沒寫 type 屬性，CSS 選不到；要用 `e.type` 屬性判斷（沒寫時預設就是 'text'）。 */
function texts(r) {
  if (!r) return [];
  return [...r.querySelectorAll('input,textarea')]
    .filter(e => (e.tagName === 'TEXTAREA' || e.type === 'text') &&
      !e.closest('.ant-select') && !(e.placeholder || '').includes('街道名稱'));
}
// 用「列標籤＋單位」或「列標籤＋第幾格」找文字格
function field(name, unit, nth) {
  const ts = texts(typeof name === 'string' ? row(name) : name);
  if (unit !== undefined && unit !== null) return ts.find(e => unitOf(e) === unit) || null;
  return ts[nth || 0] || null;
}
/* 出售樓層那列沒有標籤，用它的「出售單層／出售多層」下拉認。
   不要用單位認：單層時是「樓」，多層時變成兩格「層」（placeholder 出售最低/最高樓層），
   跟「出售總樓層」的「層」撞在一起（2026-10-14 AG1727776 透天踩過）。 */
function floorRow() {
  const s = [...document.querySelectorAll('.ant-select')]
    .find(x => /^出售(單|多)層$/.test(((x.querySelector('.ant-select-selection-item') || {}).innerText || '').trim()));
  return s ? s.closest('.ant-form-item') : null;
}
function selectIn(r, nth) {
  return r ? [...r.querySelectorAll('.ant-select')][nth || 0] || null : null;
}

function setVal(el, v) {
  if (!el || v === null || v === undefined || v === '') return;
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
  Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, String(v));
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

/* antd radio/checkbox：一定要點外層 wrapper，input.click() 沒用。
   要限定在哪一列找：「是／否／有」這種字好幾列都有（帶租約、保護電話、管理費）。 */
function wrapper(text, rowName) {
  const scope = rowName ? row(rowName) : document;
  if (!scope) return null;
  return [...scope.querySelectorAll('label.ant-radio-wrapper,label.ant-checkbox-wrapper')]
    .find(l => norm(l.innerText) === text) || null;
}
function pickRadio(text, rowName) {
  if (!text) return;
  const m = wrapper(text, rowName);
  if (!m) { log.push('找不到選項「' + (rowName ? rowName + '/' : '') + text + '」'); return; }
  if (!m.querySelector('.ant-radio-checked,.ant-checkbox-checked')) m.click();
}
function isPicked(text, rowName) {
  const m = wrapper(text, rowName);
  return !!(m && m.querySelector('.ant-radio-checked,.ant-checkbox-checked'));
}

/* antd 虛擬清單：打字過濾無效（只比對 value 的數字 id），必須捲動到選項被渲染出來。
   dropdown 要用 aria-controls 認自己那個。 */
async function pickSelect(sel, text, what) {
  if (!text) return 'skip';
  const inp = sel && sel.querySelector('input');
  if (!sel || !inp) return what + ' 的下拉找不到';
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(inp, ''); inp.dispatchEvent(new Event('input', { bubbles: true }));
  /* ⚠️ 只認 aria-controls 指到的那個 dropdown，**絕對不要**用「抓 document 最後一個」當備援。
     antd 關掉選單後節點會留在 DOM 而且不會加 hidden class，備援會撈到上一個 select 的清單——
     2026-09-19 就是這樣害「出售型態」跑去鄉鎮的清單裡找「出售多層」，當然找不到。 */
  const ac = inp.getAttribute('aria-controls');
  if (!ac) return what + ' 沒有 aria-controls，認不出它的選單';
  let dd = null;
  for (let t = 0; t < 12 && !dd; t++) {
    if (t % 4 === 0)
      sel.querySelector('.ant-select-selector')
         .dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    await sleep(250);
    const n = document.getElementById(ac);
    dd = n ? n.closest('.ant-select-dropdown') : null;
    if (dd && !dd.querySelector('.ant-select-item-option')) dd = null;  // 還沒渲染完
  }
  if (!dd) return what + ' 開不出選單';
  const holder = dd.querySelector('.rc-virtual-list-holder') || dd;
  let stuck = 0;
  for (let s = 0; s < 60; s++) {
    const opts = [...dd.querySelectorAll('.ant-select-item-option')];
    const m = opts.find(o => (o.title || o.innerText).trim() === text);
    if (m) {
      m.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await sleep(350);
      const si = sel.querySelector('.ant-select-selection-item');
      return si ? si.innerText : '(空)';
    }
    const before = holder.scrollTop;
    holder.scrollTop = before + 200;
    holder.dispatchEvent(new Event('scroll', { bubbles: true }));
    await sleep(140);
    // 捲不動要連續兩次才算到底：第一圈清單常常還沒撐出高度
    stuck = (holder.scrollTop === before) ? stuck + 1 : 0;
    if (stuck >= 2)
      return '找不到「' + text + '」，清單全部選項:' +
        [...dd.querySelectorAll('.ant-select-item-option')]
          .map(o => (o.title || o.innerText).trim()).join('/');
  }
  return '捲太多次';
}

// 關掉目前開著的下拉／面板。不關的話下一個 pickSelect 會抓到上一個的清單（踩過）
async function closePopups() {
  document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  document.body.click();
  await sleep(400);
}

/* 街道不是 antd select，是「搜尋框＋街名格子」。
   ⚠️ 鄉鎮選完之後街道清單要跟後端要資料，太早搜會是空的——所以要等面板出現、再重試幾次。 */
async function pickStreet(sel, name) {
  if (!name) return 'skip';
  if (!sel) return '找不到街道元件';
  /* ⚠️ 街道面板只有 mousedown 打不開，要完整 pointer 序列＋focus（其他 select 用 mousedown 就夠）。
     注意它自己的 ant-select dropdown 會顯示「無此資料」，那是正常的——真正的清單在另一個面板裡。 */
  const sc = sel.querySelector('.ant-select-selector'), sinp = sel.querySelector('input');
  let box = null;
  for (let t = 0; t < 10 && !box; t++) {
    if (t % 3 === 0) {
      ['pointerdown', 'mousedown', 'mouseup', 'click']
        .forEach(ev => sc.dispatchEvent(new MouseEvent(ev, { bubbles: true, cancelable: true })));
      if (sinp) sinp.focus();
    }
    await sleep(400);
    box = [...document.querySelectorAll('input')]
      .find(i => (i.placeholder || '').includes('街道名稱')) || null;
  }
  if (!box) return '街道面板開不出來（縣市/鄉鎮選好了嗎？）';
  /* 等街名清單真的載入（出現「第1/N頁」）才搜。2026-10-14 只等固定 600ms，
     鄉鎮剛選完清單還沒回來，三次搜尋全落空。 */
  let panel = box;
  for (let k = 0; k < 5 && panel; k++) panel = panel.parentElement;
  for (let t = 0; t < 20 && panel && !/第\d+\/\d+頁/.test(panel.innerText); t++) await sleep(250);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  for (let attempt = 0; attempt < 5; attempt++) {
    setter.call(box, name); box.dispatchEvent(new Event('input', { bubbles: true }));
    const btn = box.parentElement.querySelector('button');
    if (btn) ['mousedown', 'mouseup', 'click']
      .forEach(t => btn.dispatchEvent(new MouseEvent(t, { bubbles: true })));
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
    await sleep(900 + attempt * 400);
    const hit = [...document.querySelectorAll('li,span,div')]
      .find(e => e.children.length === 0 && e.innerText.trim() === name);
    if (hit) {
      ['mousedown', 'mouseup', 'click']
        .forEach(t => hit.dispatchEvent(new MouseEvent(t, { bubbles: true })));
      await sleep(500);
      const si = sel.querySelector('.ant-select-selection-item');
      return si ? si.innerText : name;
    }
  }
  return '搜不到街道「' + name + '」（清單可能還沒載入，或街名跟來源頁寫法不同）';
}

// 特色描述是 ProseMirror，innerText= 沒用，要 execCommand 一行一行打
function fillDesc(lines) {
  const pm = document.querySelector('[contenteditable=true].ProseMirror');
  if (!pm) return '找不到富文本框';
  pm.focus();
  const sel = window.getSelection(), r = document.createRange();
  r.selectNodeContents(pm); sel.removeAllRanges(); sel.addRange(r);
  document.execCommand('delete');
  lines.forEach((ln, i) => {
    if (i) document.execCommand('insertParagraph');
    if (ln) document.execCommand('insertText', false, ln);
  });
  /* ⚠️ 打完一定要 blur：591 好像是編輯器失焦時才把內容寫回表單。AG1918099 用程式按保存（沒失焦），
     畫面上有字但存進去是空的，前台顯示「暫未添加說明」；前兩筆是滑鼠點保存（會失焦）所以沒事。 */
  pm.blur();
  pm.dispatchEvent(new FocusEvent('focusout', { bubbles: true }));
  return pm.innerText.slice(0, 40) + '…';
}

(async () => {
  const D = DATA;
  // 1. 會讓版面多長格子的單選先點，後面的格子才找得到（車位面積列、管理費金額格）
  pickRadio(D.areaParking ? '含車位面積' : '不含車位面積', '權狀坪數');
  pickRadio(D.mgmtFee ? '有' : '無', '管理費');
  await sleep(500);

  // 2. 下拉（會觸發重繪）
  const addr = () => [...(row('出售地址') || document).querySelectorAll('.ant-select')];
  const rCity = await pickSelect(addr()[0], D.city, '縣市');         await closePopups();
  const rDist = await pickSelect(addr()[1], D.district, '鄉鎮');     await closePopups();
  await sleep(600);                       // 等街道清單跟後端要完資料
  const rStreet = await pickStreet(addr()[2], D.street);              await closePopups();
  const rFloorType = await pickSelect(selectIn(floorRow()), D.floorType, '出售型態'); await closePopups();
  const rOrient = await pickSelect(selectIn(row('朝向')), D.orientation, '朝向');    await closePopups();
  const rPark = D.areaParking
    ? await pickSelect(selectIn(row('車位面積')), D.parkingType, '車位類型') : 'skip';
  await closePopups();

  // 3. 純文字欄位：每次都現場用標籤找，重繪後不會對錯格
  const spec = [
    ['巷', () => field('出售地址', '巷'), D.lane],
    ['弄', () => field('出售地址', '弄'), D.alley],
    ['號', () => field('出售地址', '號'), D.no],
    ['之', () => field('出售地址', null, 3), D.noSub],
    ['樓層', () => field(floorRow(), null, 0), D.floorFrom],
    ['樓層2', () => field(floorRow(), null, 1), D.floorTo],
    ['總樓層', () => field('出售總樓層'), D.totalFloors],
    ['社區', () => field('社區名稱'), D.community],
    ['房', () => field('格局', '房'), D.rooms],
    ['廳', () => field('格局', '廳'), D.halls],
    ['衛', () => field('格局', '衛'), D.baths],
    ['陽台', () => field('格局', '陽台'), D.balcony],
    ['年', () => field('建築完工時間', '年'), D.builtY],
    ['月', () => field('建築完工時間', '月'), D.builtM],
    ['日', () => field('建築完工時間', '日'), D.builtD],
    ['權狀坪數', () => field('權狀坪數'), D.areaTotal],
    ['車位面積', () => field('車位面積', '坪'), D.areaParking],
    ['主建物', () => field('主建物'), D.areaMain],
    ['附屬建物', () => field('附屬建物'), D.areaAnnex],
    ['共有部分', () => field('共有部分'), D.areaPublic],
    ['土地坪數', () => field('土地坪數'), D.landArea],
    ['售價', () => field('售價', '萬元'), D.price],
    ['管理費', () => field('管理費', '元/月'), D.mgmtFee],
    ['捷運站', () => field('附近交通', '捷運站'), D.mrt],
    ['標題', () => field('廣告標題'), D.title],
  ].filter(s => s[2] !== null && s[2] !== undefined && s[2] !== '');
  for (const [, f, v] of spec) setVal(f(), v);

  // 4. 其他單選（限定列，避免「是／否」對到別列）
  pickRadio('成屋', '建築完工時間');
  pickRadio((D.parkingInPrice ?? !!D.areaParking) ? '含車位價格' : '不含車位價格', '售價');
  pickRadio('否', '帶租約');
  pickRadio('簡易裝潢', '裝潢程度');
  pickRadio(D.contract, '委託書');
  pickRadio('收取服務費', '服務費');
  if (D.hideNo) pickRadio('隱藏門號', '出售地址');
  /* 生活機能／特色標籤是同一組 checkbox 共用一個陣列狀態：連續點太快，後一下會用舊狀態蓋掉前一下
     （2026-10-14 實測：一口氣點 4 個只剩 2 個勾著）。每點一下等 250ms，最後再補一輪沒勾上的。 */
  for (let round = 0; round < 2; round++) {
    for (const [list, rowName] of [[D.amenities || [], '生活機能'], [D.tags || [], '特色標籤']])
      for (const t of list)
        if (!isPicked(t, rowName)) { pickRadio(t, rowName); await sleep(250); }
    await sleep(300);
  }

  // 5. 文案（結尾自動補聯絡方式）
  const desc = D.desc.some(l => l.includes('line.me/ti/p/')) ? D.desc : D.desc.concat(CONTACT);
  const rDesc = fillDesc(desc);

  /* 社區名稱大樓案必填：591 沒自動帶出、DATA 也沒給時填「無」（591 自己的提示就這樣寫）。
     只在格子還是空的時候補，不要蓋掉 591 依地址帶出的社區名。AG1918099（店住、無社區名）踩過。 */
  const comm = field('社區名稱');
  if (comm && !comm.value) setVal(comm, '無');

  // 6. 回讀驗證，被重繪清掉的自動補一次
  await sleep(500);
  const missed = [];
  for (const [name, f, v] of spec) {
    const el = f();
    if (el && el.value !== String(v)) { setVal(el, v); missed.push(name); }
  }
  await sleep(400);
  const bad = [];
  for (const [name, f, v] of spec) {
    const el = f();
    if (!el || el.value !== String(v))
      bad.push(name + ' 想填' + v + ' 實際' + (el ? el.value : '(找不到這格)'));
  }
  const selNow = s => s ? ((s.querySelector('.ant-select-selection-item') || {}).innerText || '(空)') : '(找不到)';
  const radios = [
    ['成屋', '建築完工時間'], [D.areaParking ? '含車位面積' : '不含車位面積', '權狀坪數'],
    [(D.parkingInPrice ?? !!D.areaParking) ? '含車位價格' : '不含車位價格', '售價'], [D.mgmtFee ? '有' : '無', '管理費'],
    ['否', '帶租約'], ['簡易裝潢', '裝潢程度'], [D.contract, '委託書'], ['收取服務費', '服務費'],
  ].concat(D.hideNo ? [['隱藏門號', '出售地址']] : [])
   .concat((D.amenities || []).map(t => [t, '生活機能']), (D.tags || []).map(t => [t, '特色標籤']));
  return JSON.stringify({
    下拉: { 縣市: rCity, 鄉鎮: rDist, 街道: rStreet, 出售型態: rFloorType, 朝向: rOrient, 車位類型: rPark },
    現況: {
      縣市: selNow(addr()[0]), 鄉鎮: selNow(addr()[1]), 街道: selNow(addr()[2]),
      出售型態: selNow(selectIn(floorRow())), 朝向: selNow(selectIn(row('朝向'))),
      車位類型: D.areaParking ? selNow(selectIn(row('車位面積'))) : '-',
      管理費週期: D.mgmtFee ? selNow(selectIn(row('管理費'))) : '-',
      社區: (field('社區名稱') || {}).value,   // 591 可能自動改成它資料庫的名字，人工看一眼
    },
    單選: radios.map(([t, r]) => t + (isPicked(t, r) ? '✓' : '✗')),
    文案: rDesc,
    補填過: missed,
    對不上: bad,          // 空陣列＝全部正確，非空就要人工看
    警告: log,
  }, null, 1);
})();
