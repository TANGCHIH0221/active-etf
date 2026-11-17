/* Stock trends UI. Pure data functions are shared with Node regression tests.
   趨勢資料不內嵌在 index.html(曾讓頁面長到 12 MB 且每天變大),改由
   window.TREND_URL(data/stock_trends.json?v=<trend_build_id>)載入。
   window.TREND_DATA 若已存在則直接使用(測試與相容用)。 */
(function (root) {
  'use strict';
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const selectWindow = (data, key) => (data.windows || {})[key] || {available:false};
  function searchStocks(data, query) {
    const q = query.trim().toLowerCase();
    const rows = Object.entries(data.stocks || {});
    return rows.filter(([c,s]) => c.toLowerCase().includes(q) || (s.name || '').toLowerCase().includes(q))
      .sort((a,b) => Number(b[0] === query) - Number(a[0] === query) || a[0].localeCompare(b[0]));
  }
  function rankStocks(data, key, dir, order='net') {
    const w = selectWindow(data,key);
    if (!w.available) return [];
    return Object.entries(w.stocks).filter(([,s]) => s.net_delta != null &&
      (dir === 'sell' ? s.net_delta < -0.000001 : s.net_delta > 0.000001))
      .map(([code,s]) => ({code,...s}))
      .sort((a,b) => {
        const metric = dir === 'sell' ? 'decreasing_etfs' : 'increasing_etfs';
        const breadth = order === 'breadth' ? b[metric].length-a[metric].length : 0;
        return breadth || Math.abs(b.net_delta)-Math.abs(a.net_delta) || a.code.localeCompare(b.code);
      });
  }
  const csvCell = value => {
    let s = String(value == null ? '' : value);
    if (typeof value === 'string' && /^[=+\-@\t\r]/.test(s)) s = "'" + s;
    return '"'+s.replace(/"/g,'""')+'"';
  };
  const formatLots = n => n == null ? '—' : (n < -0.000001 ? '−' : n > 0.000001 ? '+' : '') +
    (Math.abs(n) / 1000).toLocaleString('zh-TW',{maximumFractionDigits:2});
  const filterIntervals = (rows, code, w) => rows.filter(r => r.stock === code && r.to_date > w.from_date && r.to_date <= w.to_date);
  function unpack(data) {
    if (data.intervals) return data.intervals;
    const t = data.interval_table;
    if (!t) return [];
    const sf = new Set(['etf','stock','from_date','to_date','observed_date','quality']);
    return t.rows.map(row => Object.fromEntries(t.fields.map((key,i) => [key,
      sf.has(key) ? t.strings[row[i]] : key === 'source_snapshot_refs' ? row[i].map(x=>t.strings[x]) : row[i]])));
  }
  const api = {selectWindow,searchStocks,rankStocks,csvCell,formatLots,filterIntervals,unpack};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.ETFTrends = api;
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  if (!$('trendPanel')) return;
  // 資料載入前就被呼叫(反查頁「查看累積加減碼趨勢」)→ 先切頁並記下,載入後再開
  let pending = null;
  api.settled = false;
  api.openStock = function(value){pending=value;if(typeof root.tab==='function')root.tab(2);$('trendPanel').scrollIntoView({behavior:'auto',block:'start'});};
  function placeholder(msg){
    $('trendBody').hidden=true;$('trendEmpty').hidden=false;$('trendEmpty').textContent=msg;
    $('trendRankTable').innerHTML='<div class="empty">'+esc(msg)+'</div>';
  }
  if (root.TREND_DATA) {
    api.settled = true; init(root.TREND_DATA); api.ready = Promise.resolve(root.TREND_DATA);
  } else if (root.TREND_URL && typeof fetch === 'function') {
    placeholder('趨勢資料載入中…');
    api.ready = fetch(root.TREND_URL)
      .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(d => { root.TREND_DATA = d; api.settled = true; init(d); return d; })
      .catch(err => { api.settled = true; placeholder('趨勢資料載入失敗（' + err.message + '），請重新整理頁面。'); return null; });
  } else {
    api.settled = true; init({stocks:{},windows:{}}); api.ready = Promise.resolve(null);
  }

  function init(data) {
  let key = '20', code = data.stocks['2330'] ? '2330' : Object.keys(data.stocks)[0], day = '', direction = 'buy', rankOrder = 'net';
  let decoded;
  const intervals = () => decoded || (decoded=unpack(data));
  const signClass = v => v == null || v === 0 ? '' : v > 0 ? 'up' : 'down';
  const count = v => v == null ? '—' : v.toLocaleString('zh-TW');
  const qualityLabel = q => ({ok:'可比',gap:'跨日缺口',insufficient_scale:'校正樣本不足',
    possible_corporate_action:'疑似公司行動',calendar_unverified:'日曆未確認'}[q] || q);

  function chart(series, field, label, color, bars=false) {
    const width=900,height=205,left=65,right=18,top=20,bottom=32;
    const values=series.map(r=>r[field]).filter(v=>v!=null);
    if (!values.length) return '<div class="empty">沒有完整可比樣本，無法繪製此圖。</div>';
    let lo=Math.min(0,...values),hi=Math.max(0,...values);
    if(hi===lo){hi=1;lo=-1;}
    const x=i=>left+(width-left-right)*(i+.5)/series.length;
    const y=v=>top+(hi-v)/(hi-lo)*(height-top-bottom);
    let marks='',path='';
    for(let i=0;i<series.length;i++){
      const r=series[i],v=r[field];
      if(v==null){path='';continue;}
      const px=x(i),py=y(v);
      if(bars){
        const bw=Math.min(32,(width-left-right)/series.length*.65);
        marks+='<rect x="'+(px-bw/2)+'" y="'+Math.min(py,y(0))+'" width="'+bw+'" height="'+Math.max(1,Math.abs(py-y(0)))+'" fill="'+(v>=0?'var(--up)':'var(--down)')+'"/>';
      } else {
        if(path) marks+='<line x1="'+path[0]+'" y1="'+path[1]+'" x2="'+px+'" y2="'+py+'" stroke="'+color+'" stroke-width="2.5"/>';
        path=[px,py];
      }
      marks+='<circle cx="'+px+'" cy="'+py+'" r="'+(r.date===day?5:3)+'" fill="'+color+'"/>';
      if(!r.baseline) marks+='<rect class="trend-point" tabindex="0" role="button" aria-label="'+esc(r.date+' '+label+' '+(v/1000).toFixed(2)+' 張')+'" data-day="'+r.date+'" x="'+(px-(width-left-right)/series.length/2)+'" y="0" width="'+((width-left-right)/series.length)+'" height="'+(height-bottom)+'" fill="transparent"><title>'+esc(r.date+'：'+(v/1000).toLocaleString('zh-TW')+' 張')+'</title></rect>';
    }
    const ticks=[lo,0,hi].filter((v,i,a)=>a.indexOf(v)===i).map(v=>'<line x1="'+left+'" x2="'+(width-right)+'" y1="'+y(v)+'" y2="'+y(v)+'" class="trend-grid"/><text x="'+(left-8)+'" y="'+(y(v)+4)+'" text-anchor="end">'+(v/1000).toLocaleString('zh-TW',{maximumFractionDigits:1})+'</text>').join('');
    const labels=[0,Math.floor((series.length-1)/2),series.length-1].filter((v,i,a)=>a.indexOf(v)===i)
      .map(i=>'<text x="'+x(i)+'" y="'+(height-8)+'" text-anchor="middle">'+series[i].date.slice(5)+'</text>').join('');
    return '<svg class="trend-chart" viewBox="0 0 '+width+' '+height+'" role="group" aria-label="'+esc(label)+'，單位張。點選或以 Tab、Enter 查看日期明細"><text x="8" y="14">張</text>'+ticks+marks+labels+'</svg>';
  }
  function metrics(s,w) {
    const list=[['累積淨調整估算',formatLots(s.net_delta),'張',signClass(s.net_delta)],
      ['增持／減持總量',formatLots(s.positive_delta)+' / '+formatLots(s.negative_delta),'張',''],
      ['淨增持／淨減持 ETF',(s.net_delta==null?'—':s.increasing_etfs.length+' / '+s.decreasing_etfs.length),'家',''],
      ['固定可比樣本',s.cohort_etfs.length+' / '+w.expected_etf_count,'家','']];
    return '<div class="trend-metrics">'+list.map(([label,value,unit,cls])=>'<div><span>'+label+'</span><strong class="'+cls+'">'+value+'</strong><small>'+unit+'</small></div>').join('')+'</div>';
  }
  function breakdown(w,s) {
    if(!s.series.some(r=>r.date===day)) day=w.to_date;
    $('trendDay').innerHTML=w.dates.map(d=>'<option value="'+d+'"'+(d===day?' selected':'')+'>'+d+'</option>').join('');
    const rows=filterIntervals(intervals(),code,w).filter(r=>r.to_date===day);
    $('trendBreakdown').innerHTML='<div class="scroll"><table><thead><tr><th>ETF</th><th>持股比較區間</th><th class="num">原始變化（張）</th><th class="num">校正估算（張）</th><th>狀態</th></tr></thead><tbody>'+
      rows.map(r=>'<tr><td class="mono">'+esc(r.etf)+'</td><td>'+r.from_date+' → '+r.to_date+'</td><td class="num">'+formatLots(r.raw_delta)+'</td><td class="num '+signClass(r.adjusted_delta)+'">'+formatLots(r.adjusted_delta)+'</td><td>'+esc(qualityLabel(r.quality))+(s.cohort_etfs.includes(r.etf)?'':' · 未納入固定樣本')+'</td></tr>').join('')+
      (!rows.length?'<tr><td colspan="5">這一天沒有該股的可用區間紀錄；不能解讀為零買賣。</td></tr>':'')+'</tbody></table></div>';
  }
  function drawStock() {
    const w=selectWindow(data,key);
    $('trendWindow').value=key;
    $('trendStock').value=code||'';
    $('trendStockName').textContent=code ? code+' '+(data.stocks[code]||{}).name : '無歷史資料';
    if(!w.available || !code){
      $('trendBody').hidden=true;$('trendEmpty').hidden=false;
      $('trendEmpty').textContent='歷史不足：需要 '+key+' 個完整'+((data.calendar||{}).label||'交易日')+'的變化，目前最多 '+(w.available_sessions||0)+' 期。請選較短區間。';
      return;
    }
    $('trendEmpty').hidden=true;$('trendBody').hidden=false;
    const s=w.stocks[code];if(!s)return;
    if(!w.dates.includes(day)) day=w.to_date;
    $('trendPeriod').textContent=w.from_date+' → '+w.to_date+'，'+w.dates.length+' 個'+data.calendar.label+'；每日按同一樣本累計。';
    $('trendMetrics').innerHTML=metrics(s,w);
    $('trendCoverage').textContent='固定可比 '+s.cohort_etfs.length+'／'+w.expected_etf_count+' 檔：'+(s.cohort_etfs.join('、')||'無')+'。'+
      (w.excluded_etfs.length?'日期缺漏或資料品質排除：'+w.excluded_etfs.map(e=>e.etf).join('、')+'。':'')+
      (s.excluded_etfs.length?'此股另因疑似公司行動等因素排除：'+s.excluded_etfs.join('、')+'。':'')+
      '此結果代表可比樣本，不是全部主動式 ETF 的完整買賣量。';
    $('trendDaily').innerHTML=chart(s.series,'net_delta','每日淨調整估算','var(--blue-lt)',true);
    const baseline={baseline:true,date:w.from_date,cumulative:0,total_shares:s.contributions.reduce((n,r)=>n+r.previous_shares,0)};
    $('trendCumulative').innerHTML=chart(s.cohort_etfs.length?[baseline,...s.series]:s.series,'cumulative','累積淨調整估算','var(--amber)');
    $('trendHoldings').innerHTML=chart(s.cohort_etfs.length?[baseline,...s.series]:s.series,'total_shares','可比樣本持股總量','var(--blue-lt)');
    $('trendContributions').innerHTML='<div class="scroll"><table><thead><tr><th>ETF</th><th class="num">期初（張）</th><th class="num">期末（張）</th><th class="num">原始差額（張）</th><th class="num">淨調整估算（張）</th></tr></thead><tbody>'+
      s.contributions.slice().sort((a,b)=>Math.abs(b.adjusted_delta)-Math.abs(a.adjusted_delta)).map(r=>'<tr><td class="mono">'+esc(r.etf)+'</td><td class="num">'+count(r.previous_shares/1000)+'</td><td class="num">'+count(r.current_shares/1000)+'</td><td class="num">'+formatLots(r.raw_delta)+'</td><td class="num '+signClass(r.adjusted_delta)+'">'+formatLots(r.adjusted_delta)+'</td></tr>').join('')+'</tbody></table></div>';
    $('trendDailyData').innerHTML='<div class="scroll"><table><thead><tr><th>日期</th><th class="num">淨調整（張）</th><th class="num">累積（張）</th><th class="num">持股總量（張）</th><th class="num">持有 ETF</th><th class="num">增／減持家數</th></tr></thead><tbody>'+s.series.map(r=>'<tr><td>'+r.date+'</td><td class="num">'+formatLots(r.net_delta)+'</td><td class="num">'+formatLots(r.cumulative)+'</td><td class="num">'+(r.total_shares==null?'—':count(r.total_shares/1000))+'</td><td class="num">'+count(r.held_count)+'</td><td class="num">'+(r.net_delta==null?'—':r.increasing_count+' / '+r.decreasing_count)+'</td></tr>').join('')+'</tbody></table></div>';
    breakdown(w,s);
  }
  function drawRanking() {
    const w=selectWindow(data,key);$('trendRankWindow').value=key;
    const rows=rankStocks(data,key,direction,rankOrder);
    $('trendRankNote').textContent=w.available?'期間 '+w.from_date+' → '+w.to_date+'；固定日期完整樣本 '+w.cohort_etfs.length+'／'+w.expected_etf_count+' 檔。張數排序不等於資金規模排序。':'此區間歷史不足，請選擇 5／20 日或全部歷史。';
    $('trendRankTable').innerHTML=rows.length?'<div class="scroll rt"><table><thead><tr><th>個股</th><th class="num">5 日淨調整（張）</th><th class="num">20 日淨調整（張）</th><th class="num">所選區間（張）</th><th class="num">增／減 ETF</th><th class="num">正向／有效日</th><th class="num">可比樣本</th></tr></thead><tbody>'+rows.slice(0,60).map(r=>{
      const v=k=>{const x=selectWindow(data,k);return x.available&&x.stocks[r.code]?x.stocks[r.code].net_delta:null;};
      return '<tr><td data-l="個股"><button class="trend-link" data-stock="'+esc(r.code)+'">'+esc(r.code)+' '+esc(data.stocks[r.code].name)+'</button></td><td data-l="5 日淨調整" class="num">'+formatLots(v('5'))+'</td><td data-l="20 日淨調整" class="num">'+formatLots(v('20'))+'</td><td data-l="所選區間" class="num '+signClass(r.net_delta)+'">'+formatLots(r.net_delta)+'</td><td data-l="增／減 ETF" class="num">'+r.increasing_etfs.length+' / '+r.decreasing_etfs.length+'</td><td data-l="正向／有效日" class="num">'+r.positive_days+' / '+w.dates.length+'</td><td data-l="可比樣本" class="num">'+r.cohort_etfs.length+' / '+w.expected_etf_count+'</td></tr>';
    }).join('')+'</tbody></table></div>':'<div class="empty">'+(!w.available?'此區間歷史不足，請選擇較短期間。':!w.cohort_etfs.length?'此區間沒有完整可比樣本；資料日期缺漏或品質檢查未通過，不代表沒有加減碼。':'此區間沒有符合方向且可比較的個股。')+'</div>';
  }
  function changeWindow(value){key=value;day='';drawStock();drawRanking();}
  api.openStock=function(value){if(!data.stocks[value])return;code=value;drawStock();if(typeof root.tab==='function')root.tab(2);$('trendPanel').scrollIntoView({behavior:'auto',block:'start'});};
  $('trendWindow').onchange=e=>changeWindow(e.target.value);
  $('trendRankWindow').onchange=e=>changeWindow(e.target.value);
  $('trendSort').onchange=e=>{rankOrder=e.target.value;drawRanking();};
  $('trendDirection').onchange=e=>{direction=e.target.value;drawRanking();};
  $('trendDay').onchange=e=>{day=e.target.value;drawStock();};
  $('trendStock').oninput=e=>{
    const hits=searchStocks(data,e.target.value).slice(0,12);
    $('trendCandidates').innerHTML=hits.map(([c,s])=>'<button class="trend-link" data-stock="'+esc(c)+'">'+esc(c)+' '+esc(s.name)+'</button>').join(' ');
    const exact=data.stocks[e.target.value.trim()];if(exact){code=e.target.value.trim();drawStock();}
  };
  $('trendPanel').addEventListener('click',e=>{
    const point=e.target.closest('[data-day]');if(point){day=point.dataset.day;drawStock();}
    const stock=e.target.closest('[data-stock]');if(stock){code=stock.dataset.stock;$('trendCandidates').innerHTML='';drawStock();}
  });
  $('trendPanel').addEventListener('keydown',e=>{if((e.key==='Enter'||e.key===' ')&&e.target.matches('[data-day]')){e.preventDefault();day=e.target.dataset.day;drawStock();}});
  $('trendRankTable').addEventListener('click',e=>{const b=e.target.closest('[data-stock]');if(b)api.openStock(b.dataset.stock);});
  $('trendExport').onclick=()=>{
    const w=selectWindow(data,key);if(!w.available)return;
    const s=w.stocks[code];
    const fields=['etf','stock','from_date','to_date','observed_date','previous_shares','current_shares','raw_delta','adjusted_delta','scale','common_holdings_count','quality','source_snapshot_refs','source_revision'];
    const header=fields.concat(['included_in_fixed_cohort','method']);
    const lines=[header.map(csvCell).join(',')];
    for(const r of filterIntervals(intervals(),code,w))lines.push(fields.map(f=>csvCell(Array.isArray(r[f])?r[f].join(' | '):r[f])).concat([csvCell(s.cohort_etfs.includes(r.etf)),csvCell(data.method)]).join(','));
    const blob=new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'});
    const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=code+'-'+w.from_date+'-'+w.to_date+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  if (pending && data.stocks[pending]) code = pending;
  drawStock();drawRanking();
  }
})(typeof globalThis!=='undefined'?globalThis:this);
