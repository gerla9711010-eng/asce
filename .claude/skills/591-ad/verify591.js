/* 591 刊登後前台驗收：在廣告頁（sale.591.com.tw/home/house/detail/2/{編號}.html）執行，
   跟填進去的 DATA 逐項比對，回傳「對不上」清單。用法：DATA 貼跟 fill591.js 同一份（含 desc），整份貼進 javascript_tool。

   為什麼要這支（2026-10-14）：AG1918099 表單上有文案、前台卻是「暫未添加說明」，是使用者自己發現的。
   前台才是買方看到的版本，591 也會自己改寫（社區名、車位說明），只看表單不夠。刊登後馬上就看得到，不用等 3 分鐘。
   注意：591 會把坪數尾巴的 0 吃掉（24.60 → 24.6），所以坪數一律比數值。 */

const DATA = { /* 貼 fill591.js 用的那份 */ };

const EXPECT_BROKER = '凱璿誼峰不動產有限公司';
const CONTACT_MARK = 'line.me/ti/p/kg1pMk4vX8';

const sleep = ms => new Promise(r => setTimeout(r, ms));
await (async () => {
  const D = DATA;
  if (!/sale\.591\.com\.tw\/home\/house\/detail/.test(location.href))
    return JSON.stringify({ 錯誤: '不在 591 廣告頁：' + location.href });
  for (let t = 0; t < 20 && !document.body.innerText.includes('屋況特色'); t++) await sleep(500);
  const T = document.body.innerText;
  // 「標籤\n：\n值」或「值\n標籤」兩種排法
  const after = label => { const m = T.match(new RegExp(label + '\\s*[:：]?\\s*\\n\\s*[:：]?\\s*([^\\n]+)')); return m ? m[1].trim() : null; };
  const before = label => { const m = T.match(new RegExp('([^\\n]+)\\n\\s*' + label + '\\s*\\n')); return m ? m[1].trim() : null; };
  const num = s => s == null ? null : Number(String(s).replace(/[^\d.]/g, ''));
  const bad = [], ok = [];
  const chk = (name, want, got, eq) => {
    if (want === null || want === undefined || want === '') return;
    const pass = eq ? eq(want, got) : String(got) === String(want);
    (pass ? ok : bad).push(name + (pass ? '' : '：要「' + want + '」前台「' + got + '」'));
  };
  const sameNum = (a, b) => b != null && Math.abs(Number(a) - Number(b)) < 0.001;

  const desc = (T.split('屋況特色')[1] || '').split(/買房知識|查看更多內容/)[0].trim();
  const floor = D.floorType === '出售多層'
    ? D.floorFrom + 'F~' + D.floorTo + 'F/' + D.totalFloors + 'F'
    : D.floorFrom + 'F/' + D.totalFloors + 'F';

  chk('標題', D.title && D.title.replace(/\s+/g, ''), (document.querySelector('h1') || {}).innerText?.trim().replace(/\s+/g, ''));
  chk('售價', D.price, num((T.match(/([\d,]+)\s*萬元/) || [])[1]), sameNum);
  chk('含車位價格', (D.parkingInPrice ?? !!D.areaParking) ? '含車位價格' : '不含車位價格',
      T.includes('（含車位價格）') ? '含車位價格' : '不含車位價格');
  chk('格局', D.rooms + '房' + D.halls + '廳' + D.baths + '衛', before('格局'));
  chk('權狀坪數', D.areaTotal, num(before('權狀坪數')), sameNum);
  chk('樓層', floor, after('樓層'));
  chk('主建物', D.areaMain, num(after('主建物')), sameNum);
  chk('附屬建物', Number(D.areaAnnex) ? D.areaAnnex : null, num(after('附屬建物')), sameNum);
  chk('共有部分', Number(D.areaPublic) ? D.areaPublic : null, num(after('共用部分')), sameNum);
  chk('管理費', D.mgmtFee ? D.mgmtFee + '元/月' : '無', after('管理費'));
  chk('帶租約', '否', after('帶租約'));
  chk('裝潢', '簡易裝潢', after('裝潢程度'));
  chk('文案有存進去', true, desc.length > 30 && !desc.includes('暫未添加'));
  chk('文案開頭', D.desc && D.desc[0], desc.split('\n')[0].trim());
  chk('LINE／電話', true, desc.includes(CONTACT_MARK) && desc.includes('0912877583'));
  chk('經紀業名稱', EXPECT_BROKER, after('經紀業名稱'));

  return JSON.stringify({
    對不上: bad,                // 空陣列＝前台跟 DATA 一致
    通過: ok.length + ' 項',
    參考: {                     // 591 自己改寫或自動帶的，人看一眼
      社區: after('社區'), 車位: after('車位'), 所屬公司: after('所屬公司'),
      附近交通: after('附近交通'), 屋齡: before('屋齡'),
    },
  }, null, 1);
})();
