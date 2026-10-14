/* 591 第 3 頁「確認刊登方案」：取消所有加購 → 確認應付 0 元 → 送出；第 4 頁拿廣告網址。
   用法：整份貼進 mcp__claude-in-chrome__javascript_tool，跑兩次：
     1. MODE='pay'  （第 3 頁）取消加購、驗 0 元、按送出。應付不是 0 或還有勾選就**不會**按。
     2. MODE='done' （第 4 頁，等 2~3 秒後）關掉挽留彈窗、回傳廣告網址。
   分兩次是因為按送出會換頁，同一次 javascript 呼叫會跟著頁面一起死掉。

   為什麼這樣寫（都踩過）：
   - 加購是預設勾的（2026-10-14 AA1072581：精選推薦＋同意自動續費＋AI 助手，應付 2,856 元）。
   - 要**先取消「同意自動續費」再取消推廣本體**，順序反了子選項會殘留。
   - 狀態看外層 `.ant-checkbox-checked`，不要看 input.checked（591 的 name 都一樣，DOM 狀態不可信）。
   - 送出按鈕的字 591 改過（「確認刊登方案」／「立即支付」），兩個都認。0 元時按它就是送出，不扣錢。
   - 第 4 頁的「你還可以買OOO」挽留彈窗按右上 X 關掉，不要點裡面的「立即支付」。 */

const MODE = 'pay';   // 'pay' | 'done'

const sleep = ms => new Promise(r => setTimeout(r, ms));
const boxes = () => [...document.querySelectorAll('label.ant-checkbox-wrapper')];
const on = l => !!l.querySelector('.ant-checkbox-checked');
const state = () => boxes().map(l => (l.innerText.trim().slice(0, 14) || '(推廣本體)') + '=' + (on(l) ? 'V' : '-'));
const pay = () => {
  const m = document.body.innerText.match(/應付金額：\s*([\d,]+)\s*元/);
  return m ? Number(m[1].replace(/,/g, '')) : null;
};

await (async () => {
  if (MODE === 'done') {
    if (!/\/post\/four\//.test(location.pathname))
      return JSON.stringify({ 錯誤: '不在第 4 頁（刊登成功頁）：' + location.pathname });
    const x = document.querySelector('.ant-modal .ant-modal-close');
    if (x) { x.click(); await sleep(500); }
    const id = (location.pathname.match(/house\/(\d+)/) || [])[1];
    return JSON.stringify({
      成功: /廣告刊登成功/.test(document.body.innerText),
      物件編號: id || null,
      廣告網址: id ? 'https://sale.591.com.tw/home/house/detail/2/' + id + '.html' : null,
    }, null, 1);
  }

  if (!/\/post\/three\//.test(location.pathname))
    return JSON.stringify({
      錯誤: '不在第 3 頁：' + location.pathname,
      // 還在第 2 頁通常是保存被表單驗證擋下來，把紅字列出來
      表單錯誤: [...document.querySelectorAll('.ant-form-item-explain-error')].map(e => e.innerText).slice(0, 10),
    });
  const before = { 勾選: state(), 應付: pay() };

  // 1. 自動續費先關
  const renew = boxes().find(l => l.innerText.includes('自動續費'));
  if (renew && on(renew)) { renew.click(); await sleep(1000); }
  // 2. 其他還勾著的逐一取消（每點一次就重抓，取消推廣本體會讓子選項消失/重繪）
  for (let i = 0; i < 8; i++) {
    const c = boxes().find(on);
    if (!c) break;
    c.click(); await sleep(1200);
  }
  await sleep(500);
  const after = { 勾選: state(), 應付: pay() };
  const clean = !boxes().some(on) && after.應付 === 0;

  let result;
  if (!clean) {
    result = '沒送出：應付 ' + after.應付 + ' 元／還有勾選 → 停下來問使用者，不要自己付錢';
  } else {
    const btn = [...document.querySelectorAll('button')]
      .find(b => /^(確認刊登方案|立即支付)$/.test(b.innerText.trim()));
    if (!btn) result = '找不到送出按鈕';
    else {
      setTimeout(() => btn.click(), 300);   // 先回傳再按，換頁才不會吃掉回傳值
      result = '已按送出（' + btn.innerText.trim() + '）→ 等 2~3 秒跑 MODE=done';
    }
  }
  return JSON.stringify({ 取消前: before, 取消後: after, 乾淨: clean, 結果: result }, null, 1);
})();
