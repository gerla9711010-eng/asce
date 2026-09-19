/* 591 出售表單一次填完。用法：把這整份貼進 mcp__claude-in-chrome__javascript_tool，
   最上面的 DATA 換成這件案子的值，一次呼叫填完整頁並回傳驗證結果。

   為什麼要這樣做：一格一格點擊打字慢到使用者會中斷（2026-09-19 實測）。
   591 是 React + antd，直接操作 DOM 事件比模擬滑鼠快一個數量級，而且不受捲動位移影響。

   填寫順序是有意義的：會觸發重繪的元件（三段地址、出售型態、朝向）先填，
   純文字欄位後填，最後回讀驗證並自動補回被重繪清掉的格子。

   沒有的欄位（例：透天沒有車位面積、大樓沒有土地坪數）在 DATA 裡留 null 就會跳過。 */

const DATA = {
  city: '高雄市', district: '前鎮區', street: '公正路',
  lane: '47', alley: '', no: '1', noSub: '', hideNo: true,
  floorType: '出售多層',      // '出售單層' | '出售多層'
  floorFrom: '1', floorTo: '3',
  totalFloors: '3',
  community: '',              // 透天留空
  rooms: '5', halls: '2', baths: '3', balcony: '',
  builtY: '66', builtM: '8', builtD: '30',   // 民國
  orientation: '坐東南朝西北',
  areaTotal: '37.15',         // 權狀坪數
  areaMain: '37.15', areaAnnex: '0', areaPublic: '0',
  areaParking: null,          // 有車位才填
  parkingType: null,          // '平面式停車位' | '機械式停車位' | '平面式+機械式'
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
};

/* ---------- 以下不用改 ---------- */
const sleep = ms => new Promise(r => setTimeout(r, ms));
const all = () => [...document.querySelectorAll('input,select,textarea')];
const log = [];

function setVal(el, v) {
  if (!el || v === null || v === undefined || v === '') return;
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
  Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, String(v));
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// antd radio/checkbox：一定要點外層 wrapper，input.click() 沒用
function pickRadio(text) {
  if (!text) return;
  const m = [...document.querySelectorAll('label.ant-radio-wrapper,label.ant-checkbox-wrapper')]
    .find(l => l.innerText.replace(/\s+/g, '') === text);
  if (!m) { log.push('找不到選項「' + text + '」'); return; }
  if (!m.querySelector('.ant-radio-checked,.ant-checkbox-checked')) m.click();
}

function isPicked(text) {
  const m = [...document.querySelectorAll('label.ant-radio-wrapper,label.ant-checkbox-wrapper')]
    .find(l => l.innerText.replace(/\s+/g, '') === text);
  return !!(m && m.querySelector('.ant-radio-checked,.ant-checkbox-checked'));
}

/* antd 虛擬清單：打字過濾無效（只比對 value 的數字 id），必須捲動到選項被渲染出來。
   dropdown 要用 aria-controls 認自己那個，抓 document 最後一個會抓到別的 select 的。 */
/* 用 .ant-select 的序號定位，不要用 input 的全域索引——選完縣市/鄉鎮之後
   街道面板會塞進新的 input，全域索引就整排位移了（踩過）。
   目前版面：0 縣市｜1 鄉鎮｜2 街道｜3 出售型態｜4 朝向｜5 坪(單位)｜6 管理費｜7,8 公車站 */
const SEL = { city: 0, district: 1, street: 2, floorType: 3, orientation: 4 };

