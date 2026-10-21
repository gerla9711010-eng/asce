/* 591 編輯頁（換物件／改既有廣告）送出。用法：使用者說「送出」之後，整份貼進 javascript_tool，一次跑完。
   新刊（第 3 頁付款）不是這支，用 save591.js＋pay0.js。

   2026-10-21 S20698894、S21079307 實跑過的順序（按鈕都用文字找，不用座標）：
   ①頁面「確認修改」→ ②「溫馨提示：法定用途/現況/型態是否需要更新」型態已換好 →「無需更新」
   → ③「確認修改？…2次修改機會…將扣除1次」→「確認修改」→ ④「出售資訊修改成功！」＋付費「定時更新」推銷 → 右上 X。
   扣次說明不是「扣除1次」（例：次數用完、要扣 2 次）就停下來不按，回傳原文給使用者看。
   送出前先檢查：照片不是 0 張、沒有還在上傳的、文案不是空的（AG1918099 表單有字前台卻空過）。 */
const MIN_PHOTOS = 1;

await (async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const sec = n => [...document.querySelectorAll('.ant-form-item')]
    .find(it => (it.querySelector('.ant-form-item-label')?.innerText || '').includes(n));
  const photos = sec('房屋照片') ? sec('房屋照片').querySelectorAll('img').length : 0;
  const plan = sec('格局圖') ? sec('格局圖').querySelectorAll('img').length : 0;
  const uploading = document.querySelectorAll('.ant-upload-list-item-uploading,.ant-progress').length;
  const pm = document.querySelector('[contenteditable=true].ProseMirror');
  const descLen = pm ? pm.innerText.trim().length : 0;
  const pre = { 房屋照片: photos, 格局圖: plan, 上傳中: uploading, 文案字數: descLen };
  if (photos < MIN_PHOTOS || uploading || descLen < 30)
    return JSON.stringify({ 結果: '送出前檢查沒過，沒按', ...pre });

  const visible = () => [...document.querySelectorAll('.ant-modal-wrap')]
    .filter(w => getComputedStyle(w).display !== 'none' && w.innerText.trim());
  const btnIn = (root, text) => [...root.querySelectorAll('button')].find(b => b.innerText.replace(/\s/g, '') === text);
  const steps = [];
  if (pm) { pm.blur(); pm.dispatchEvent(new FocusEvent('focusout', { bubbles: true })); }   // 編輯器失焦才寫回表單
  const main = [...document.querySelectorAll('button')]
    .find(b => b.innerText.replace(/\s/g, '') === '確認修改' && !b.closest('.ant-modal-wrap'));
  if (!main) return JSON.stringify({ 結果: '找不到頁面上的「確認修改」', ...pre });
  main.click(); steps.push('確認修改');
  for (let round = 0; round < 6; round++) {
    await sleep(2500);
    const ws = visible();
    const tip = ws.find(w => w.innerText.includes('溫馨提示') && w.innerText.includes('無需更新'));
    if (tip) {
      const b = [...tip.querySelectorAll('button,a,span')].find(x => x.children.length === 0 && x.innerText.trim() === '無需更新');
      (b.closest('button') || b).click(); steps.push('溫馨提示→無需更新'); continue;
    }
    const chance = ws.find(w => w.innerText.includes('修改機會'));
    if (chance) {
      const t = chance.innerText.replace(/\s+/g, ' ');
      if (!t.includes('扣除1次')) return JSON.stringify({ 結果: '扣次說明跟預期不同，停下來沒按', 原文: t.slice(0, 300), steps, ...pre });
      btnIn(chance, '確認修改').click(); steps.push('扣 1 次改址：確認'); continue;
    }
    const ok = ws.find(w => w.innerText.includes('修改成功'));
    if (ok) {
      ok.querySelector('.ant-modal-close')?.click();   // 推銷「定時更新」，不買
      steps.push('修改成功，推銷視窗已關');
      return JSON.stringify({ 結果: '成功', steps, ...pre });
    }
    const err = [...document.querySelectorAll('.ant-form-item-explain-error,.ant-message-error')].map(e => e.innerText);
    if (err.length) return JSON.stringify({ 結果: '被表單擋下', 錯誤: err, steps, ...pre });
  }
  return JSON.stringify({ 結果: '等不到結果，截圖看', steps, 彈窗: visible().map(w => w.innerText.slice(0, 120)), ...pre });
})();
