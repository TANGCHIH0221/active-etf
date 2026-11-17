const assert = require('node:assert/strict');
const ui = require('../scripts/trends_ui.js');
const data = {stocks:{'2330':{name:'台積電'},'9999':{name:'已出清'}},windows:{
  '20':{available:true,stocks:{'2330':{net_delta:2000,increasing_etfs:['A'],decreasing_etfs:[]},
  '9999':{net_delta:-1000,increasing_etfs:[],decreasing_etfs:['B']}}},
  '60':{available:false,reason:'insufficient_history'}}};
assert.equal(ui.selectWindow(data,'60').available,false);
assert.equal(ui.searchStocks(data,'9999')[0][1].name,'已出清');
assert.deepEqual(ui.rankStocks(data,'20','buy').map(r=>r.code),['2330']);
assert.deepEqual(ui.rankStocks(data,'20','sell').map(r=>r.code),['9999']);
assert.equal(ui.rankStocks(data,'60','buy').length,0);
assert.equal(ui.csvCell('=1+1'), '"\'=1+1"');
assert.equal(ui.csvCell('a,"b"'), '"a,""b"""');
assert.equal(ui.formatLots(null),'—');
assert.equal(ui.formatLots(-1200),'−1.2');
assert.equal(ui.formatLots(0),'0');
const rows=[{etf:'A',stock:'2330',from_date:'2026-09-30',to_date:'2026-10-01',adjusted_delta:10,quality:'ok'}];
assert.equal(ui.filterIntervals(rows,'2330',{from_date:'2026-09-30',to_date:'2026-10-02'}).length,1);
assert.equal(ui.filterIntervals(rows,'9999',{from_date:'2026-09-30',to_date:'2026-10-02'}).length,0);
console.log('Trend UI logic: 13 assertions passed');
const sorting={stocks:{A:{name:'A'},B:{name:'B'}},windows:{'20':{available:true,stocks:{
  A:{net_delta:1000,increasing_etfs:['X'],decreasing_etfs:[]},
  B:{net_delta:200,increasing_etfs:['X','Y'],decreasing_etfs:[]}}}}};
assert.deepEqual(ui.rankStocks(sorting,'20','buy','breadth').map(r=>r.code),['B','A']);
console.log('Breadth sort assertion passed');
