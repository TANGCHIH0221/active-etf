import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from test_pipeline_v3 import snapshot


class OfflineBuildTests(unittest.TestCase):
    def test_offline_build_preserves_sources_and_is_deterministic(self):
        build=importlib.import_module('build_local')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);history=root/'data/history';history.mkdir(parents=True)
            for day in ['2026-10-01','2026-10-02']:
                (history/(day+'.json')).write_text(json.dumps(snapshot(day)))
            registry=root/'data/etf_registry.json';registry.write_text(json.dumps({'A':{'market':'tw','status':'active','name':'A'}}))
            perf=root/'data/perf_stats.json';perf.write_text('{"events":[]}')
            (root/'active.json').write_text(json.dumps({'updated':'2026-10-02','etfs':{'A':{'close':11,'quote_date':'2026-10-02'}},'stocks':{},'crosslinks':{}}))
            before={p:p.read_bytes() for p in [*history.glob('*.json'),registry,perf]}
            build.rebuild(root)
            one=(root/'index.html').read_bytes();data=(root/'data/stock_trends.json').read_bytes()
            build.rebuild(root)
            self.assertEqual(one,(root/'index.html').read_bytes())
            self.assertEqual(data,(root/'data/stock_trends.json').read_bytes())
            self.assertEqual(before,{p:p.read_bytes() for p in before})
            a=json.loads((root/'active.json').read_text())
            self.assertEqual(a['schema_version'],3)
            self.assertEqual(a['etfs']['A']['premium_pct'],10)
            self.assertIn('trend_build_id',a)
