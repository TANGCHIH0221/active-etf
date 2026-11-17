#!/usr/bin/env python3
"""Deterministic offline rebuild. Keeps raw history, registry and perf_stats untouched."""
import argparse
import hashlib
import json
from pathlib import Path

import outputs
import quotes
import render_html
import trends
import update_dashboard as ud
from adapters.base import Holding

ROOT = Path(__file__).resolve().parents[1]


def derived_outputs(root, active, registry, extra_docs=()):
    raw = trends.build_trends(root / 'data/history', registry, extra_docs=extra_docs)
    packed = trends.pack_trends(raw)
    text = json.dumps(packed, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + '\n'
    active['trend_build_id'] = hashlib.sha256(text.encode()).hexdigest()[:16]
    active['schema_version'] = 3
    active['build_id'] = render_html.build_id_of(active)
    html = render_html.render(active, registry)
    return raw, text, html


def rebuild(root=ROOT):
    root = Path(root)
    reg = json.loads((root / 'data/etf_registry.json').read_text())
    old = json.loads((root / 'active.json').read_text())
    latest = outputs.load_latest_snapshot(root / 'data/history')
    results = {}
    for code, entry in latest['etfs'].items():
        if reg.get(code, {}).get('market') != 'tw' or reg.get(code, {}).get('status') == 'disabled':
            continue
        results[code] = {**entry, 'holdings': [Holding(**h) for h in entry['holdings']]}
    ud.compute_all_events(results, outputs.load_baselines(root / 'data/history', results))
    px, dates = {}, {}
    for entries in (old.get('stocks', {}), old.get('etfs', {})):
        for code, entry in entries.items():
            if entry.get('close') is not None:
                px[code] = entry['close']
                dates[code] = entry.get('quote_date')  # Never invent a legacy quote date.
    qm = quotes.QuoteMap(px, dates)
    fundamental = ud.build_fundamentals(results, qm)
    active = outputs.build_active_json(latest['date'], reg, results, fundamental,
                                       old.get('crosslinks', {}), qm)
    active['quote_failures'] = old.get('quote_failures', [])
    raw, text, html = derived_outputs(root, active, reg)
    audit = {'source_head': '0b9643d', 'method': trends.VERSION,
             'updated': active['updated'], 'quality': raw['quality'],
             'windows': {k: {field: v for field,v in w.items() if field != 'stocks'} for k,w in raw['windows'].items()},
             'history_sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p,_ in outputs.iter_snapshots(root/'data/history')},
             'current_events': sum(len(e['events']) for e in active['etfs'].values()),
             'legacy_stock_prices_without_dates': sorted(c for c in old.get('stocks', {}) if px.get(c) is not None and not dates.get(c)),
             'notes': ['No raw history/perf_stats/registry modified.',
                       'Calendar is TWSE scheduled sessions; exceptional closures require an explicit update.',
                       'Legacy missing quote dates remain unknown; no historical amounts fabricated.']}
    outputs.write_bundle_atomic({root/'data/stock_trends.json': text,
        root/'active.json': outputs.json_text(active), root/'index.html': html,
        root/'docs/reviews/2026-10-03-migration.json': outputs.json_text(audit)})
    return audit


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=ROOT)
    args = ap.parse_args()
    with outputs.project_lock(args.root):
        audit = rebuild(args.root)
    print('離線重建完成；保留原始歷史。資料日 {}，當期事件 {} 筆。'.format(audit['updated'],audit['current_events']))
