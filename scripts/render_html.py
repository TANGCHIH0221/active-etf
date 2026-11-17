# -*- coding: utf-8 -*-
"""產生 index.html(自包含:資料內嵌、無外部依賴)。

深色版面,站內慣例綠漲紅跌(綠=加碼/新增,紅=減碼/剔除)。
配色不是憑感覺挑的,每個顏色都跑過 dataviz 的六項檢查(OKLab ΔE、Machado CVD
模擬、WCAG 對比,基準面板色 #111827);詳細理由寫在 CSS 內的註解。三個重點色
(藍/琥珀/洋紅)負責結構、活動、訊號三種角色,漲跌綠紅只用於狀態,兩組不混用。
"""
import json
from pathlib import Path

ASSETS = Path(__file__).resolve().parent

# 篩選 chip 的字符,與 JS 端 TYPE 表一致(綠↔紅對紅綠色盲不可靠,方向一律配字符)
GLYPH = {"ADD": "✚", "INCREASE": "▲", "DECREASE": "▼", "REMOVE": "✕"}

# 異動明細預設篩選(需與 JS 的 filterType 初值一致)
DEFAULT_FILTER = "INCREASE"

# Abacus 的命名空間,沿用 credit-card-guide 的做法(免註冊、純前端)
COUNTER_NS = "nctuwanglin-active-etf"

