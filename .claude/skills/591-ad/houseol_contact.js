/* houseol 來源頁（print19）只抓聯絡資訊＋大樓名稱，一次可查多筆。
   用法：分頁先開任一 hq.houseol.com.tw 頁面（同源才帶得到登入 cookie；剛 navigate 完第一次呼叫常失敗，再呼叫一次），
   CASES 換成案號，整份貼進 javascript_tool。

   為什麼要有（2026-10-21）：物件資料改走 KEIS API，但 KEIS 只有承辦人姓名、沒有電話也沒有大樓名稱；
   使用者要「每個廣告位都知道該聯絡誰」，來源頁有。只回這幾格，不用把整頁重打成檔案。
   結果寫進 ledger591.py（--agent --phone --store），大樓名稱給 prep.py --community。
   ⚠️ fetch 回來的文件沒排版，innerText 不會在儲存格之間插空白（承辦人/行動全抓不到，踩過）→ 用 td 拼。
   ⚠️ 大樓名稱空白時不能跨行抓，會抓到下一格的「總」（AG1918099 以前也踩過）。 */
const CASES = ['AA1084264'];

await (async () => {
  const out = {};
  for (const no of CASES) {
    const r = await fetch('/auto.asp?m=SellHouse&f=print19&torf=false&listbox=' + no + '%23001&LoginPrint=1', { credentials: 'include' });
    const buf = await r.arrayBuffer();
    // 頁面可能是 big5，照 content-type／meta 的 charset 解，不要直接 r.text()
    const head = new TextDecoder('latin1').decode(buf.slice(0, 2000));
    const cs = ((r.headers.get('content-type') || '') + head).match(/charset=["']?([\w-]+)/i);
    const doc = new DOMParser().parseFromString(new TextDecoder(cs ? cs[1] : 'utf-8').decode(buf), 'text/html');
    const cells = [...doc.querySelectorAll('td')].filter(td => !td.querySelector('td'))
      .map(td => td.textContent.replace(/\s+/g, ' ').trim()).filter(Boolean);
    const t = cells.join('\n');
    const after = lab => { const i = cells.findIndex(c => c.replace(/\s/g, '') === lab); return i >= 0 ? cells[i + 1] || '' : ''; };
    const g = re => ((t.match(re) || [])[1] || '').trim();
    if (!/[售租]合約編號/.test(t)) { out[no] = { 錯誤: 'houseol 查無或沒登入' }; continue; }
    out[no] = {
      承辦人: after('承辦人'), 行動: after('行動'), 分店: after('分店'), 店電話: after('店電話'),
      大樓名稱: g(/大樓名稱：[ \t]*([^\s]*)/),
    };
  }
  return JSON.stringify(out);
})();