async function pickSelect(which, text) {
  if (!text) return 'skip';
  const sel = [...document.querySelectorAll('.ant-select')][which];
  const inp = sel && sel.querySelector('input');
  if (!sel || !inp) return 'ant-select#' + which + ' 找不到';
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(inp, ''); inp.dispatchEvent(new Event('input', { bubbles: true }));
  /* ⚠️ 只認 aria-controls 指到的那個 dropdown，**絕對不要**用「抓 document 最後一個」當備援。
     antd 關掉選單後節點會留在 DOM 而且不會加 hidden class，備援會撈到上一個 select 的清單——
     2026-09-19 就是這樣害「出售型態」跑去鄉鎮的清單裡找「出售多層」，當然找不到。 */
  const ac = inp.getAttribute('aria-controls');
  if (!ac) return 'ant-select#' + which + ' 沒有 aria-controls，認不出它的選單';
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
  if (!dd) return 'ant-select#' + which + ' 開不出選單';
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
async function pickStreet(name) {
  if (!name) return 'skip';
  const sel = [...document.querySelectorAll('.ant-select')][SEL.street];
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
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  for (let attempt = 0; attempt < 3; attempt++) {
    setter.call(box, name); box.dispatchEvent(new Event('input', { bubbles: true }));
    const btn = box.parentElement.querySelector('button');
    if (btn) ['mousedown', 'mouseup', 'click']
      .forEach(t => btn.dispatchEvent(new MouseEvent(t, { bubbles: true })));
    box.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', keyCode: 13, bubbles: true }));
    await sleep(900);
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
  return pm.innerText.slice(0, 40) + '…';
}

(async () => {
  const D = DATA;
  // 1. 會觸發重繪的元件先做
  const rCity = await pickSelect(SEL.city, D.city);        await closePopups();
  const rDist = await pickSelect(SEL.district, D.district); await closePopups();
  await sleep(600);                       // 等街道清單跟後端要完資料
  const rStreet = await pickStreet(D.street);              await closePopups();
  const rFloorType = await pickSelect(SEL.floorType, D.floorType); await closePopups();
  const rOrient = await pickSelect(SEL.orientation, D.orientation); await closePopups();

  // 2. 純文字欄位（索引在重繪後才抓）
  const es = all();
  const text = {
    3: D.lane, 4: D.alley, 5: D.no, 6: D.noSub,
    9: D.floorFrom, 10: D.floorTo, 11: D.totalFloors, 12: D.community,
    13: D.rooms, 14: D.halls, 15: D.baths, 16: D.balcony,
    19: D.builtY, 20: D.builtM, 21: D.builtD,
    24: D.areaTotal, 28: D.areaMain, 29: D.areaAnnex, 30: D.areaPublic,
    32: D.landArea, 34: D.price, 60: D.mrt, 62: D.title,
  };
  for (const k in text) setVal(es[k], text[k]);

  // 3. 單選（成屋、車位、價格、管理費、租約、裝潢、委託書、服務費）
  ['成屋', D.areaParking ? '含車位面積' : '不含車位面積',
   D.areaParking ? '含車位價格' : '不含車位價格',
   D.mgmtFee ? '有' : '無', '否', '簡易裝潢', D.contract, '收取服務費']
    .forEach(pickRadio);
  if (D.hideNo) pickRadio('隱藏門號');
  await sleep(300);

  // 4. 文案
  const rDesc = fillDesc(D.desc);

  // 5. 回讀驗證，被重繪清掉的自動補一次
  await sleep(500);
  const e2 = all(), missed = [];
  for (const k in text) {
    const want = text[k];
    if (want === null || want === undefined || want === '') continue;
    if (e2[k] && e2[k].value !== String(want)) { setVal(e2[k], want); missed.push(k); }
  }
  await sleep(400);
  const e3 = all(), bad = [];
  for (const k in text) {
    const want = text[k];
    if (want === null || want === undefined || want === '') continue;
    if (!e3[k] || e3[k].value !== String(want))
      bad.push(k + ' 想填' + want + ' 實際' + (e3[k] ? e3[k].value : '(無此格)'));
  }
  const selNow = i => {
    const s = [...document.querySelectorAll('.ant-select')][i];
    return s ? ((s.querySelector('.ant-select-selection-item') || {}).innerText || '(空)') : '?';
  };
  return JSON.stringify({
    下拉: { 縣市: rCity, 鄉鎮: rDist, 街道: rStreet, 出售型態: rFloorType, 朝向: rOrient },
    現況: { 縣市: selNow(SEL.city), 鄉鎮: selNow(SEL.district), 街道: selNow(SEL.street), 出售型態: selNow(SEL.floorType), 朝向: selNow(SEL.orientation) },
    單選: ['成屋', '不含車位面積', '不含車位價格', '無', '否', '簡易裝潢', D.contract,
           '收取服務費', '隱藏門號'].map(t => t + (isPicked(t) ? '✓' : '✗')),
    文案: rDesc,
    補填過: missed,
    對不上: bad,          // 空陣列＝全部正確，非空就要人工看
    警告: log,
  }, null, 1);
})();