CSS = """
*,*::before,*::after{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:'Inter','Noto Sans TC',sans-serif;font-feature-settings:"tnum" 1}
/* 配色以 dataviz 六項檢查實算過(OKLab ΔE、Machado CVD 模擬、WCAG 對比),
   面板色 #111827 為基準,不是憑眼睛挑的:
   - 三個重點色 blue/amber/magenta 全對(all-pairs CVD ΔE 13.2、常色視覺 19.3)
   - 藍色 sequential ramp 只用對比 >=3:1 的 100-500 階(550 以下在深色面板看不見)
   - 綠↔紅 deutan ΔE 僅 6.5(紅綠色盲的典型弱點),故四種異動 pill 一律配
     ▲▼✚✕ 字符 + 文字,色相絕不單獨承載方向 */
:root{--bg:#080b12;--panel:#111827;--panel-2:#1a2233;--line:#243044;
  --ink:#e8ebf0;--ink-dim:#9aa8bd;--ink-mute:#6b7a91;
  /* 狀態色:綠漲紅跌(站內慣例) */
  --up:#34d399;--up-deep:#059669;--down:#f87171;--down-deep:#dc2626;
  /* 三個重點色 */
  --blue:#3987e5;--blue-lt:#7cb2f0;--amber:#fab219;--magenta:#e879a8;
  /* 權重 bar 的 sequential 藍階(低→高) */
  --seq-lo:#256abf;--seq-hi:#9ec5f4}
a{color:inherit}
.mono{font-family:'JetBrains Mono','SF Mono',ui-monospace,monospace}
.wrap{max-width:78rem;margin:0 auto;padding:0 1rem}
header{border-bottom:1px solid var(--line);padding:1.25rem 0 1rem;
  background:linear-gradient(180deg,rgba(59,130,246,.06),transparent)}
h1{margin:0;font-size:1.3rem;letter-spacing:.02em}
.sub{color:var(--ink-dim);font-size:.8rem;margin-top:.35rem}
/* 固定 4 欄:auto-fit 在中等寬度會排成 3+1 落單 */
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:.6rem;margin:1rem 0}
@media(max-width:640px){.kpis{grid-template-columns:repeat(2,1fr)}}
/* 每塊各自的重點色只上在頂條與數字;標籤文字一律用 ink token 不染色。
   四塊的識別靠文字標籤,顏色是強調不是識別通道——所以不受類別色 CVD 門檻約束,
   但仍只用實算通過的三個重點色(藍/琥珀/洋紅),避免與漲跌綠紅混淆。 */
.kpi{position:relative;background:var(--panel);border:1px solid var(--line);
  border-radius:8px;padding:.8rem .9rem .75rem;overflow:hidden}
.kpi::before{content:'';position:absolute;inset:0 0 auto 0;height:3px;
  background:var(--accent,var(--blue))}
.kpi .n{font-size:1.5rem;font-weight:700;color:var(--accent,var(--ink));
  line-height:1.15;letter-spacing:-.01em}
.kpi .l{color:var(--ink-dim);font-size:.71rem;letter-spacing:.06em;margin-top:.1rem}
.k-etf{--accent:var(--blue)}
.k-stock{--accent:var(--blue-lt)}
.k-move{--accent:var(--amber)}
.k-cons{--accent:var(--magenta)}
/* 今日無異動時不該用亮色喊「0」——沒事發生就該安靜下來 */
.kpi.zero .n{color:var(--ink-mute)}
.kpi.zero::before{background:var(--line)}
nav{display:flex;gap:.4rem;margin:1rem 0;border-bottom:1px solid var(--line);flex-wrap:wrap}
nav button{background:none;border:none;color:var(--ink-dim);padding:.6rem .9rem;
  font:inherit;font-size:.9rem;cursor:pointer;border-bottom:2px solid transparent}
nav button.on{color:var(--ink);border-bottom-color:var(--blue);font-weight:600}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  padding:1rem;margin-bottom:1rem}
.panel h2{margin:0 0 .75rem;font-size:.95rem;letter-spacing:.02em}
.panel h2 .hint{color:var(--ink-mute);font-size:.72rem;font-weight:400;margin-left:.5rem}
table{width:100%;border-collapse:collapse;font-size:.83rem}
th{text-align:left;color:var(--ink-mute);font-weight:600;font-size:.72rem;
  letter-spacing:.05em;padding:.4rem .5rem;border-bottom:1px solid var(--line);
  white-space:nowrap}
td{padding:.42rem .5rem;border-bottom:1px solid rgba(31,41,55,.5);white-space:nowrap}
tr:hover td{background:rgba(148,163,184,.04)}
.num{text-align:right}
.up{color:var(--up)}.down{color:var(--down)}
.pill{display:inline-flex;align-items:center;gap:3px;padding:1.5px 7px;font-size:.69rem;
  font-weight:600;border-radius:4px;letter-spacing:.03em;white-space:nowrap}
.pill .g{font-size:.62rem;line-height:1}
/* 方向用色相(綠漲紅跌)、強度用實心/淡底:進出場實心,加減碼淡底。
   色相對紅綠色盲不可靠,所以 ▲▼✚✕ 字符是必要的第二通道,不是裝飾。 */
.p-add{background:var(--up-deep);color:#eafff6;border:1px solid var(--up)}
.p-inc{background:rgba(52,211,153,.13);color:var(--up);border:1px solid rgba(52,211,153,.4)}
.p-rem{background:var(--down-deep);color:#fff1f1;border:1px solid var(--down)}
.p-dec{background:rgba(248,113,113,.13);color:var(--down);border:1px solid rgba(248,113,113,.4)}
.p-dispo{background:rgba(250,178,25,.15);color:var(--amber);border:1px solid rgba(250,178,25,.45)}
.p-stale{background:rgba(250,178,25,.12);color:var(--amber);border:1px solid rgba(250,178,25,.3)}
.p-note{background:rgba(57,135,229,.14);color:var(--blue-lt);border:1px solid rgba(57,135,229,.4)}
.p-gray{background:rgba(154,168,189,.1);color:var(--ink-dim);border:1px solid rgba(154,168,189,.22)}
.controls{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin-bottom:.85rem}
input,select{background:var(--panel-2);border:1px solid var(--line);color:var(--ink);
  border-radius:5px;padding:.4rem .7rem;font:inherit;font-size:.83rem}
/* 中文 placeholder 用 size 屬性算出來的寬度會不夠(size 以英數字寬為準),
   一律改用 min-width,否則「搜尋個股代號/名稱」會貼齊邊框甚至被裁掉。 */
#evQ{min-width:13rem}
#lookupQ{min-width:22rem}
@media(max-width:640px){#evQ,#lookupQ{min-width:100%}}
input:focus,select:focus{outline:none;border-color:var(--blue)}
/* 篩選 chip 是「單選」:點另一個就換過去,再點同一個取消回到全部。
   選取態要一眼看得出來,故未選為描邊、選取為實心底色,並各自帶事件類型的顏色
   (新增/加碼綠、減碼/剔除紅),與異動 pill 同一套視覺語言。 */
.chip{background:transparent;border:1px solid var(--line);color:var(--ink-dim);
  border-radius:99px;padding:.28rem .8rem;font-size:.76rem;cursor:pointer;
  display:inline-flex;align-items:center;gap:4px;user-select:none;
  transition:background .12s,color .12s,border-color .12s}
.chip .g{font-size:.62rem;line-height:1}
.chip:hover{border-color:var(--c,var(--blue));color:var(--ink)}
.chip.on{background:var(--c,var(--blue));border-color:var(--c,var(--blue));
  color:#0a0e17;font-weight:700}
.chip[data-t="ADD"],.chip[data-t="INCREASE"]{--c:var(--up)}
.chip[data-t="REMOVE"],.chip[data-t="DECREASE"]{--c:var(--down)}
.chip-hint{color:var(--ink-mute);font-size:.72rem;margin-left:.15rem}
/* 視覺隱藏但螢幕閱讀器讀得到:只用 placeholder 沒有真正的 label,輸入後
   placeholder 消失,使用者(尤其螢幕閱讀器)無法得知欄位用途或已填的內容 */
.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
/* 資料健康列:status=ok 只代表抓取成功,不代表資料最新,必須讓人看得出差別 */
.health{display:flex;flex-wrap:wrap;gap:.4rem;margin:.2rem 0 .1rem}
.hb{background:var(--panel-2);border:1px solid var(--line);border-radius:5px;
  padding:.22rem .6rem;font-size:.73rem;color:var(--ink-mute)}
.hb b{color:var(--ink-dim);font-weight:700;margin-left:.15rem}
.hb.ok b{color:var(--up)}
.hb.warn{border-color:rgba(250,178,25,.4)}.hb.warn b{color:var(--amber)}
/* 排行名次:併在個股欄前面,不另闢一欄 */
.rank{display:inline-block;min-width:1.6rem;color:var(--ink-mute);font-size:.76rem}
/* 加碼/減碼左右並置。手機一欄寬度不夠放兩張表,改上下堆疊。 */
.cols{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
@media(max-width:860px){.cols{grid-template-columns:1fr;gap:1.2rem}}
.colh{margin:0 0 .5rem;font-size:.82rem;font-weight:700;letter-spacing:.02em;
  padding-bottom:.35rem;border-bottom:1px solid var(--line)}
.colh.up{color:var(--up)}.colh.down{color:var(--down)}
.etf-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:.85rem}
.etf-card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:.9rem}
.etf-card h3{margin:0 0 .15rem;font-size:.92rem}
.etf-meta{display:grid;grid-template-columns:repeat(2,1fr);gap:.3rem .8rem;
  margin:.6rem 0;font-size:.76rem;color:var(--ink-dim)}
.etf-meta b{color:var(--ink);font-weight:600}
.bar-row{display:flex;align-items:center;gap:.5rem;margin:.22rem 0;font-size:.76rem}
.bar-row .nm{width:5.5rem;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{flex:1;height:10px;background:rgba(154,168,189,.09);border-radius:2px;
  overflow:hidden;position:relative}
/* span 預設 display:inline,寬高與背景都不會生效,必須 block。
   顏色是 sequential(權重越大越亮),不是按名次配色——名次配色會讓同一檔股票
   在不同 ETF 卡片上換色。資料端末圓角 4px 是 dataviz 的 mark spec。 */
.bar-fill{display:block;height:100%;border-radius:0 4px 4px 0;
  background:var(--c,var(--blue))}
/* 今日有異動的持股,在 bar 末端加一道方向色記號(色相+位置雙通道) */
.bar-row.moved .bar-track::after{content:'';position:absolute;top:0;bottom:0;right:0;
  width:3px;background:var(--mv)}
.bar-row.up{--mv:var(--up)}.bar-row.down{--mv:var(--down)}
.bar-row .pc{width:3.2rem;text-align:right;color:var(--ink-dim)}
.bar-row.moved .pc{color:var(--mv);font-weight:600}
details summary{cursor:pointer;color:var(--ink-dim);font-size:.78rem;margin-top:.6rem}
.empty{color:var(--ink-mute);font-size:.83rem;padding:1rem 0;text-align:center}
.note{color:var(--ink-mute);font-size:.74rem;line-height:1.6}
footer{border-top:1px solid var(--line);margin-top:2rem;padding:1rem 0 2rem;
  color:var(--ink-mute);font-size:.74rem;line-height:1.7}
.visits{display:flex;justify-content:center;gap:1.2rem;margin-top:1rem;
  padding-top:.9rem;border-top:1px solid var(--line);
  font-family:'JetBrains Mono','SF Mono',ui-monospace,monospace;
  font-size:.72rem;color:var(--ink-mute)}
.visits b{color:var(--ink-dim);font-weight:700}
.scroll{overflow-x:auto}
@media(max-width:640px){.etf-grid{grid-template-columns:1fr}}

/* ---------- 手機版:.rt 的表格轉成卡片 ----------
   窄螢幕下橫向捲動的表格很難用:關鍵欄位(張數/金額)被推到畫面外,而且只要有
   一欄會換行(例如共識榜的 ETF 清單),整列就被撐得極高、中間全是空白。
   這裡把每一列改成一張卡片,欄位標籤取自 td 的 data-l,一份 HTML 兩種版型。 */
@media(max-width:640px){
  .rt{overflow-x:visible}
  .rt table,.rt tbody,.rt tr,.rt td{display:block;width:auto}
  .rt thead{display:none}
  .rt tr{border:1px solid var(--line);border-radius:8px;
    padding:.6rem .7rem;margin-bottom:.5rem;background:var(--panel-2)}
  .rt tr:hover td{background:none}
  .rt td{border:0;padding:.2rem 0;white-space:normal;text-align:left;
    display:flex;justify-content:space-between;align-items:center;gap:.9rem}
  .rt td::before{content:attr(data-l);color:var(--ink-mute);font-size:.72rem;
    flex:none}
  /* 第一欄(個股或 ETF)當卡片標題:不顯示標籤、獨佔一行 */
  .rt td:first-child{display:block;font-size:.92rem;font-weight:600;
    padding-bottom:.4rem;margin-bottom:.35rem;border-bottom:1px solid var(--line)}
  .rt td:first-child::before{content:none}
  .rt td.num.mono:not(:first-child){font-variant-numeric:tabular-nums}
  /* 值為「—」的欄位在卡片上只是雜訊(個股反查每張卡都會多一行空的近期異動) */
  .rt td.na{display:none}
  /* ETF 清單是多個 span + 頓號,在 flex + space-between 下每個都成了獨立項目,
     會被平均拉開。改成標籤獨立一行、代號在下方自然靠左排。 */
  .rt td.etflist{display:block}
  .rt td.etflist::before{display:block;margin-bottom:.25rem}
}
"""

