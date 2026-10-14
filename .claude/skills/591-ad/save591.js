/* 591 第 2 頁：確認照片都傳完 → 按「保存資料，下一步」。
   用法：照片 file_upload 完之後，把 PHOTOS 改成這次上傳的「房屋照片」張數（格局圖不算），整份貼進 javascript_tool。

   為什麼要這支（2026-10-14）：原本要 find 按鈕 → 點 → 再開一次 javascript 確認，三次呼叫；
   而且確認那次如果 sleep 跨過換頁，會報「Inspected target navigated」。
   這支先輪詢到照片數對上（591 的「還可以上傳 N 張」，上限 30）才按，按的時候用 setTimeout，先回傳再換頁。
   張數一直對不上就**不按**，回傳實際張數讓人看。 */

const PHOTOS = 13;

const sleep = ms => new Promise(r => setTimeout(r, ms));
await (async () => {
  if (!/\/post\/two\//.test(location.pathname)) return JSON.stringify({ 錯誤: '不在第 2 頁：' + location.pathname });
  let got = null;
  for (let t = 0; t < 30; t++) {                 // 最多等 15 秒讓照片傳完
    const m = document.body.innerText.match(/還可以上傳(\d+)張照片/);
    got = m ? 30 - Number(m[1]) : null;
    const busy = /上傳中|uploading/i.test(document.body.innerText);
    if (got === PHOTOS && !busy) break;
    await sleep(500);
  }
  if (got !== PHOTOS)
    return JSON.stringify({ 結果: '沒按：房屋照片 ' + got + ' 張，預期 ' + PHOTOS + ' 張——人工看一下哪張沒傳上去' });
  const btn = [...document.querySelectorAll('button')].find(b => b.innerText.replace(/\s+/g, '') === '保存資料，下一步');
  if (!btn) return JSON.stringify({ 結果: '找不到「保存資料，下一步」按鈕' });
  setTimeout(() => btn.click(), 300);
  return JSON.stringify({ 結果: '照片 ' + got + ' 張 OK，已按保存 → 等 3 秒，到第 3 頁跑 pay0.js（MODE=pay）' });
})();
