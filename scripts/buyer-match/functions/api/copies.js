/* 買方配案頁的複製次數（電腦、手機共用同一份）
 * GET  /api/copies              → { "<key>": 次數, ... }
 * POST /api/copies {keys:[...]} → 每個 key +1，回傳全部最新次數
 * key = build_page.js 用「客戶＋物件指紋」算的 12 碼雜湊，D1 裡沒有客戶名
 */
const KEY = /^[0-9a-f]{12}$/;

async function all(db) {
  const { results } = await db.prepare('SELECT k, n FROM copies').all();
  const out = {};
  for (const r of results) out[r.k] = r.n;
  return out;
}
const json = (o, status = 200) => new Response(JSON.stringify(o), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });

export async function onRequestGet({ env }) {
  return json(await all(env.DB));
}

export async function onRequestPost({ env, request }) {
  let body;
  try { body = await request.json(); } catch (e) { return json({ error: 'bad json' }, 400); }
  const keys = [...new Set((body && body.keys) || [])].filter((k) => KEY.test(k));
  if (!keys.length || keys.length > 300) return json({ error: 'bad keys' }, 400);
  const now = new Date().toISOString();
  const st = env.DB.prepare('INSERT INTO copies (k, n, last) VALUES (?1, 1, ?2) ON CONFLICT(k) DO UPDATE SET n = n + 1, last = ?2');
  await env.DB.batch(keys.map((k) => st.bind(k, now)));
  return json(await all(env.DB));
}
