import sys
import tempfile
import json
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))


def holdings(q=1000):
    return [{'code':c,'name':c,'shares':n,'weight':20} for c,n in [('2330',q),('2317',1000),('2454',1000)]]


class TrendsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.reg={'A':{'market':'tw','status':'active'}}

    def put(self,day,hs=None,etf='A',status='ok',data_date=None):
        p=self.root/(day+'.json');doc=json.loads(p.read_text()) if p.exists() else {'date':day,'etfs':{}}
        doc['etfs'][etf]={'status':status,'data_date':data_date or day,'holdings':hs if hs is not None else holdings(),'meta':{},'events':[]}
        p.write_text(json.dumps(doc))

    def build(self):
        import trends
        return trends.build_trends(self.root,self.reg)

    def test_pure_proportional_flows_zero(self):
        self.put('2026-09-29');self.put('2026-09-30',[dict(h,shares=h['shares']*2) for h in holdings()])
        d=self.build();s=d['windows']['all']['stocks']['2330']
        self.assertEqual(s['net_delta'],0)
        self.assertEqual(s['raw_delta'],1000)

    def test_below_threshold_daily_changes_accumulate(self):
        for day,q in [('2026-09-29',1000),('2026-09-30',1020),('2026-10-01',1040),('2026-10-02',1060)]:self.put(day,holdings(q))
        s=self.build()['windows']['all']['stocks']['2330']
        self.assertEqual(s['net_delta'],60)
        self.assertEqual(s['increasing_etfs'],['A'])
        self.assertEqual(s['positive_days'],3)
        self.assertEqual(s['series'][-1]['cumulative'],60)

    def test_missing_day_not_zero_or_one_day_trade(self):
        self.put('2026-09-29');self.put('2026-10-01',holdings(1500))
        d=self.build()
        self.assertEqual(d['windows']['all']['cohort_etfs'],[])
        self.assertIsNone(d['windows']['all']['stocks']['2330']['net_delta'])
        self.assertTrue(any(i['quality']=='gap' for i in d['intervals']))

    def test_new_etf_is_not_purchase(self):
        self.put('2026-09-29');self.put('2026-09-30');self.put('2026-09-30',holdings(3000),'B')
        self.reg['B']={'market':'tw','status':'active'}
        d=self.build();self.assertEqual(d['windows']['all']['cohort_etfs'],['A'])
        self.assertEqual(d['windows']['all']['stocks']['2330']['net_delta'],0)

    def test_cleared_stock_remains_searchable(self):
        self.put('2026-09-29',holdings()+[{'code':'9999','name':'出清股','shares':100,'weight':1}])
        self.put('2026-09-30')
        d=self.build()
        self.assertEqual(d['stocks']['9999']['name'],'出清股')
        self.assertEqual(d['windows']['all']['stocks']['9999']['net_delta'],-100)
        self.assertEqual(d['windows']['all']['stocks']['9999']['series'][-1]['held_count'],0)

    def test_60_days_is_unavailable(self):
        self.put('2026-09-29');self.put('2026-09-30')
        w=self.build()['windows']['60']
        self.assertFalse(w['available']);self.assertEqual(w['reason'],'insufficient_history')

    def test_holidays_are_not_missing_sessions(self):
        self.put('2026-09-24');self.put('2026-09-29',holdings(1100))
        d=self.build();self.assertEqual(d['windows']['all']['cohort_etfs'],['A'])
        self.assertEqual(d['windows']['all']['stocks']['2330']['net_delta'],100)

    def test_revision_counts_once(self):
        self.put('2026-09-29');self.put('2026-09-30',holdings(1100))
        doc=json.loads((self.root/'2026-09-30.json').read_text());doc['revision']=1
        doc['etfs']['A']['holdings']=holdings(1200)
        (self.root/'revisions').mkdir();(self.root/'revisions'/'2026-09-30-0001.json').write_text(json.dumps(doc))
        d=self.build();self.assertEqual(d['windows']['all']['stocks']['2330']['net_delta'],200)
        self.assertEqual(len([i for i in d['intervals'] if i['stock']=='2330']),1)
        self.assertEqual(d['quality']['revision_conflicts'],1)

    def test_possible_stock_split_is_unknown(self):
        self.put('2026-09-29');self.put('2026-09-30',holdings(2000))
        d=self.build();s=d['windows']['all']['stocks']['2330']
        self.assertIsNone(s['net_delta'])
        self.assertEqual(s['excluded_etfs'],['A'])

    def test_stale_is_not_fresh_observation(self):
        self.put('2026-09-29');self.put('2026-09-30',status='stale',data_date='2026-09-29')
        d=self.build();self.assertEqual(d['windows']['all']['cohort_etfs'],[])

    def test_5_sessions_needs_6_endpoints(self):
        for day in ['2026-09-23','2026-09-24','2026-09-29','2026-09-30','2026-10-01','2026-10-02']:self.put(day)
        d=self.build();self.assertTrue(d['windows']['5']['available'])
        self.assertEqual(len(d['windows']['5']['dates']),5)

    def test_calendar_outside_coverage_is_not_trading_days(self):
        self.put('2027-01-04');self.put('2027-01-05')
        d=self.build();self.assertFalse(d['calendar']['verified'])
        self.assertEqual(d['calendar']['label'],'觀測日')

    def test_packed_intervals_roundtrip(self):
        import trends
        self.put('2026-09-29');self.put('2026-09-30',holdings(1050))
        raw=self.build();packed=trends.pack_trends(raw)
        self.assertEqual(trends.unpack_intervals(packed),raw['intervals'])

    def test_typhoon_closure_oct23_keeps_adjacent_trading_interval(self):
        from trading_calendar import adjacent
        self.assertTrue(adjacent('2026-10-22','2026-10-27'))
        self.put('2026-10-22');self.put('2026-10-27',holdings(1050))
        w=self.build()['windows']['all']
        self.assertEqual(w['cohort_etfs'],['A'])
        self.assertEqual(w['stocks']['2330']['net_delta'],50)
