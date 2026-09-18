// 本機模擬 n8n 這支 workflow：直接抓線上的 jsCode / jsonBody 來跑，看今天會推出什麼
import fs from 'node:fs';

const env = Object.fromEntries(
  fs.readFileSync('C:/Users/user/asce/.env', 'utf8').split(/\r?\n/)
    .filter(l => l && !l.startsWith('#') && l.includes('='))
    .map(l => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()])
);
const kenv = Object.fromEntries(
  fs.readFileSync('C:/Users/user/asce/scripts/keis/.env', 'utf8').split(/\r?\n/)
    .filter(l => l && !l.startsWith('#') && l.includes('='))
    .map(l => [l.slice(0, l.indexOf('=')).trim(), l.slice(l.indexOf('=') + 1).trim()])
);

const wf = await (await fetch(env.N8N_URL.replace(/\/$/, '') + '/api/v1/workflows/pXa1ULXsWcnbILTP',
  { headers: { 'X-N8N-API-KEY': env.N8N_API_KEY } })).json();
const node = n => wf.nodes.find(x => x.name === n);

const notion = async (bodyStr) => {
  const r = await fetch('https://api.notion.com/v1/databases/4f28b91531594c618725afc3ecc36e2f/query', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + kenv.KEIS_NOTION_TOKEN, 'Notion-Version': '2022-06-28', 'Content-Type': 'application/json' },
    body: bodyStr,
  });
  if (!r.ok) throw new Error('notion ' + r.status + ' ' + (await r.text()).slice(0, 300));
  return r.json();
};

// n8n 的 "={{ expr }}" → 直接 eval expr，$json 由外面帶進來
const evalExpr = (raw, $json) => {
  const expr = raw.replace(/^=\{\{/, '').replace(/\}\}$/, '');
  return Function('$json', 'return (' + expr + ')')($json);
};

const runCode = (jsCode, inputJson, refs) => {
  const $input = { first: () => ({ json: inputJson }) };
  const $ = name => ({ first: () => ({ json: refs[name] }) });
  return Function('$input', '$', jsCode)($input, $);
};

// 1) 查 Notion 未聯絡名單
const q1 = evalExpr(node('查 Notion 未聯絡名單').parameters.jsonBody, {});
const res1 = await notion(q1);
console.log('查詢回傳:', res1.results.length, '筆, has_more =', res1.has_more);
const stale = res1.results.filter(p => (p.properties['聯絡狀態']?.select?.name) !== '未聯絡');
console.log('其中狀態不是「未聯絡」的舊索引資料:', stale.length,
  stale.map(p => p.properties['電話']?.phone_number + '=' + p.properties['聯絡狀態']?.select?.name).join(', '));

// 2) 挑出快到期未聯絡
const picked = runCode(node('挑出快到期未聯絡').parameters.jsCode, { results: res1.results }, {});
if (!picked.length) { console.log('→ 今天沒有符合的，不推播'); process.exit(0); }
const pickJson = picked[0].json;
console.log('挑中:', pickJson.rows.length, '筆；不重複電話', pickJson.phones.length, '支');

// 3) 查同電話前筆
const q2 = evalExpr(node('查同電話前筆').parameters.jsonBody, pickJson);
const res2 = await notion(q2);
console.log('同電話查詢回傳:', res2.results.length, '筆, has_more =', res2.has_more);

// 4) 組訊息
const out = runCode(node('組訊息（標重複）').parameters.jsCode, { results: res2.results },
  { '挑出快到期未聯絡': pickJson });
console.log('\n===== Telegram 會收到的內容 =====\n');
console.log(out[0].json.text);
