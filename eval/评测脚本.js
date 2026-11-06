/*
 * 评测脚本：在真实页面里跑检索侧与生成侧，结果写进 评测结果.json。
 * 用法：node eval/评测脚本.js <临时目录> <页面副本路径> eval/评测结果.json
 * 依赖：本机 Chrome、Node 18+（用到全局 WebSocket）、8890 代理在跑。
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const { pathToFileURL } = require('url');

const TMP = process.argv[2];
const PAGE = process.argv[3];
const OUT = process.argv[4];
const SET = path.join(__dirname, '评测集.jsonl');
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9335;
const URL = pathToFileURL(PAGE).href;
const sleep = ms => new Promise(r => setTimeout(r, ms));

const items = fs.readFileSync(SET, 'utf8').trim().split('\n').map(l => JSON.parse(l));
const byId = Object.fromEntries(items.map(x => [x.id, x]));
const GEN_IDS = ['Q01','Q05','Q08','Q12','Q13','Q14','Q15','Q16','Q17','Q18','M01a','M01b','M02a','M02b'];

const chrome = spawn(CHROME, [
  '--headless=new', '--no-first-run', '--no-default-browser-check',
  '--remote-debugging-port=' + PORT, '--user-data-dir=' + path.join(TMP, 'profile'),
  '--allow-file-access-from-files', '--window-size=1440,900', '--disable-gpu', URL
], { stdio: 'ignore' });
const watchdog = setTimeout(() => { console.error('总超时'); try { chrome.kill(); } catch (e) {} process.exit(2); }, 900000);

let ws, seq = 0; const pending = new Map();
function send(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++seq; pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
}
async function ev(expr, awaitPromise = true) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise, returnByValue: true, timeout: 180000 });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' ' + ((r.exceptionDetails.exception || {}).description || ''));
  return r.result && r.result.value;
}

function askExpr(q, doReset) {
  return `(async()=>{
    ${doReset ? 'resetThread();' : ''}
    setView('client');
    const inp=document.getElementById('q');
    inp.value=${JSON.stringify(q)};
    const t0=Date.now(); let err='';
    try{ await run(); }catch(e){ err=String((e&&e.message)||e); }
    const bots=[...document.querySelectorAll('.msg.bot .say')];
    const hits=[...document.querySelectorAll('#hits .hit')].map(h=>({
      src:(h.querySelector('.src')||{}).textContent||'',
      sim:(h.querySelector('.sc')||{}).textContent||'',
      txt:(h.querySelector('.txt')||{}).textContent||''
    }));
    return {
      sec:+((Date.now()-t0)/1000).toFixed(2), err,
      reply:bots.length?bots[bots.length-1].innerText.trim():'',
      typing:document.querySelectorAll('.msg .typing').length,
      btn:document.getElementById('btn').disabled,
      rw:(document.getElementById('rw')||{}).innerText||'',
      genSec:(document.getElementById('ans-src')||{}).textContent||'',
      hits:hits,
      hist:historyText()
    };
  })()`;
}

(async () => {
  let target = null;
  for (let i = 0; i < 80; i++) {
    try {
      const list = await fetch('http://127.0.0.1:' + PORT + '/json/list').then(r => r.json());
      target = list.find(t => t.type === 'page' && t.url.indexOf(path.basename(PAGE)) >= 0);
      if (target) break;
    } catch (e) {}
    await sleep(400);
  }
  if (!target) throw new Error('找不到页面调试目标');
  ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) {
      const p = pending.get(m.id); pending.delete(m.id);
      m.error ? p.reject(new Error(JSON.stringify(m.error))) : p.resolve(m.result);
    }
  };
  await send('Runtime.enable');

  let ok = false;
  for (let i = 0; i < 160; i++) {
    const v = await ev("(()=>{try{return document.readyState==='complete' && typeof rank==='function' && typeof run==='function' && VEC.ready===true}catch(e){return false}})()", false);
    if (v === true) { ok = true; break; }
    await sleep(500);
  }
  if (!ok) throw new Error('页面或向量索引未就绪');
  const meta = await ev(`(()=>({
    time:new Date().toISOString(), docs:DOCS.length, chunks:chunks.length,
    vecModel:VEC.model, vecDim:VEC.dim, chatModel:API.model, chatBase:API.base,
    embModel:EMB.model, rw:RW.on, chunkSize:CHUNK_SIZE, overlap:OVERLAP
  }))()`);
  console.log('环境', JSON.stringify(meta));

  // 检索侧：原句检索，逐题取前 5 块
  const retrieval = await ev(`(async()=>{
    const qs=${JSON.stringify(items.map(x => ({id:x.id, q:x.question})))};
    const out=[];
    for(const it of qs){
      const r=await rank(it.q);
      out.push({id:it.id, q:it.q, top:r.slice(0,5).map(x=>({
        doc:x.chunk.doc.title, section:x.chunk.section||'', idx:x.chunk.idx+1,
        sim:+((x.sim||0)*100).toFixed(1), byVec:!!x.byVec
      }))});
    }
    return out;
  })()`);
  console.log('检索侧完成', retrieval.length, '题');

  // 生成侧：端到端，多轮组不重置会话
  const generation = [];
  for (const id of GEN_IDS) {
    const it = byId[id];
    const doReset = !(it.group && it.order === 2);
    const r = await ev(askExpr(it.question, doReset));
    generation.push(Object.assign({ id, q: it.question, group: it.group, order: it.order }, r));
    console.log('生成侧', id, r.sec + 's', (r.reply || '').slice(0, 40).replace(/\n/g, ' '));
  }

  fs.writeFileSync(OUT, JSON.stringify({ meta, items, retrieval, generation }, null, 2), 'utf8');
  console.log('已写出', OUT);
})().catch(e => {
  console.error('失败', String(e && e.stack || e));
  process.exitCode = 1;
}).finally(() => {
  clearTimeout(watchdog);
  try { ws && ws.close(); } catch (e) {}
  try { chrome.kill(); } catch (e) {}
  setTimeout(() => process.exit(process.exitCode || 0), 500);
});
