/* 591 出租表單一次填完。用法：把這整份貼進 mcp__claude-in-chrome__javascript_tool，
   最上面的 DATA 換成這件案子的值，一次呼叫填完整頁並回傳驗證結果。

   跟出售版（../591-ad/fill591.js）最大的不同：**用欄位標籤找格子，不用全域索引**。
   出租表單每一列都是 .ant-form-item，左邊有自己的標籤（「可使用坪數」「租金」…），
   所以「找到那一列 → 列裡第幾格」就好，選完地址、重繪之後也不會整排位移。
   radio 也一律限定在同一列裡點：「無／有」在電梯、車位、管理費三列都有，全域找一定點錯。

   pickSelect／pickStreet／fillDesc 的眉角跟出售版一樣（antd 虛擬清單、街道面板、ProseMirror），
   改之前先看 ../591-ad/SKILL.md Step 3 那九條。

   開伙／養寵物／身份要求／提供設備／提供家具：**刻意不填**（使用者 2026-10-12 指示：自己加工）。
   沒有的欄位在 DATA 裡留 null 就會跳過。 */

const DATA = {
  city: '高雄市', district: '三民區', street: '博愛一路',
  lane: '', alley: '', no: '1', noSub: '', hideNo: true,
  floorType: null,            // 出租單層那格的下拉；null = 不動它（預設「出租單層」）
  floorFrom: '5', floorTo: '',   // 出租樓層；0 = 整棟
  totalFloors: '12',
  elevator: '有',             // '有' | '無'
  community: '',
  rooms: '2', halls: '1', baths: '1', balcony: '1',
  areaUse: '20.15',           // 可使用坪數 = trunc(主建物 + 附屬建物)，必填。用 print19 的 3 位小數算
  areaTotal: '30.67',         // 權狀坪數 = trunc(總建坪)，選填但照填
  parking: '無',              // '有' | '無'
  parkingType: null,          // 車位=有 時必填：'平面式' | '機械式' | '平面式 + 機械式' | '其他'
  parkingRent: '含租金內',     // 車位=有 時必填（車位租金列）：'含租金內' | '費用另計'。來源沒寫預設含（使用者 2026-10-12）
  builtY: '105', builtM: '8', builtD: '26',   // 民國
  orientation: '坐東南朝西北',
  decoration: '簡易裝潢',      // 固定（使用者偏好，跟出售一致）
  minLease: '1年',            // 固定 1年（使用者定案）。選項：'三個月' | '半年' | '1年' | '2年' | '其它'
  moveInNow: true,            // 勾「隨時可遷入」；false = 不動（日期要人工選）
  rent: '18000',              // 元/月
  deposit: '2個月',           // '免押金' | '1個月' | '2個月' | '面議' | '其他'
  includes: ['無'],          // 預設 ['無']，訴求重點寫明含才改。租金包含：['無'] 或 ['水費','電費','管理費',…]
  water: null,                // 水費列：'台水繳費' | '平分帳單' | '費用另計' | '其他' | null
  power: null,                // 電費列：'台電繳費' | '平分帳單' | '費用另計' | '其他' | null
  mgmtFee: null,              // 管理費列：數字（元/月）；null = 不動
  mrt: 'R11高雄車站',
  title: '博愛商圈電梯兩房',   // 6～20 字
  desc: ['【測試】'],
  propReg: '已辦產',          // 產權登記：'已辦產' | '未辦產'
  contract: '有簽訂',          // KEIS contract_type：一般委託→'有簽訂'；專任委託→'有簽訂專任約'
  feeWay: '半個月租金',        // 固定（使用者 2026-10-12 指示）
};

/* ---------- 以下不用改 ---------- */
const sleep = ms => new Promise(r => setTimeout(r, ms));
const log = [];

function setVal(el, v) {
  if (!el || v === null || v === undefined || v === '') return;
  const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
  Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, String(v));
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// 用左邊標籤的第一行找那一列（.ant-form-item）。只認最外層那個，巢狀的子 item 不算
function row(label) {
  return [...document.querySelectorAll('.ant-form-item')].find(f => {
    const l = f.querySelector('.ant-form-item-label');
    return l && l.innerText.trim().split('\n')[0] === label;
  }) || null;
}
// 出租樓層那列沒有標籤，用它的說明文字認
function floorRow() {
  return [...document.querySelectorAll('.ant-form-item')]
    .filter(f => f.innerText.includes('出租樓層0為整棟')).pop() || null;
}
// 列裡的純文字格（排除 antd select 的 search input 和街道搜尋框）
function texts(r) {
  if (!r) return [];
  return [...r.querySelectorAll('input')].filter(i =>
    !['radio', 'checkbox', 'file', 'search'].includes(i.type) &&
    !(i.placeholder || '').includes('街道名稱'));
}

