/* 591 編輯頁（換物件）的照片區。用法：整份貼進 mcp__claude-in-chrome__javascript_tool。
   MODE='clear'：房屋照片「全選」→「刪除選中」，格局圖有舊的也刪掉；回傳刪完剩幾張（要是 0）。
   MODE='count'：上傳後數張數、看還有沒有在上傳中，跟 KEIS 張數對得上才往下。
   上傳本身不在這裡：一次 find 拿兩個 file input 的 ref（房屋照片／格局圖），再用 file_upload 整批傳。

   2026-10-21 EG0517920 換進 S20698894 實測：全選＋刪除選中沒有跳確認框，畫面出「圖片刪除成功」；
   刪除只動表單，按「確認修改」前不會生效。 */
const MODE = 'clear';

await (async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const sec = name => [...document.querySelectorAll('.ant-form-item')]
    .find(it => (it.querySelector('.ant-form-item-label')?.innerText || '').includes(name));
  const count = () => {
    const p = sec('房屋照片'), f = sec('格局圖');
    return {
      房屋照片: p ? p.querySelectorAll('img').length : '找不到區塊',
      格局圖: f ? f.querySelectorAll('img').length : '找不到區塊',
      上傳中: document.querySelectorAll('.ant-upload-list-item-uploading,.ant-progress').length,
    };
  };
  if (MODE === 'count') { await sleep(3000); return JSON.stringify(count()); }

  const before = count();
  const p = sec('房屋照片');
  if (p && p.querySelectorAll('img').length) {
    const all = [...p.querySelectorAll('label.ant-checkbox-wrapper')].find(l => l.innerText.trim() === '全選');
    if (!all) return '找不到「全選」';
    if (!all.querySelector('.ant-checkbox-checked')) all.click();
    await sleep(400);
    const del = [...p.querySelectorAll('a')].find(a => a.innerText.trim() === '刪除選中');
    if (!del) return '找不到「刪除選中」';
    del.click();
    await sleep(1200);
  }
  /* 格局圖只有一張，用卡片上的垃圾桶刪（沒有全選）。找不到就回報，人工刪。 */
  const f = sec('格局圖');
  let floorNote = '';
  if (f && f.querySelectorAll('img').length) {
    const bin = f.querySelector('[class*=delete],[class*=remove],.anticon-delete');
    if (bin) { bin.click(); await sleep(800); } else floorNote = '格局圖有舊圖但找不到刪除鈕，人工刪';
  }
  return JSON.stringify({ 刪除前: before, 刪除後: count(), 備註: floorNote });
})();