JS = r"""
const $ = s => document.querySelector(s);
// 一律用它包外部字串(投信基金名、個股名、使用者輸入)再塞進 innerHTML。
// 這些值來自投信網頁,不是我們控制的;使用者輸入更是直接來自輸入框。
const esc = v => String(v == null ? '' : v)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const fmt = n => n == null ? '—' : n.toLocaleString('en-US');
const pct = n => n == null ? '—' : n.toFixed(2) + '%';
const money = n => n == null ? '—' : (n >= 1e8 ? (n/1e8).toFixed(1)+' 億'
  : n >= 1e4 ? (n/1e4).toFixed(0)+' 萬' : fmt(n));
// 買賣金額/張數一律帶正負號。money() 收的是絕對值,負號由這裡補,
// 否則減碼會顯示成「1.9 億」看起來像買進。
const signed = (text, v) => (v > 0 ? '+' : v < 0 ? '−' : '') + String(text).replace(/^-/, '');
// [文字, class, 字符]。字符不是裝飾:綠↔紅在紅綠色盲下 deutan ΔE 只有 6.5,
// 方向必須有色相以外的第二通道才讀得出來。
const TYPE = {ADD:['新增','p-add','✚'],INCREASE:['加碼','p-inc','▲'],
              REMOVE:['剔除','p-rem','✕'],DECREASE:['減碼','p-dec','▼']};
const pill = t => '<span class="pill ' + TYPE[t][1] + '"><span class="g">'
  + TYPE[t][2] + '</span>' + TYPE[t][0] + '</span>';
// 權重 → sequential 藍階(低→高越亮)。只走對比 >=3:1 的區段,深色面板才看得見。
const SEQ_LO = [37,106,191], SEQ_HI = [158,197,244];
const seqColor = (w, max) => {
  const t = max > 0 ? Math.min(1, Math.max(0, w / max)) : 0;
  const c = SEQ_LO.map((lo, i) => Math.round(lo + (SEQ_HI[i] - lo) * t));
  return 'rgb(' + c.join(',') + ')';
};
const dispoSet = new Set(DATA.crosslinks.dispo || []);
const notes = DATA.crosslinks.notes || {};

function stockCell(code, name) {
  // name 來自投信網站爬回來的資料,不是使用者輸入,但仍是外部字串——
  // 一律 esc() 再塞進 innerHTML,不要賭它永遠乾淨。
  let h = '<span class="mono">' + code + '</span> ' + esc(name || '');
  if (dispoSet.has(code)) h += ' <span class="pill p-dispo"><span class="g">!</span>處置</span>';
  if (notes[code]) h += ' <a href="' + notes[code] + '" target="_blank" title="研究筆記"'
    + ' class="pill p-note" style="text-decoration:none"><span class="g">◆</span>筆記</a>';
  return h;
}

/* ---------- Tab 1:今日異動 ---------- */
const allEvents = [];
for (const [etf, e] of Object.entries(DATA.etfs))
  for (const ev of e.events || []) allEvents.push({etf, ...ev});

// 預設只看加碼:一次進來最想知道的是經理人買了什麼,再點一次該 chip 可看全部
let filterType = 'INCREASE', filterEtf = '', filterQ = '';

// 該檔今日的「持股變化估值」(帶正負號)= 主動調整估算股數 × 收盤價。
// 這不是實際成交金額:它只統計通過門檻的事件,且以收盤價估算,不是成交價。
function netAmount(code, sharesDelta) {
  const stock = DATA.stocks[code] || {};
  const px = stock.quote_date === DATA.updated ? stock.close : null;
  return (sharesDelta != null && px) ? sharesDelta * px : null;
}

// 金額由大到小(比絕對值);算不出金額的排最後,退而用檔數/張數當次要鍵。
function byAmountDesc(a, b) {
  const x = netAmount(a.code, a.shares_delta), y = netAmount(b.code, b.shares_delta);
  if (x == null && y == null)
    return Math.abs(b.shares_delta || 0) - Math.abs(a.shares_delta || 0);
  if (x == null) return 1;
  if (y == null) return -1;
  return Math.abs(y) - Math.abs(x);
}

// 一列的共用欄位:張數 + 金額(兩張表共用,避免兩處算法分岔)
function lotsAmtCells(r, cls) {
  const lots = r.shares_delta == null ? null : r.shares_delta / 1000;
  const amt = netAmount(r.code, r.shares_delta);
  return '<td data-l="張數" class="num mono ' + cls + '">' +
      (lots == null ? '—' : signed(Math.round(lots).toLocaleString('en-US'), lots)) +
    '</td><td data-l="金額" class="num mono ' + cls + '">' +
      (amt == null ? '—' : signed(money(Math.abs(amt)), amt)) + '</td>';
}

/* ---------- 今日異動金額排行 ---------- */
// 把全體 ETF 的事件依個股彙總成「主動調整估算股數」。同一檔股票可能在 A 檔 ETF
// 被加碼、在 B 檔被減碼,這裡取淨額。與共識榜不同:共識榜要求 2 檔以上同方向,
// 這裡只要有異動就算。**只涵蓋通過門檻的事件**,未達門檻的變化不在內,
// 所以不是「全體 ETF 對該股的真實淨買賣」。
const FLOW_TOP_N = 10;
function dailyFlows() {
  const m = {};
  for (const [etf, e] of Object.entries(DATA.etfs))
    for (const ev of e.events || []) {
      if (!ev.daily_comparable || ev.to_date !== DATA.updated || ev.adjusted_shares_delta == null) continue;
      const f = m[ev.code] || (m[ev.code] =
        {code: ev.code, name: ev.name, shares_delta: 0, etfs: []});
      // 與 outputs 一致:優先用校正後的主動調整估算
      f.shares_delta += (ev.adjusted_shares_delta != null
        ? ev.adjusted_shares_delta : (ev.shares_delta || 0));
      if (!f.etfs.includes(etf)) f.etfs.push(etf);
    }
  return Object.values(m).filter(f => f.shares_delta !== 0);
}

function renderFlowTable(rows, dir) {
  if (!rows.length)
    return '<div class="empty">今日沒有' + (dir === 'up' ? '淨買超' : '淨賣超') + '的標的</div>';
  return '<div class="scroll rt"><table><thead><tr><th>個股</th>' +
    '<th class="num">張數</th><th class="num">金額</th><th class="num">檔數</th>' +
    '</tr></thead><tbody>' +
    rows.map((r, i) =>
      '<tr><td data-l="個股"><span class="rank mono">' + (i + 1) + '</span>' +
      stockCell(r.code, r.name) + '</td>' + lotsAmtCells(r, dir) +
      '<td data-l="檔數" class="num mono">' + r.etfs.length + '</td></tr>').join('') +
    '</tbody></table></div>';
}

function paintFlows() {
  const all = dailyFlows();
  $('#flowUp').innerHTML = renderFlowTable(
    all.filter(f => f.shares_delta > 0).sort(byAmountDesc).slice(0, FLOW_TOP_N), 'up');
  $('#flowDown').innerHTML = renderFlowTable(
    all.filter(f => f.shares_delta < 0).sort(byAmountDesc).slice(0, FLOW_TOP_N), 'down');
}

/* ---------- 經理人共識榜 ---------- */
function renderConsensusTable(rows, dir) {
  if (!rows.length)
    return '<div class="empty">今日沒有 2 檔以上 ETF 同步' +
      (dir === 'up' ? '加碼' : '減碼') + '的標的</div>';
  return '<div class="scroll rt"><table><thead><tr><th>個股</th>' +
    '<th class="num">檔數</th><th class="num">張數</th><th class="num">金額</th>' +
    '<th>ETF</th></tr></thead><tbody>' +
    rows.map(r =>
      '<tr><td data-l="個股">' + stockCell(r.code, r.name) + '</td>' +
      '<td data-l="檔數" class="num ' + dir + '">' + r.etfs.length + '</td>' +
      lotsAmtCells(r, dir) +
      '<td data-l="ETF" class="etflist" style="white-space:normal">' +
      r.etfs.map(e => '<span class="mono">' + e + '</span>').join('、') +
      '</td></tr>').join('') + '</tbody></table></div>';
}

function renderEvents() {
  let rows = allEvents.filter(e =>
    (!filterType || e.type === filterType) &&
    (!filterEtf || e.etf === filterEtf) &&
    (!filterQ || e.code.includes(filterQ) || (e.name || '').includes(filterQ)));
  if (!rows.length) return '<div class="empty">沒有符合條件的異動</div>';
  const order = {ADD: 0, INCREASE: 1, DECREASE: 2, REMOVE: 3};
  rows.sort((a, b) => order[a.type] - order[b.type] ||
    Math.abs(b.weight_delta || b.weight || 0) - Math.abs(a.weight_delta || a.weight || 0));
  return '<div class="scroll rt"><table><thead><tr><th>ETF</th><th>個股</th><th>異動</th>' +
    '<th class="num">權重</th><th class="num">權重變化</th><th class="num">股數變化</th>' +
    '</tr></thead><tbody>' + rows.map(e => {
      const dw = e.weight_delta, ds = e.shares_delta_pct;
      const dir = (e.type === 'ADD' || e.type === 'INCREASE') ? 'up' : 'down';
      return '<tr><td data-l="ETF"><span class="mono">' + e.etf + '</span><br><small class="sub">' + esc(e.from_date || '—') + ' → ' + esc(e.to_date || '—') + '</small></td>' +
        '<td data-l="個股">' + stockCell(e.code, e.name) + '</td>' +
        '<td data-l="異動">' + pill(e.type) + '</td>' +
        '<td data-l="權重" class="num mono">' + (e.weight != null ? pct(e.weight) : pct(e.prev_weight)) + '</td>' +
        '<td data-l="權重變化" class="num mono ' + dir + (dw == null ? ' na' : '') + '">' +
          (dw != null ? (dw > 0 ? '+' : '') + dw.toFixed(2) : '—') + '</td>' +
        '<td data-l="股數變化" class="num mono ' + dir + (ds == null ? ' na' : '') + '">' +
          (ds != null ? (ds > 0 ? '+' : '') + ds.toFixed(1) + '%' : '—') + '</td></tr>';
    }).join('') + '</tbody></table></div>';
}

function paintTab1() {
  paintFlows();
  const c = DATA.consensus;
  $('#consUp').innerHTML = renderConsensusTable(
    [...c.increase].sort(byAmountDesc), 'up');
  $('#consDown').innerHTML = renderConsensusTable(
    [...c.decrease].sort(byAmountDesc), 'down');
  $('#events').innerHTML = renderEvents();
}

/* ---------- Tab 2:各檔 ETF ---------- */
function etfCard(code, e) {
  const top = [...e.holdings].sort((a, b) => b.weight - a.weight).slice(0, 10);
  const max = top.length ? top[0].weight : 1;
  // 這檔 ETF 今日動過的標的:bar 末端加方向色記號,一眼看出經理人改了哪幾檔
  const moves = {};
  for (const ev of e.events || [])
    moves[ev.code] = (ev.type === 'ADD' || ev.type === 'INCREASE') ? 'up' : 'down';
  const bars = top.map(h => {
    const mv = moves[h.code];
    return '<div class="bar-row' + (mv ? ' moved ' + mv : '') + '">' +
      '<span class="nm">' + esc(h.name) + '</span>' +
      '<span class="bar-track"><span class="bar-fill" style="width:' +
      (h.weight / max * 100).toFixed(1) + '%;--c:' + seqColor(h.weight, max) + '"></span></span>' +
      '<span class="pc mono">' + h.weight.toFixed(2) + '%</span></div>';
  }).join('');
  const stale = e.status === 'stale'
    ? ' <span class="pill p-stale">資料未更新</span>' : '';
  const prem = e.premium_pct;
  const full = '<details><summary>完整持股 ' + e.holdings.length + ' 檔</summary>' +
    '<div class="scroll"><table><thead><tr><th>個股</th><th class="num">股數</th>' +
    '<th class="num">權重</th></tr></thead><tbody>' +
    [...e.holdings].sort((a, b) => b.weight - a.weight).map(h =>
      '<tr><td>' + stockCell(h.code, h.name) + '</td><td class="num mono">' + fmt(h.shares) +
      '</td><td class="num mono">' + h.weight.toFixed(2) + '%</td></tr>').join('') +
    '</tbody></table></div></details>';
  return '<div class="etf-card"><h3><span class="mono">' + code + '</span> ' + esc(e.name) + stale + '</h3>' +
    '<div class="sub" style="font-size:.72rem">' + (e.issuer || '') + '投信 · 資料日 ' +
    (e.data_date || '—') + '</div>' +
    '<div class="etf-meta"><span>規模 <b>' + money(e.scale) + '</b></span>' +
    '<span>受益人 <b>' + fmt(e.holders) + '</b></span>' +
    '<span>淨值 <b>' + (e.nav != null ? e.nav.toFixed(2) : '—') + '</b></span>' +
    '<span>折溢價 <b class="' + (prem > 0 ? 'up' : prem < 0 ? 'down' : '') + '"' +
    (e.premium_note ? ' title="' + esc(e.premium_note) + '"' : '') + '>' +
    (prem != null ? (prem > 0 ? '+' : '') + prem.toFixed(2) + '%'
                  : (e.premium_note ? '—*' : '—')) + '</b></span></div>' +
    bars + full + '</div>';
}

function paintTab2() {
  const active = Object.entries(DATA.etfs).filter(([, e]) => e.holdings.length);
  const pending = Object.entries(DATA.etfs).filter(([, e]) => !e.holdings.length);
  active.sort((a, b) => (b[1].scale || 0) - (a[1].scale || 0));
  let h = '<div class="etf-grid">' + active.map(([c, e]) => etfCard(c, e)).join('') + '</div>';
  if (pending.length) {
    // 不能把所有空 holdings 都叫「adapter 待補」:新掛牌但首次抓取失敗、
    // 手動停用、當日無資料,跟「沒有 adapter」是完全不同的狀況。
    const label = e => e.status === 'unsupported' ? '尚未支援此投信'
                     : e.status === 'disabled' ? '已手動停用'
                     : e.status === 'stale' ? '抓取失敗(無可沿用的快照)'
                     : '本次無資料';
    const groups = {};
    pending.forEach(([c, e]) => (groups[label(e)] = groups[label(e)] || []).push([c, e]));
    h += '<div class="panel" style="margin-top:1rem"><h2>未納入統計的 ETF' +
      '<span class="hint">依原因分類;補上 adapter 或來源恢復後自動納入</span></h2>' +
      Object.entries(groups).map(([g, items]) =>
        '<div style="margin:.5rem 0"><div class="note" style="margin-bottom:.3rem">' +
        esc(g) + '(' + items.length + ')</div>' +
        items.map(([c, e]) => '<span class="pill p-gray" style="margin:.2rem">' +
          c + ' ' + esc(e.name) + '</span>').join('') + '</div>').join('') +
      '</div>';
  }
  $('#etfs').innerHTML = h;
}

/* ---------- Tab 3:個股反查 ---------- */
// 被全部 ETF 持有的個股,逐一列出 22 個代號等於沒有資訊——排行前十幾乎都是這樣,
// 每張卡重複同一串代號、佔掉五行。這種情況改講「全部 N 檔」。
const TRACKED_N = Object.values(DATA.etfs).filter(e => (e.holdings || []).length).length;
function etfListCell(codes) {
  if (TRACKED_N && codes.length === TRACKED_N)
    return '<span style="color:var(--ink-mute)">全部 ' + TRACKED_N + ' 檔</span>';
  return codes.map(c => '<span class="mono">' + c + '</span>').join('、');
}

function paintRanking() {
  const rows = Object.entries(DATA.stocks)
    .filter(([, s]) => s.etfs.length)
    .sort((a, b) => b[1].etfs.length - a[1].etfs.length ||
                    b[1].total_weight - a[1].total_weight).slice(0, 30);
  // 名次併進「個股」欄而不獨立成一欄:手機轉卡片時第一欄會變成卡片標題,
  // 名次單獨一欄會佔掉整個標題行,個股名反而被降級成一般欄位。
  $('#ranking').innerHTML = '<div class="scroll rt"><table><thead><tr><th>個股</th>' +
    '<th class="num">持有檔數</th><th class="num">合計權重</th><th>ETF</th></tr></thead><tbody>' +
    rows.map(([code, s], i) =>
      '<tr><td data-l="個股"><span class="rank mono">' + (i + 1) + '</span>' +
      stockCell(code, s.name) + '</td>' +
      '<td data-l="持有檔數" class="num mono">' + s.etfs.length + '</td>' +
      '<td data-l="合計權重" class="num mono">' + s.total_weight.toFixed(2) + '%</td>' +
      '<td data-l="ETF" class="etflist" ' +
      'style="white-space:normal;color:var(--ink-dim);font-size:.76rem">' +
      etfListCell(s.etfs.map(x => x.etf)) +
      '</td></tr>').join('') + '</tbody></table></div>';
}

function lookup(q) {
  q = (q || '').trim();
  if (!q) { $('#lookup').innerHTML = '<div class="empty">輸入股票代號或名稱查詢</div>'; return; }
  // 精確代號優先,其餘列為候選。原本用 .find() 只取第一筆,輸入「台」這種
  // 部分名稱時會被鎖在某一檔上,選不到其他標的。
  const all = Object.entries(DATA.stocks);
  const exact = all.filter(([c]) => c === q);
  const fuzzy = all.filter(([c, st]) => c !== q &&
    (c.includes(q) || (st.name || '').includes(q)));
  const pick = exact.length ? exact : fuzzy;
  // 趨勢資料是另檔非同步載入;還沒載完就先等,免得把「已出清但有歷史」誤報成查無
  const T = window.ETFTrends;
  if (!pick.length && T && !T.settled && T.ready) {
    $('#lookup').innerHTML = '<div class="note">歷史資料載入中…</div>';
    T.ready.then(() => lookup(q)); return;
  }
  if (!pick.length && window.TREND_DATA && window.TREND_DATA.stocks[q]) {
    window.ETFTrends.openStock(q);
    $('#lookup').innerHTML = '<div class="note">此股目前未持有，已開啟歷史趨勢。</div>'; return;
  }
  if (!pick.length) {
    $('#lookup').innerHTML = '<div class="empty">查無「' + esc(q) +
      '」——目前沒有主動式 ETF 持有,近期也沒有異動紀錄</div>';
    return;
  }
  const [code, s] = pick[0];
  const others = pick.slice(1, 9);
  const rows = [...s.etfs].sort((a, b) => b.weight - a.weight);
  const evs = s.recent_events || [];
  // 已出清的 ETF 不會出現在 s.etfs,只走訪持有者會讓「剔除」完全消失。
  const heldSet = new Set(rows.map(r => r.etf));
  const gone = evs.filter(e => !heldSet.has(e.etf));

  const cand = others.length
    ? '<div class="note" style="margin:-.3rem 0 .7rem">其他符合:' +
      others.map(([c, st]) =>
        '<a href="#" class="cand" data-c="' + c + '"><span class="mono">' + c +
        '</span> ' + esc(st.name) + '</a>').join('、') + '</div>'
    : '';

  const held = rows.length
    ? '<div class="scroll rt"><table><thead><tr><th>ETF</th><th class="num">權重</th>' +
      '<th class="num">股數</th><th>當日異動</th></tr></thead><tbody>' +
      rows.map(r => {
        const ev = evs.find(e => e.etf === r.etf);
        const tag = ev ? pill(ev.type) +
          ' <span style="color:var(--ink-mute);font-size:.72rem">' + ev.date + '</span>' : '—';
        return '<tr><td data-l="ETF"><span class="mono">' + r.etf + '</span></td>' +
          '<td data-l="權重" class="num mono">' + r.weight.toFixed(2) + '%</td>' +
          '<td data-l="股數" class="num mono">' + fmt(r.shares) + '</td>' +
          '<td data-l="當日異動"' + (ev ? '' : ' class="na"') + '>' + tag + '</td></tr>';
      }).join('') + '</tbody></table></div>'
    : '<div class="empty">目前沒有主動式 ETF 持有這檔</div>';

  // 出清的另開一區——不然「某檔 ETF 今天把它賣光了」這個最重要的訊息會消失
  const cleared = gone.length
    ? '<h3 class="colh down" style="margin-top:1rem">已出清(不在上表)</h3>' +
      '<div class="scroll rt"><table><thead><tr><th>ETF</th><th>當日異動</th>' +
      '</tr></thead><tbody>' +
      gone.map(e => '<tr><td data-l="ETF"><span class="mono">' + e.etf + '</span><br><small class="sub">' + esc(e.from_date || '—') + ' → ' + esc(e.to_date || '—') + '</small></td>' +
        '<td data-l="當日異動">' + pill(e.type) +
        ' <span style="color:var(--ink-mute);font-size:.72rem">' + e.date +
        '</span></td></tr>').join('') + '</tbody></table></div>'
    : '';

  // total_value 一直有算卻沒顯示過;合計權重是跨基金相加,不是真實配置比例
  const val = s.total_value != null
    ? ' · 合計市值 <b>' + money(s.total_value) + '</b>' +
      (s.close ? '<span style="color:var(--ink-mute)">(收盤 ' + s.close + ')</span>' : '')
    : '';
  $('#lookup').innerHTML = '<h2 style="margin:.2rem 0 .8rem">' + stockCell(code, s.name) +
    ' <span class="hint" style="color:var(--ink-mute);font-size:.76rem">被 ' + rows.length +
    ' 檔持有 · 合計 ' + fmt(s.total_shares) + ' 股' + val +
    ' · 權重加總 ' + s.total_weight.toFixed(2) + '%(跨基金相加,非真實配置比例)' +
    '</span></h2>' + '<button type="button" class="trend-link" id="lookupTrend">查看累積加減碼趨勢</button>' + cand + held + cleared;
  $('#lookupTrend').onclick = () => window.ETFTrends && window.ETFTrends.openStock(code);

  document.querySelectorAll('#lookup .cand').forEach(a => a.onclick = ev => {
    ev.preventDefault();
    $('#lookupQ').value = a.dataset.c;
    lookup(a.dataset.c);
  });
}


/* ---------- 初始化 ---------- */
function tab(n) {
  document.querySelectorAll('nav button').forEach((b, i) =>
    b.classList.toggle('on', i === n));
  document.querySelectorAll('section').forEach((s, i) =>
    s.style.display = i === n ? '' : 'none');
}
document.querySelectorAll('nav button').forEach((b, i) =>
  b.onclick = () => tab(i));
// 單選:點另一個就換過去,再點同一個則取消回到「全部」
document.querySelectorAll('#typeChips .chip').forEach(c => c.onclick = () => {
  const t = c.dataset.t;
  filterType = (filterType === t) ? '' : t;
  document.querySelectorAll('#typeChips .chip').forEach(x => {
    const on = x.dataset.t === filterType;
    x.classList.toggle('on', on);
    // <button> 原生就能 Tab/Enter/Space 操作(原本是 <span>,鍵盤使用者按不到);
    // aria-pressed 讓螢幕閱讀器知道這是切換按鈕,而不只是普通按鈕
    x.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  $('#events').innerHTML = renderEvents();
});
$('#etfSel').onchange = e => { filterEtf = e.target.value; $('#events').innerHTML = renderEvents(); };
$('#evQ').oninput = e => { filterQ = e.target.value.trim(); $('#events').innerHTML = renderEvents(); };
$('#lookupQ').oninput = e => lookup(e.target.value);
paintTab1(); paintTab2(); paintRanking(); lookup(''); tab(0);

/* 瀏覽計數:Abacus(免註冊、免 API key),與信用卡儀表板同一套做法。
   原本用的 CounterAPI v1 已於 2026/07 停用(回 410),故遷移過來。
   - /hit/<ns>/<key> 遞增並回傳 {"value":N}
   - 日計數以「台灣時間」換日:直接用 UTC 會變成早上 8 點才跨日
   - 用 allSettled 而非 all:其中一個失敗時另一個仍顯示得出來
   - 全部失敗就整塊不顯示,不要在頁尾留一行壞掉的字 */
(function () {
  const base = 'https://abacus.jasoncameron.dev/hit/__NS__';
  const today = new Date(Date.now() + 8 * 3600 * 1000)
    .toISOString().slice(0, 10).replace(/-/g, '');
  const el = $('#visits');
  const num = v => (v && typeof v.value === 'number')
    ? v.value.toLocaleString('en-US') : null;
  Promise.allSettled([
    fetch(base + '/total').then(r => r.json()),
    fetch(base + '/day-' + today).then(r => r.json()),
  ]).then(([total, day]) => {
    const t = total.status === 'fulfilled' ? num(total.value) : null;
    const d = day.status === 'fulfilled' ? num(day.value) : null;
    const parts = [];
    if (d) parts.push('<span>今日瀏覽 <b>' + d + '</b></span>');
    if (t) parts.push('<span>累計瀏覽 <b>' + t + '</b></span>');
    if (parts.length) el.innerHTML = parts.join('');
    else el.style.display = 'none';
  }).catch(() => { el.style.display = 'none'; });
})();
"""