// antd radio/checkbox：點外層 wrapper，而且限定在這一列裡。
// 選項文字有時黏著「(說明)」連結（產權登記的「已辦產 (說明)」），比對前拿掉
const norm = s => s.replace(/\s+/g, '').replace(/\(說明\)$/, '');
function opt(r, text) {
  return [...r.querySelectorAll('label.ant-radio-wrapper,label.ant-checkbox-wrapper')]
    .find(l => norm(l.innerText) === text);
}
function pick(r, text, label) {
  if (!text) return;
  if (!r) { log.push('找不到列「' + label + '」'); return; }
  const m = opt(r, text);
  if (!m) { log.push('「' + label + '」列裡找不到選項「' + text + '」'); return; }
  if (!m.querySelector('.ant-radio-checked,.ant-checkbox-checked')) m.click();
}
function picked(r, text) {
  const m = r && opt(r, text);
  return !!(m && m.querySelector('.ant-radio-checked,.ant-checkbox-checked'));
}

/* antd 虛擬清單（同出售版）：打字過濾無效，要捲到選項被渲染出來；
   dropdown 只認 aria-controls 指到的那個。這裡改成直接收 .ant-select 元素。 */
async function pickSelect(sel, text, name) {
  if (!text) return 'skip';
  const inp = sel && sel.querySelector('input');
  if (!sel || !inp) return name + ' 找不到';
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(inp, ''); inp.dispatchEvent(new Event('input', { bubbles: true }));
  const ac = inp.getAttribute('aria-controls');
  if (!ac) return name + ' 沒有 aria-controls，認不出它的選單';
  let dd = null;
  for (let t = 0; t < 12 && !dd; t++) {
    if (t % 4 === 0)
      sel.querySelector('.ant-select-selector')
         .dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
    await sleep(250);
    const n = document.getElementById(ac);
    dd = n ? n.closest('.ant-select-dropdown') : null;
    if (dd && !dd.querySelector('.ant-select-item-option')) dd = null;
  }
  if (!dd) return name + ' 開不出選單';
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
    stuck = (holder.scrollTop === before) ? stuck + 1 : 0;
    if (stuck >= 2)
      return '找不到「' + text + '」，清單全部選項:' +
        [...dd.querySelectorAll('.ant-select-item-option')]
          .map(o => (o.title || o.innerText).trim()).join('/');
  }
  return '捲太多次';
}

async function closePopups() {
  document.body.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
  document.body.click();
  await sleep(400);
}

