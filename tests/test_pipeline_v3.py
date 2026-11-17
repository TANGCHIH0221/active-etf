import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import outputs
import update_dashboard as ud
import quotes
import render_html
from adapters.base import Holding, validate_holdings, AdapterError
from diffengine import compute_events


def result(day='2026-10-02', shares=1000):
    return {'status': 'ok', 'data_date': day,
            'holdings': [Holding('2330', '台積電', shares, 60)],
            'meta': {'nav_per_unit': 10, 'units': 1000}, 'events': []}


def snapshot(day, shares=1000):
    r = result(day, shares)
    r['holdings'] = outputs.holdings_to_json(r['holdings'])
    return {'date': day, 'etfs': {'A': r}}


class PipelineRegressionTests(unittest.TestCase):
    def test_same_day_correction_can_revert_to_original_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for shares in (1000, 1200, 1000):
                doc = snapshot('2026-10-02', shares)
                dest = outputs.snapshot_destination(root, doc)
                self.assertIsNotNone(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(outputs.json_text(doc))
            latest = outputs.load_latest_snapshot(root)
            self.assertEqual(latest['etfs']['A']['holdings'][0]['shares'], 1000)
            self.assertIsNone(outputs.snapshot_destination(root, snapshot('2026-10-02', 1000)))
            self.assertEqual(len(list(outputs.iter_snapshots(root))), 3)

    def test_legacy_batch_dated_events_are_preserved_outside_verified_events(self):
        legacy = {'date': '2026-10-02', 'etf': 'A', 'code': '2330',
                  'type': 'INCREASE', 'close': 100, 'shares': 1200}
        original = {'events': [legacy], 'custom': 'preserve'}
        r = result('2026-10-01', 1200)
        r['events'] = [{'code': '2330', 'type': 'INCREASE',
                        'from_date': '2026-09-30', 'to_date': '2026-10-01'}]
        updated = outputs.build_perf_stats(original, '2026-10-02', {'A': r}, quotes.QuoteMap())
        self.assertEqual([e['date'] for e in updated['events']], ['2026-10-01'])
        self.assertEqual(updated['legacy_events'], [legacy])
        self.assertEqual(original, {'events': [legacy], 'custom': 'preserve'})
        self.assertEqual(updated['custom'], 'preserve')
        self.assertEqual(outputs.build_perf_stats(updated, '2026-10-02', {'A': r}, quotes.QuoteMap()), updated)

    def test_daily_estimates_require_same_scale_evidence_as_trends(self):
        for common_count, scale in ((1, 2), (3, 6), (3, 0.1)):
            with self.subTest(common_count=common_count, scale=scale):
                p = {str(i): Holding(str(i), 'X', 1000, 10) for i in range(common_count+1)}
                c = {str(i): Holding(str(i), 'X', int(1000*scale), 10) for i in range(common_count)}
                c['NEW'] = Holding('NEW', 'X', 1000, 10)
                events = compute_events(p,c)
                self.assertEqual({e['type'] for e in events}, {'ADD', 'REMOVE'})
                for e in events:
                    self.assertIsNone(e['adjusted_shares_delta'])
                    self.assertEqual(e['quality'], 'insufficient_scale')
                    self.assertIn('shares_delta', e)

    def test_batch_watermark_keeps_early_updated_etf_in_trends(self):
        import trends
        reg = {e: {'market': 'tw', 'status': 'active'} for e in ('A','B','C')}
        previous = {e: result('2026-10-01') for e in reg}
        current = {e: result('2026-10-01') for e in reg}
        current['A'] = result('2026-10-02')
        batch = ud.resolve_data_date(current)
        self.assertEqual(batch, '2026-10-02')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'2026-10-01.json').write_text(outputs.json_text(outputs.snapshot_document('2026-10-01', previous)))
            records, _, _, _, excluded = trends.canonical_history(root, reg,
                [('2026-10-02.json', outputs.snapshot_document(batch, current))])
            self.assertIn(('A', '2026-10-02'), records)
            self.assertEqual(excluded, [])

    def test_invalid_adapter_date_is_rejected(self):
        reg = {'A': {'market': 'tw', 'status': 'active', 'adapter': 'test'}}
        import contextlib, io
        out = io.StringIO()  # 吞掉預期中的錯誤訊息,別讓它混進 CI log 像真的失敗
        with patch.dict(ud.base.ADAPTERS, {'test': lambda _: ('2026-99-01', [], {})}), \
                contextlib.redirect_stdout(out):
            self.assertEqual(ud.fetch_all_holdings(reg), {})
        self.assertIn('無效資料日期', out.getvalue())

    def test_disabled_etf_is_not_published_or_fetched(self):
        reg = {'00996A': {'market': 'tw', 'status': 'disabled', 'adapter': 'megafunds'}}
        r = {'00996A': result()}
        active = outputs.build_active_json('2026-10-02', reg, r, {})
        self.assertEqual(active['etfs'], {})
        self.assertEqual(active['stocks'], {})
        with patch.dict(ud.base.ADAPTERS, {'megafunds': lambda _: self.fail('disabled ETF fetched')}):
            self.assertEqual(ud.fetch_all_holdings(reg), {})
        stale = {}
        ud.carry_stale(stale, reg, {'etfs': {'00996A': snapshot('2026-10-02')['etfs']['A']}})
        self.assertEqual(stale, {})

    def test_first_observation_not_a_purchase(self):
        r = {'NEW': result()}
        ud.compute_all_events(r, snapshot('2026-10-01'))
        self.assertEqual(r['NEW']['events'], [])

    def test_metadata_correction_changes_fingerprint(self):
        a = {'A': result()}; b = copy.deepcopy(a)
        b['A']['meta']['nav_per_unit'] = 11
        self.assertFalse(outputs.should_skip_results(b, outputs.results_fingerprint(a)))

    def test_latest_state_includes_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'2026-10-01.json').write_text(json.dumps(snapshot('2026-10-01')))
            (p/'2026-10-02.json').write_text(json.dumps(snapshot('2026-10-02', 2000)))
            latest = outputs.load_latest_snapshot(p)
            r = {'A': result('2026-10-01')}
            ud.reject_regressions(r, latest)
            self.assertEqual(r['A']['data_date'], '2026-10-02')
            self.assertEqual(r['A']['holdings'][0].shares, 2000)

    def test_event_keeps_true_interval(self):
        prev = snapshot('2026-09-30')
        r = {'A': result('2026-10-02')}
        r['A']['holdings'].append(Holding('2454', '聯發科', 100, 5))
        ud.compute_all_events(r, prev)
        self.assertEqual(r['A']['events'][0]['from_date'], '2026-09-30')
        self.assertEqual(r['A']['events'][0]['to_date'], '2026-10-02')

    def test_remove_uses_same_adjusted_formula(self):
        p = {str(i): Holding(str(i), 'X', 1000, 20) for i in range(4)}
        c = {str(i): Holding(str(i), 'X', 1200, 20) for i in range(1, 4)}
        ev = compute_events(p, c)[0]
        self.assertEqual(ev['shares_delta'], -1000)
        self.assertEqual(ev['adjusted_shares_delta'], -1200)

    def test_consensus_does_not_mix_intervals(self):
        reg = {c: {'market': 'tw'} for c in ('A','B')}
        res = {c: result() for c in reg}
        for c, start in [('A','2026-10-01'),('B','2026-09-30')]:
            res[c]['events'] = [{'code':'2330','name':'台積電','type':'INCREASE',
                                'adjusted_shares_delta':100,'from_date':start,'to_date':'2026-10-02'}]
        active = outputs.build_active_json('2026-10-02',reg,res,{})
        self.assertEqual(active['consensus']['increase'], [])

    def test_quote_dates_are_per_security(self):
        d, q, failed = quotes.merge_quotes(('2026-10-02',{'2330':100}),
                                           ('2026-10-01',{'6488':50}),[])
        self.assertEqual(q.dates['6488'], '2026-10-01')
        self.assertEqual(q.dates['2330'], '2026-10-02')

    def test_unknown_quote_date_cannot_compute_premium(self):
        f=ud.build_fundamentals({'A':result()}, {'A':11}, None)
        self.assertIsNone(f['A']['premium_pct'])

    def test_event_price_must_match_period_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = result('2026-10-01')
            r['events']=[{'code':'2330','type':'ADD','from_date':'2026-09-30','to_date':'2026-10-01'}]
            _, q, _ = quotes.merge_quotes(('2026-10-02',{'2330':100}),None,[])
            ev=outputs.append_events(Path(tmp)/'perf.json','2026-10-02',{'A':r},q)['events'][0]
            self.assertEqual(ev['date'],'2026-10-01')
            self.assertIsNone(ev['close'])

    def test_ui_version_changes_build_id(self):
        a={'updated':'2026-10-02'}
        before=render_html.build_id_of(a)
        with patch.object(render_html,'CSS',render_html.CSS+'body{color:red}'):
            self.assertNotEqual(before,render_html.build_id_of(a))

    def test_json_cannot_close_script_element(self):
        a={'updated':'2026-10-02','etfs':{},'stocks':{'X':{'name':'</script><div>bad</div>'}},
           'consensus':{'increase':[],'decrease':[]},'crosslinks':{}}
        html=render_html.render(a,{})
        self.assertNotIn('</script><div>bad</div>',html)

    def test_negative_weight_rejected(self):
        with self.assertRaises(AdapterError):
            validate_holdings([Holding('A','A',1,90),Holding('B','B',1,-1)],'ETF')

    def test_bundle_stage_failure_leaves_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);a=p/'a';a.write_text('old')
            with patch('pathlib.Path.write_text',side_effect=OSError('full')):
                with self.assertRaises(OSError):
                    outputs.write_bundle_atomic({a:'new',p/'b':'new'})
            self.assertEqual(a.read_text(),'old')
            self.assertFalse((p/'b').exists())

    def test_main_does_not_rollback_or_skip_quote_recovery(self):
        for fetched_day in ('2026-10-01','2026-10-02'):
            with self.subTest(day=fetched_day), tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);h=p/'data/history';h.mkdir(parents=True)
                (h/'2026-10-01.json').write_text(json.dumps(snapshot('2026-10-01')))
                (h/'2026-10-02.json').write_text(json.dumps(snapshot('2026-10-02',2000)))
                latest={'A':result('2026-10-02',2000)}
                outputs.update_last_counts('2026-10-02',{'A':1},p/'counts.json',outputs.results_fingerprint(latest))
                reg={'A':{'market':'tw','status':'active','name':'A','issuer':'test'}}
                from contextlib import ExitStack
                with ExitStack() as stack:
                    for k,v in {'HISTORY':h,'REGISTRY_PATH':p/'reg.json','LAST_COUNTS':p/'counts.json',
                                'PERF_STATS':p/'perf.json','ACTIVE_JSON':p/'active.json','INDEX_HTML':p/'index.html'}.items():
                        stack.enter_context(patch.object(ud,k,v))
                    stack.enter_context(patch.object(ud,'fetch_registry',return_value=reg))
                    stack.enter_context(patch.object(ud,'fetch_all_holdings',return_value={'A':result(fetched_day,2000)}))
                    stack.enter_context(patch.object(ud.quotes_mod,'fetch_all',return_value=('2026-10-02',{'A':11,'2330':100},[])))
                    stack.enter_context(patch.object(ud.crosslinks_mod,'fetch_crosslinks',return_value={'dispo':[],'notes':{}}))
                    stack.enter_context(patch.object(sys,'argv',['update']))
                    self.assertEqual(ud.main(),0)
                a=json.loads((p/'active.json').read_text())
                self.assertEqual(a['updated'],'2026-10-02')
                self.assertEqual(a['etfs']['A']['close'],11)
                self.assertEqual(a['etfs']['A']['holdings'][0]['shares'],2000)

    def test_only_adjacent_periods_enter_daily_consensus(self):
        reg={c:{'market':'tw'} for c in ('A','B')};res={c:result() for c in reg}
        for r in res.values():
            r['events']=[{'code':'2330','name':'台積電','type':'ADD','adjusted_shares_delta':100,
                          'from_date':'2026-09-29','to_date':'2026-10-02'}]
        self.assertEqual(outputs.build_active_json('2026-10-02',reg,res,{})['consensus']['increase'],[])

    def test_trend_controls_and_payload_in_render(self):
        a={'updated':'2026-10-02','etfs':{},'stocks':{},'crosslinks':{},'consensus':{'increase':[],'decrease':[]}}
        a['trend_build_id']='abc123'
        html=render_html.render(a,{})
        self.assertTrue('id="trendWindow"' in html)
        self.assertTrue('id="trendExport"' in html)
        # 趨勢資料另檔載入,不可再內嵌(曾讓 index.html 長到 12 MB)
        self.assertIn('window.TREND_URL = "data/stock_trends.json?v=abc123"', html)
        self.assertNotIn('window.TREND_DATA =', html)