def _days_between(older, newer):
    """兩個 YYYY-MM-DD 相差幾天;無法解析或非落後回 0。"""
    import datetime
    try:
        a = datetime.date.fromisoformat(older)
        b = datetime.date.fromisoformat(newer)
    except (TypeError, ValueError):
        return 0
    return max((b - a).days, 0)


def build_id_of(active):
    """由 active.json 內容算出的確定性 build_id。

    部署驗證只比「Updated YYYY-MM-DD」的話,同日修 UI 或補資料後即使線上仍是
    舊版也會通過。改用內容雜湊,同日不同內容就驗得出來。
    """
    import hashlib
    # 排除 build_id 自身,否則「先算再塞回去」會讓後續重算得到不同結果
    payload = json.dumps({k: v for k, v in active.items() if k != "build_id"},
                         ensure_ascii=False, sort_keys=True)
    from pathlib import Path
    assets = CSS + JS + Path(__file__).read_text()
    assets += "".join((ASSETS / name).read_text() for name in ("trends_ui.js", "trends_ui.css", "trends_ui.html"))
    return hashlib.sha256((payload + assets).encode("utf-8")).hexdigest()[:12]


def render(active, registry):
    date = active["updated"]
    etfs = active["etfs"]
    tracked = {c: e for c, e in etfs.items() if e["holdings"]}
    n_events = sum(len(e["events"]) for e in etfs.values())
    n_cons = len(active["consensus"]["increase"]) + len(active["consensus"]["decrease"])
    stale = [c for c, e in etfs.items() if e["status"] == "stale"]

    # 下拉也只顯示代號(使用者要求除「各檔 ETF」頁外都不出現中文名)
    opts = "".join('<option value="{0}">{0}</option>'.format(c)
                   for c in sorted(tracked))
    chips = "".join(
        '<button type="button" class="chip{3}" data-t="{0}" '
        'aria-pressed="{4}"><span class="g">{2}</span>{1}</button>'.format(
            t, label, GLYPH[t], " on" if t == DEFAULT_FILTER else "",
            "true" if t == DEFAULT_FILTER else "false")
        for t, label in (("ADD", "新增"), ("INCREASE", "加碼"),
                         ("DECREASE", "減碼"), ("REMOVE", "剔除")))
    # ── 資料健康列 ────────────────────────────────────────────────────────
    # status=ok 只代表「抓取成功」,不代表「資料是最新的」——實測常有 5 檔停在
    # 前一交易日卻仍標 ok。使用者有權一眼看出自己在看多新的資料,所以把
    # 「最新持股日、行情日、各狀態檔數、落後哪幾檔」直接放頁首。
    tracked_dates = [e.get("data_date") for e in etfs.values()
                     if e.get("status") in ("ok", "stale") and e.get("data_date")]
    latest = max(tracked_dates) if tracked_dates else date
    behind = sorted(c for c, e in etfs.items()
                    if e.get("status") in ("ok", "stale")
                    and e.get("data_date") and e["data_date"] < latest)
    quote_dates = {e.get("quote_date") for e in etfs.values() if e.get("quote_date")}
    qd = sorted(quote_dates)[-1] if quote_dates else "—"
    n_ok = sum(1 for e in etfs.values() if e.get("status") == "ok")
    n_stale = sum(1 for e in etfs.values() if e.get("status") == "stale")
    n_unsup = sum(1 for e in etfs.values() if e.get("status") == "unsupported")
    n_noprem = sum(1 for e in etfs.values() if e.get("premium_note"))

    chips_health = ['<span class="hb">最新持股日 <b>{}</b></span>'.format(latest),
                    '<span class="hb">行情日 <b>{}</b></span>'.format(qd),
                    '<span class="hb ok">成功 <b>{}</b></span>'.format(n_ok)]
    if n_stale:
        chips_health.append('<span class="hb warn">沿用舊資料 <b>{}</b></span>'.format(n_stale))
    if behind:
        chips_health.append('<span class="hb warn">來源落後 <b>{}</b></span>'.format(len(behind)))
    if n_unsup:
        chips_health.append('<span class="hb">尚未支援 <b>{}</b></span>'.format(n_unsup))
    if n_noprem:
        chips_health.append('<span class="hb warn">折溢價留白 <b>{}</b></span>'.format(n_noprem))

    detail = []
    if stale:
        detail.append("沿用舊資料:" + "、".join(
            "{}(停在 {}{})".format(
                c, (etfs[c] or {}).get("data_date") or "—",
                "、落後 {} 天".format(_days_between((etfs[c] or {}).get("data_date"), latest))
                if _days_between((etfs[c] or {}).get("data_date"), latest) else "")
            for c in stale))
    if behind:
        detail.append("來源落後(抓取成功但投信尚未更新):" + "、".join(
            "{}({})".format(c, etfs[c].get("data_date")) for c in behind))
    if n_noprem:
        detail.append("折溢價留白:NAV 日與行情日不同,不輸出跨日數字")

    stale_note = ('<div class="health">' + "".join(chips_health) + '</div>'
                  + ('<div class="note" style="margin-top:.4rem">'
                     + ";".join(detail) + "。</div>" if detail else ""))

    return """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="build-id" content="{build_id}">
<title>台股主動式ETF追蹤 | Updated {date}</title>
<!-- AUTO:DATE:{date} -->
<style>{css}
{trend_css}</style>
</head>
<body>
<header><div class="wrap">
  <h1>台股主動式 ETF 每日追蹤</h1>
  <div class="sub">經理人持股異動 · 持股比例分佈 · 個股反向查詢 　|　 資料日 <b>{date}</b></div>
</div></header>

<div class="wrap">
  <div class="kpis">
    <div class="kpi k-etf"><div class="n">{n_etf}</div><div class="l">追蹤 ETF</div></div>
    <div class="kpi k-stock"><div class="n">{n_stock}</div><div class="l">涵蓋個股</div></div>
    <div class="kpi k-move{z_events}"><div class="n">{n_events}</div><div class="l">今日異動</div></div>
    <div class="kpi k-cons{z_cons}"><div class="n">{n_cons}</div><div class="l">共識進出</div></div>
  </div>
  {stale_note}

  <nav>
    <button class="on">今日異動</button>
    <button>各檔 ETF</button>
    <button>個股反查／趨勢</button>
    <button>累積加減碼排行</button>
  </nav>

  <section>
    <div class="panel">
      <h2>今日持股變化估值排行<span class="hint">通過門檻的加減碼 × 收盤價估算(非實際成交金額),各取前 10</span></h2>
      <div class="cols">
        <div><h3 class="colh up">▲ 增加</h3><div id="flowUp"></div></div>
        <div><h3 class="colh down">▼ 減少</h3><div id="flowDown"></div></div>
      </div>
    </div>
    <div class="panel">
      <h2>經理人共識榜<span class="hint">2 檔以上主動式 ETF 今日同方向調整的標的</span></h2>
      <div class="cols">
        <div><h3 class="colh up">▲ 同步加碼</h3><div id="consUp"></div></div>
        <div><h3 class="colh down">▼ 同步減碼</h3><div id="consDown"></div></div>
      </div>
    </div>
    <div class="panel">
      <h2>今日持股異動明細</h2>
      <div class="controls">
        <span id="typeChips">{chips}</span><span class="chip-hint">(點選篩選一種,再點一次看全部)</span>
        <label for="etfSel" class="sr-only">篩選 ETF</label>
        <select id="etfSel"><option value="">全部 ETF</option>{opts}</select>
        <label for="evQ" class="sr-only">搜尋個股代號或名稱</label>
        <input id="evQ" placeholder="搜尋個股代號 / 名稱">
      </div>
      <div id="events"></div>
      <div class="note" style="margin-top:.7rem">
        加碼/減碼已扣除申購贖回造成的等比例增減(以全體持股股數變化中位數校正),
        呈現依持股差異推估的主動調整;門檻為校正後股數變化 ≥5% 且權重變化 ≥0.1 個百分點。
      </div>
    </div>
  </section>

  <section style="display:none">
    <div id="etfs"></div>
  </section>

  <section style="display:none">
    <div class="panel">
      <h2>個股反向查詢<span class="hint">查某檔股票被哪些主動式 ETF 持有、各佔多少</span></h2>
      <div class="controls"><label for="lookupQ" class="sr-only">輸入股票代號或名稱查詢</label>
        <input id="lookupQ" placeholder="輸入股票代號或名稱,如 2330 或 台積電"></div>
      <div id="lookup"></div>
    </div>
    {trend_panel}
    <div class="panel">
      <h2>共識持股排行<span class="hint">被最多檔主動式 ETF 同時持有的個股 Top 30</span></h2>
      <div id="ranking"></div>
    </div>
  </section>

  <section style="display:none">
    <div class="panel">
      <h2>累積加減碼排行<span class="hint">固定樣本的淨調整估算；點個股看趨勢</span></h2>
      <div class="trend-controls"><label for="trendRankWindow">比較期間</label>
        <select id="trendRankWindow"><option value="5">近 5 日</option><option value="20" selected>近 20 日</option><option value="60">近 60 日</option><option value="all">全部可用歷史</option></select>
        <label for="trendSort">排序</label><select id="trendSort"><option value="net">淨調整張數</option><option value="breadth">同方向 ETF 家數</option></select>
        <label for="trendDirection">方向</label><select id="trendDirection"><option value="buy">淨增持</option><option value="sell">淨減持</option></select>
      </div><p id="trendRankNote" class="note"></p><div id="trendRankTable"></div>
      <p class="note">5 日與 20 日可能使用不同固定樣本，兩欄不可直接相減推算中間期間；請點個股檢查可比家數。</p>
    </div>
  </section>

  <footer>
    資料來源:各投信官網每日公告之申購買回清單(PCF)/基金資產明細,收盤價取自 TWSE / TPEx。
    本頁每交易日盤後自動更新,僅供研究參考,不構成投資建議。<br>
    相關儀表板:<a href="https://nctuwanglin.github.io/twse-disposition/">台股處置股</a> ·
    <a href="https://nctuwanglin.github.io/stock-research-notes/">個股研究筆記</a>
  </footer>
  <div class="visits" id="visits"></div>
</div>
<script>const DATA = {data};</script>
<script>window.TREND_URL = {trend_url};</script>
<script>{js}</script>
<script>{trend_js}</script>
</body>
</html>
""".format(date=date, css=CSS, build_id=active.get("build_id") or build_id_of(active), js=JS.replace("__NS__", COUNTER_NS),
           trend_css=(ASSETS / "trends_ui.css").read_text(),
           trend_js=(ASSETS / "trends_ui.js").read_text(),
           trend_panel=(ASSETS / "trends_ui.html").read_text(),
           # 趨勢資料另檔載入(內嵌曾讓 index.html 長到 12 MB);?v= 讓瀏覽器與 CDN
           # 在內容變更時一定抓新檔
           trend_url=json.dumps("data/stock_trends.json?v=" + (active.get("trend_build_id") or "")),
           chips=chips, opts=opts,
           stale_note=stale_note,
           n_etf=len(tracked), n_stock=len(active["stocks"]),
           n_events=n_events, n_cons=n_cons,
           z_events="" if n_events else " zero", z_cons="" if n_cons else " zero",
           data=json.dumps(active, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c"))
