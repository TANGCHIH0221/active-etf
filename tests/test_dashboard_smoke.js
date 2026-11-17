/* Unit-level DOM adapter, not a real-browser visual or layout test. No network.
   用法:node tests/test_dashboard_smoke.js [index.html] [data/stock_trends.json]
   趨勢資料是另檔載入(window.TREND_URL),這裡用 stub fetch 從磁碟讀。
   斷言不得依賴「目前累積了幾天歷史」——舊版斷言 60 日區間必為「歷史不足」,
   歷史滿 60 期後就自爆。需要不可用區間時一律自行注入。 */
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||'index.html','utf8');
const trendText=fs.readFileSync(process.argv[3]||'data/stock_trends.json','utf8');

class Element {
  constructor(env,id=''){this.env=env;this.id=id;this.value='';this.hidden=false;this.style={};this.dataset={};this.listeners={};this.classList={toggle(){}};this._html='';this.textContent='';}
  set innerHTML(s){this._html=s;for(const m of s.matchAll(/id="([^"]+)"/g))if(!this.env.elements.has(m[1]))this.env.elements.set(m[1],new Element(this.env,m[1]));}
  get innerHTML(){return this._html;}
  addEventListener(n,fn){this.listeners[n]=fn;}
  setAttribute(){}
  scrollIntoView(){}
  click(){if(this.onclick)this.onclick({target:this});}
}

function boot(fetchImpl){
  const env={elements:new Map(),groups:{},blobs:[],fetchCalls:[]};
  for(const m of html.matchAll(/id="([^"]+)"/g))env.elements.set(m[1],new Element(env,m[1]));
  env.groups['nav button']=Array.from({length:4},()=>new Element(env));
  env.groups['section']=Array.from({length:4},()=>new Element(env));
  env.groups['#typeChips .chip']=['ADD','INCREASE','DECREASE','REMOVE'].map(t=>{const e=new Element(env);e.dataset.t=t;return e;});
  const doc={getElementById:id=>env.elements.get(id)||null,querySelector:s=>s.startsWith('#')?env.elements.get(s.slice(1))||null:null,
    querySelectorAll:s=>env.groups[s]||[],createElement:()=>new Element(env)};
  const ctx={document:doc,console,Date,Set,Map,Blob,Promise,Error,
    URL:{createObjectURL:b=>{env.blobs.push(b);return 'blob:test';},revokeObjectURL(){}},setTimeout:fn=>fn(),
    fetch:url=>{env.fetchCalls.push(url);return String(url).includes('stock_trends.json')?fetchImpl(url):Promise.reject(new Error('offline unit test'));}};
  ctx.window=ctx;ctx.globalThis=ctx;vm.createContext(ctx);
  const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
  for(const s of scripts)vm.runInContext(s,ctx,{timeout:10000});
  env.ctx=ctx;env.$=id=>env.elements.get(id);
  return env;
}
const okFetch=()=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(trendText))});

(async()=>{
  // index.html 不可再內嵌趨勢資料
  assert(!/window\.TREND_DATA\s*=/.test(html),'trend data must not be embedded in index.html');
  assert(/window\.TREND_URL = "data\/stock_trends\.json\?v=[0-9a-f]+"/.test(html),'TREND_URL with cache-busting version');

  // ── 正常載入 ──
  const env=boot(okFetch),{ctx,$}=env;
  assert.equal(env.fetchCalls.filter(u=>String(u).includes('stock_trends.json')).length,1,'trend file fetched exactly once');
  assert($('trendEmpty').textContent.includes('載入中'),'placeholder before data arrives');
  await ctx.ETFTrends.ready;
  assert.equal(ctx.ETFTrends.settled,true);
  assert($('trendStockName').textContent.includes('2330'));
  assert($('trendDaily').innerHTML.includes('<svg'));
  for(const id of ['trendCumulative','trendHoldings']) {
    const dates=[...$(id).innerHTML.matchAll(/data-day="([^"]+)"/g)].map(m=>m[1]);
    assert(dates.every(d=>ctx.TREND_DATA.windows['20'].dates.includes(d)), 'Only selectable trading periods should be interactive');
  }
  assert($('trendRankTable').innerHTML.includes('data-stock='));
  // 歷史不足:自行注入不可用區間,不依賴實際累積天數
  ctx.TREND_DATA.windows['60']={available:false,available_sessions:3};
  $('trendWindow').onchange({target:{value:'60'}});
  assert.equal($('trendBody').hidden,true);
  assert($('trendEmpty').textContent.includes('歷史不足'));
  $('trendWindow').onchange({target:{value:'5'}});
  assert.equal($('trendBody').hidden,false);
  ctx.ETFTrends.openStock('2454');
  assert($('trendStockName').textContent.includes('2454'));
  assert.equal(env.groups.section[2].style.display,'');
  $('trendDirection').onchange({target:{value:'sell'}});
  assert($('trendRankTable').innerHTML.includes('data-stock='));
  $('trendExport').click();
  assert.equal(env.blobs.length,1);
  const csv=await env.blobs[0].text();
  assert(csv.includes('included_in_fixed_cohort'));assert(csv.includes('2454'));
  const emptyWindow=ctx.TREND_DATA.windows['5'];
  emptyWindow.cohort_etfs=[];
  for(const stock of Object.values(emptyWindow.stocks)) stock.net_delta=null;
  $('trendRankWindow').onchange({target:{value:'5'}});
  assert($('trendRankTable').innerHTML.includes('沒有完整可比樣本'));
  assert($('trendRankTable').innerHTML.includes('不代表沒有加減碼'));

  // ── 載入前就點「查看趨勢」:先排隊,載入後開該股 ──
  let release;
  const env2=boot(()=>new Promise(r=>{release=()=>r({ok:true,status:200,json:()=>Promise.resolve(JSON.parse(trendText))});}));
  env2.ctx.ETFTrends.openStock('2454');
  assert.equal(env2.ctx.ETFTrends.settled,false);
  release();await env2.ctx.ETFTrends.ready;
  assert(env2.$('trendStockName').textContent.includes('2454'),'queued openStock applied after load');

  // ── 載入失敗:顯示錯誤,不留在「載入中」 ──
  const env3=boot(()=>Promise.resolve({ok:false,status:404,json:()=>Promise.reject(new Error('no body'))}));
  const r3=await env3.ctx.ETFTrends.ready;
  assert.equal(r3,null);assert.equal(env3.ctx.ETFTrends.settled,true);
  assert(env3.$('trendEmpty').textContent.includes('載入失敗'));
  assert(env3.$('trendEmpty').textContent.includes('404'));

  console.log('Dashboard smoke checks passed: lazy trend load, controls, export, queued open, load failure (unit DOM; no visual assertions).');
})().catch(e=>{console.error(e);process.exit(1);});
