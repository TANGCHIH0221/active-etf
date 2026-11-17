import sys,json,copy,tempfile,contextlib,io,collections,re
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import outputs,update_dashboard as ud,render_html,quotes
from adapters.base import Holding
from diffengine import compute_events
E={}
def result(date,shares=100):
 return {'status':'ok','data_date':date,'holdings':[Holding('2330','台積電',shares,60)],'meta':{'nav_per_unit':10,'units':1000}}
def snap(date,shares=100):
 r=result(date,shares);r['holdings']=outputs.holdings_to_json(r['holdings']);r['events']=[]
 return {'date':date,'etfs':{'A':r}}
try: ud.compute_all_events({'NEW':result('2026-10-02')},snap('2026-10-01'))
except Exception as ex:E['new_etf_crash']=repr(ex)
r={'A':result('2026-10-01',100)}
ud.reject_regressions(r,snap('2026-10-01',100))
ud.carry_stale(r,{'A':{'market':'tw','status':'active'}},snap('2026-10-01'),snap('2026-10-02',200))
E['same_day_regression']={'retained_date':r['A']['data_date'],'retained_shares':r['A']['holdings'][0].shares,'existing_latest_date':'2026-10-02','existing_latest_shares':200}
before={'A':result('2026-10-02')};after=copy.deepcopy(before);after['A']['meta']['nav_per_unit']=11
E['nav_change_skips']=outputs.should_skip_results(after,outputs.results_fingerprint(before))
# Execute main with all external I/O stubbed; all writes are restricted to TemporaryDirectory.
def main_probe(rollback):
 with tempfile.TemporaryDirectory() as tmp,contextlib.ExitStack() as stack:
  p=Path(tmp);hist=p/'history';hist.mkdir()
  (hist/'2026-09-30.json').write_text(json.dumps(snap('2026-09-30')))
  (hist/'2026-10-01.json').write_text(json.dumps(snap('2026-10-01')))
  (hist/'2026-10-02.json').write_text(json.dumps(snap('2026-10-02',200)))
  active=p/'active.json';active.write_text(json.dumps({'updated':'2026-10-02','quote_missing':True}))
  reg={'A':{'market':'tw','status':'active','name':'A','issuer':'test'}}
  res={'A':result('2026-10-01' if rollback else '2026-10-02',100 if rollback else 200)}
  latest={'A':result('2026-10-02',200)}
  last=p/'last.json';outputs.update_last_counts('2026-10-02',{'A':1},last,outputs.results_fingerprint(latest))
  for k,v in {'HISTORY':hist,'REGISTRY_PATH':p/'reg.json','LAST_COUNTS':last,'PERF_STATS':p/'perf.json','ACTIVE_JSON':active,'INDEX_HTML':p/'index.html'}.items():stack.enter_context(patch.object(ud,k,v))
  stack.enter_context(patch.object(ud,'fetch_registry',return_value=reg));stack.enter_context(patch.object(ud,'fetch_all_holdings',return_value=res))
  quote=stack.enter_context(patch.object(ud.quotes_mod,'fetch_all',return_value=('2026-10-02',{'2330':100,'A':11},[])))
  stack.enter_context(patch.object(ud.crosslinks_mod,'fetch_crosslinks',return_value={'dispo':[],'notes':{}}))
  stack.enter_context(patch.object(sys,'argv',['probe']))
  with contextlib.redirect_stdout(io.StringIO()) as log:ret=ud.main()
  return {'return':ret,'quote_fetch_calls':quote.call_count,'active_updated':json.loads(active.read_text())['updated'],'log':log.getvalue()}
E['global_date_rollback']=main_probe(True)
E['quote_recovery_skipped']=main_probe(False)
a=json.loads((ROOT/'active.json').read_text());reg=json.loads((ROOT/'data/etf_registry.json').read_text())
h1=render_html.render(a,reg)
with patch.object(render_html,'CSS',render_html.CSS+'\n/* UI revision */'):
 h2=render_html.render(a,reg)
getid=lambda h:re.search(r'name="build-id" content="([^"]+)"',h).group(1)
E['ui_hash_unchanged']={'html_changed':h1!=h2,'old_id':getid(h1),'new_id':getid(h2)}
pv={str(i):Holding(str(i),'x',1000,20) for i in range(4)}
cu={str(i):Holding(str(i),'x',1200,20) for i in range(1,4)}
E['remove_uses_raw_delta']={'scale':1.2,'events':compute_events(pv,cu),'expected_adjusted_remove':-1200}
E['mixed_quote_dates']=quotes.merge_quotes(('2026-10-02',{'2330':100}),('2026-10-01',{'6488':50}),[])
E['actual_mixed_consensus']=[{'side':side,'stock':v['code'],'members':[(c,a['etfs'][c]['data_date']) for c in v['etfs']]} for side,ls in a['consensus'].items() for v in ls if len({a['etfs'][c]['data_date'] for c in v['etfs']})>1]
files=sorted((ROOT/'data/history').glob('*.json'));versions=collections.defaultdict(set);date_counts=collections.defaultdict(set);meta=0;units=0;no_quotes=0;cross_records=0;old_events=0;new_events=0
for f in files:
 d=json.loads(f.read_text())
 for c,r in d['etfs'].items():
  sig=tuple(sorted((h['code'],h['shares'],h['weight']) for h in r['holdings']))
  versions[c,r['data_date']].add(sig)
  if r['status']=='ok':date_counts[c].add(r['data_date'])
  meta+=bool(r.get('meta'));units+=bool(r.get('meta',{}).get('units'))
  for ev in r.get('events',[]):
   if ev['type'] in ('INCREASE','DECREASE'):
    if 'adjusted_shares_delta' in ev:new_events+=1
    else:old_events+=1
  if f.stem!=r['data_date'] and r.get('events'):cross_records+=1
E['history']={'file_count':len(files),'from':files[0].stem,'to':files[-1].stem,'meta_records':meta,'units_records':units,'incr_decr_with_adjusted':new_events,'incr_decr_without_adjusted':old_events,'event_records_differ_from_file_date':cross_records,'conflicting_same_etf_data_date':[(c,d,len(v)) for (c,d),v in versions.items() if len(v)>1],'distinct_ok_dates_per_etf':{c:len(s) for c,s in date_counts.items()}}
E['current_stale']=[{'etf':c,'date':e['data_date']} for c,e in a['etfs'].items() if e['status']=='stale']
b=copy.deepcopy(a);b['stocks']['2330']['name']='probe</script><div>MARKER</div>'
E['inline_json_not_script_safe']='probe</script><div>MARKER</div>' in render_html.render(b,reg)
E['current_html_matches_renderer']=(ROOT/'index.html').read_text()==render_html.render(a,reg)
print(json.dumps(E,ensure_ascii=False,indent=2))