// 街道（同出售版）：搜尋框＋街名格子，要完整 pointer 序列才打得開
async function pickStreet(sel, name) {
  if (!name) return 'skip';
  if (!sel) return '找不到街道元件';
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

/* 整頁跑完約 40～60 秒，會超過 javascript_tool 的 45 秒上限（2026-10-12 踩過：逾時但其實填完了）。
   所以背景跑，結果放 window.__fill591rent；貼完隔 30 秒用另一次呼叫讀 `window.__fill591rent`，
   還是「執行中」就再等。 */
window.__fill591rent = '執行中';
(async () => {
  const D = DATA;
  const addrSel = () => [...row('出租地址').querySelectorAll('.ant-select')];

  // 1. 會觸發重繪的元件先做
  const rCity = await pickSelect(addrSel()[0], D.city, '縣市');     await closePopups();
  const rDist = await pickSelect(addrSel()[1], D.district, '鄉鎮'); await closePopups();
  await sleep(600);
  const rStreet = await pickStreet(addrSel()[2], D.street);          await closePopups();
  const rFloorType = await pickSelect(floorRow()?.querySelector('.ant-select'), D.floorType, '出租單層');
  await closePopups();
  const rOrient = await pickSelect(row('朝向')?.querySelector('.ant-select'), D.orientation, '朝向');
  await closePopups();
  // 車位類型的下拉要先點「有」才會長出來
  pick(row('車位'), D.parking, '車位');
  await sleep(400);
  const rPark = D.parking === '有'
    ? await pickSelect(row('車位')?.querySelector('.ant-select'), D.parkingType, '車位類型') : 'skip';
  await closePopups();

  // 2. 文字格：[列, 第幾格, 值]。每次都重新找列，重繪過也不會錯位
  const T = [
    [() => row('出租地址'), 0, D.lane], [() => row('出租地址'), 1, D.alley],
    [() => row('出租地址'), 2, D.no],   [() => row('出租地址'), 3, D.noSub],
    [floorRow, 0, D.floorFrom], [floorRow, 1, D.floorTo],
    [() => row('出租總樓層'), 0, D.totalFloors],
    [() => row('社區名稱'), 0, D.community],
    [() => row('格局'), 0, D.rooms], [() => row('格局'), 1, D.halls],
    [() => row('格局'), 2, D.baths], [() => row('格局'), 3, D.balcony],
    [() => row('可使用坪數'), 0, D.areaUse],
    [() => row('權狀坪數'), 0, D.areaTotal],
    [() => row('建築完工時間'), 0, D.builtY], [() => row('建築完工時間'), 1, D.builtM],
    [() => row('建築完工時間'), 2, D.builtD],
    [() => row('租金'), 0, D.rent],
    [() => row('管理費'), 0, D.mgmtFee],
    [() => row('附近交通'), 2, D.mrt],      // 0,1 公車站｜2 捷運站｜3 火車站
    [() => row('廣告標題'), 0, D.title],
  ];
  const fill = () => T.forEach(([r, i, v]) => setVal(texts(r())[i], v));
  fill();

  // 3. 單選／複選（都限定在自己那一列）
  pick(row('電梯'), D.elevator, '電梯');
  pick(row('建築完工時間'), '成屋', '建築完工時間');
  pick(row('裝潢程度'), D.decoration, '裝潢程度');
  pick(row('最短租期'), D.minLease, '最短租期');
  if (D.moveInNow) pick(row('可遷入日'), '隨時可遷入', '可遷入日');
  pick(row('押金'), D.deposit, '押金');
  if (D.parking === '有') pick(row('車位租金'), D.parkingRent, '車位租金');  // 勾車位=有 才會長出來
  (D.includes || []).forEach(x => pick(row('租金包含'), x, '租金包含'));
  pick(row('水費'), D.water, '水費');
  pick(row('電費'), D.power, '電費');
  pick(row('產權登記'), D.propReg, '產權登記');
  pick(row('服務費'), '收取服務費', '服務費');
  pick(row('服務費收取方式'), D.feeWay, '服務費收取方式');
  pick(row('委託書'), D.contract, '委託書');
  if (D.hideNo) pick(row('出租地址'), '隱藏門號', '出租地址');
  await sleep(300);

  // 4. 文案
  const rDesc = fillDesc(D.desc);

  // 5. 回讀驗證，被重繪清掉的補一次，再驗一次
  await sleep(500);
  const diff = () => T.filter(([r, i, v]) => v !== null && v !== undefined && v !== '')
    .map(([r, i, v]) => { const el = texts(r())[i]; return [el, v, el ? el.value : '(無此格)']; })
    .filter(([el, v, got]) => got !== String(v));
  const missed = diff().length;
  if (missed) { fill(); await sleep(400); }
  const bad = diff().map(([el, v, got]) => '想填' + v + ' 實際' + got);

  const chk = [
    ['電梯', D.elevator], ['車位', D.parking], ['建築完工時間', '成屋'],
    ['裝潢程度', D.decoration], ['最短租期', D.minLease], ['押金', D.deposit],
    ['產權登記', D.propReg], ['服務費', '收取服務費'], ['服務費收取方式', D.feeWay],
    ['委託書', D.contract], ['車位租金', D.parking === '有' ? D.parkingRent : null], ['出租地址', D.hideNo ? '隱藏門號' : null],
    ['可遷入日', D.moveInNow ? '隨時可遷入' : null],
    ...(D.includes || []).map(x => ['租金包含', x]),
    ['水費', D.water], ['電費', D.power],
  ].filter(([, v]) => v).map(([l, v]) => l + ':' + v + (picked(row(l), v) ? '✓' : '✗'));

  const selNow = s => s ? ((s.querySelector('.ant-select-selection-item') || {}).innerText || '(空)') : '?';
  return JSON.stringify({
    下拉: { 縣市: rCity, 鄉鎮: rDist, 街道: rStreet, 出租單層: rFloorType, 朝向: rOrient, 車位類型: rPark },
    現況: { 縣市: selNow(addrSel()[0]), 鄉鎮: selNow(addrSel()[1]), 街道: selNow(addrSel()[2]),
            朝向: selNow(row('朝向')?.querySelector('.ant-select')) },
    單選: chk,            // 每項都要是 ✓
    文案: rDesc,
    補填過: missed,
    對不上: bad,          // 空陣列＝文字格全部正確
    警告: log,
  }, null, 1);
})().then(r => { window.__fill591rent = r; },
         e => { window.__fill591rent = '錯誤：' + e.message; });
'已開始，30 秒後讀 window.__fill591rent';
