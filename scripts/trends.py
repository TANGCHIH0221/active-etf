"""Rebuildable, threshold-free ETF holdings intervals. Never alters source snapshots.

All net figures describe endpoint holdings adjustments, not executed purchases.
A fixed window cohort avoids adding/removing stale funds from a running total.
"""
import statistics
from collections import defaultdict

from outputs import iter_snapshots
from trading_calendar import load_calendar, sessions, valid_date

VERSION = 'median-v1'
from diffengine import valid_scale


def _signature(entry):
    return tuple(sorted((h['code'], h['shares'], h['weight']) for h in entry['holdings']))


def canonical_history(history_dir, registry, extra_docs=()):
    """Last observed revision wins; retain source references and known legacy exclusions."""
    records, names, conflicts, excluded = {}, {}, [], []
    docs = [(str(p.relative_to(history_dir)), d) for p, d in iter_snapshots(history_dir)]
    docs += list(extra_docs)
    docs.sort(key=lambda x: (x[1].get('date', ''), x[1].get('revision', 0), x[0]))
    batches = []
    for source, doc in docs:
        observed = doc.get('date')
        if not valid_date(observed):
            continue
        batches.append(observed)
        for etf, entry in doc.get('etfs', {}).items():
            reg = registry.get(etf, {})
            if reg.get('market') != 'tw' or reg.get('status') in ('disabled', 'unsupported'):
                continue
            for h in entry.get('holdings', []):
                names[h['code']] = {'name': h['name']}
            day = entry.get('data_date')
            reason = None
            if not valid_date(day):
                reason = 'invalid_date'
            elif day > observed:
                reason = 'future_label'
            elif etf == '00987A' and observed < '2026-09-10':
                reason = 'legacy_publication_date'
            if reason:
                excluded.append({'etf': etf, 'source': source, 'date': day, 'reason': reason})
                continue
            if entry.get('status') != 'ok' or not entry.get('holdings'):
                continue
            hs = entry['holdings']
            # Old unvalidated data must not silently become a trusted interval.
            if len({h['code'] for h in hs}) != len(hs) or any(h['shares'] < 0 or h['weight'] < 0 for h in hs):
                excluded.append({'etf': etf, 'source': source, 'date': day, 'reason': 'invalid_holdings'})
                continue
            key = (etf, day)
            old = records.get(key)
            if old and _signature(old['entry']) != _signature(entry):
                conflicts.append({'etf': etf, 'date': day, 'superseded': old['source'], 'selected': source})
            records[key] = {'entry': entry, 'source': source, 'observed': observed,
                            'revision': doc.get('revision', 0)}
    return records, names, batches, conflicts, excluded


def interval_rows(etf, first, last, calendar, verified):
    p, c = first['entry'], last['entry']
    d0, d1 = p['data_date'], c['data_date']
    prev = {h['code']: h for h in p['holdings']}
    curr = {h['code']: h for h in c['holdings']}
    common = [k for k in prev.keys() & curr.keys() if prev[k]['shares'] > 0 and curr[k]['shares'] > 0]
    scale = statistics.median(curr[k]['shares'] / prev[k]['shares'] for k in common) if common else None
    span = sessions(d0, d1, calendar)
    quality = 'ok'
    if not verified or span != [d0, d1]:
        quality = 'gap' if verified else 'calendar_unverified'
    if not valid_scale(scale, len(common)):
        quality = 'insufficient_scale'
    rows = []
    for stock in sorted(prev.keys() | curr.keys()):
        before, after = prev.get(stock), curr.get(stock)
        q0, q1 = (before or {}).get('shares', 0), (after or {}).get('shares', 0)
        status = quality
        # Conservative corporate-action flag: an individual near-integer share change,
        # unlike the portfolio scale, with nearly unchanged weight. This is NOT a
        # corporate-action adjustment feed: ambiguous rows remain unknown.
        if quality == 'ok' and q0 and q1 and before and after:
            ratio = q1 / q0 / scale
            action_ratio = any(abs(ratio - r) < 0.015 for r in (0.1, 0.2, 0.25, 1/3, 0.5, 2, 3, 4, 5, 10))
            if action_ratio and abs(after['weight'] - before['weight']) <= max(0.1, before['weight'] * 0.03):
                status = 'possible_corporate_action'
        adjusted = round(q1 - q0 * scale, 6) if status == 'ok' else None
        rows.append({'etf': etf, 'stock': stock, 'from_date': d0, 'to_date': d1,
            'observed_date': last['observed'], 'previous_shares': q0, 'current_shares': q1,
            'raw_delta': q1-q0, 'adjusted_delta': adjusted,
            'scale': round(scale, 10) if scale else None, 'common_holdings_count': len(common),
            'method': VERSION, 'calculation_version': 1, 'quality': status,
            'source_snapshot_refs': [first['source'], last['source']],
            'source_revision': last['revision']})
    return rows


def _aggregate(stock, cohort, dates, records, intervals_by_pair):
    """Keep a stock-specific fixed subset when an action/quality issue affects it."""
    eligible, excluded = [], []
    for etf in cohort:
        good = True
        for d0, d1 in zip(dates, dates[1:]):
            row = intervals_by_pair[(etf, d0, d1)].get(stock)
            if row and row['adjusted_delta'] is None:
                good = False
        (eligible if good else excluded).append(etf)
    series, running, positive, negative = [], 0.0, 0.0, 0.0
    by_etf = {e: {'etf': e, 'raw_delta': 0, 'adjusted_delta': 0.0, 'positive_delta': 0.0,
                 'negative_delta': 0.0, 'previous_shares': 0, 'current_shares': 0} for e in eligible}
    maps = {(e, d): {h['code']: h for h in records[(e, d)]['entry']['holdings']} for e in eligible for d in dates}
    for etf in eligible:
        by_etf[etf]['previous_shares'] = maps[(etf, dates[0])].get(stock, {}).get('shares', 0)
        by_etf[etf]['current_shares'] = maps[(etf, dates[-1])].get(stock, {}).get('shares', 0)
    for d0, d1 in zip(dates, dates[1:]):
        delta, raw, up, down, held, total = 0.0, 0, 0, 0, 0, 0
        for etf in eligible:
            row = intervals_by_pair[(etf, d0, d1)].get(stock)
            value = row['adjusted_delta'] if row else 0
            raw_value = row['raw_delta'] if row else 0
            delta += value; raw += raw_value
            up += value > 0.000001; down += value < -0.000001
            shares = maps[(etf, d1)].get(stock, {}).get('shares', 0)
            total += shares; held += shares > 0
            positive += max(value, 0); negative += min(value, 0)
            item = by_etf[etf]
            item['raw_delta'] += raw_value; item['adjusted_delta'] += value
            item['positive_delta'] += max(value, 0); item['negative_delta'] += min(value, 0)
        running += delta
        series.append({'date': d1, 'net_delta': round(delta, 6) if eligible else None,
            'raw_delta': raw if eligible else None, 'cumulative': round(running, 6) if eligible else None,
            'total_shares': total if eligible else None, 'held_count': held if eligible else None,
            'increasing_count': up, 'decreasing_count': down})
    contributions = []
    for row in by_etf.values():
        for key in ('adjusted_delta', 'positive_delta', 'negative_delta'):
            row[key] = round(row[key], 6)
        if row['previous_shares'] or row['current_shares'] or row['positive_delta'] or row['negative_delta']:
            contributions.append(row)
    return {'cohort_etfs': eligible, 'excluded_etfs': excluded, 'series': series,
        'net_delta': round(running, 6) if eligible else None,
        'raw_delta': sum(r['raw_delta'] for r in contributions) if eligible else None,
        'positive_delta': round(positive, 6) if eligible else None,
        'negative_delta': round(negative, 6) if eligible else None,
        'positive_days': sum((r['net_delta'] or 0) > 0.000001 for r in series),
        'negative_days': sum((r['net_delta'] or 0) < -0.000001 for r in series),
        'increasing_etfs': [r['etf'] for r in contributions if r['adjusted_delta'] > 0.000001],
        'decreasing_etfs': [r['etf'] for r in contributions if r['adjusted_delta'] < -0.000001],
        'contributions': contributions}


def build_trends(history_dir, registry, calendar=None, extra_docs=()):
    calendar = calendar or load_calendar()
    records, stocks, batches, conflicts, excluded = canonical_history(history_dir, registry, extra_docs)
    if not batches:
        return {'schema_version': 1, 'stocks': {}, 'windows': {}, 'intervals': [], 'quality': {}, 'calendar': {}}
    start, end = min(batches), max(batches)
    expected = sessions(start, end, calendar)
    verified = expected is not None
    dates = expected if verified else sorted(set(batches))
    etfs = sorted({c for c, reg in registry.items() if reg.get('market') == 'tw'
                   and reg.get('status') not in ('disabled', 'unsupported')})
    by_etf = defaultdict(list)
    for (etf, day), entry in sorted(records.items()):
        by_etf[etf].append(entry)
    intervals = []
    for etf, entries in by_etf.items():
        for first, last in zip(entries, entries[1:]):
            intervals.extend(interval_rows(etf, first, last, calendar, verified))
    pairs = defaultdict(dict)
    for row in intervals:
        pairs[(row['etf'], row['from_date'], row['to_date'])][row['stock']] = row
    windows = {}
    for key in ('5', '20', '60', 'all'):
        n = len(dates)-1 if key == 'all' else int(key)
        if n < 1 or len(dates) < n+1:
            windows[key] = {'available': False, 'reason': 'insufficient_history', 'available_sessions': max(len(dates)-1, 0)}
            continue
        ds = dates[-n-1:]
        cohort = []
        exclusions = []
        for etf in etfs:
            missing = [d for d in ds if (etf, d) not in records]
            insufficient = any(any(r['quality'] in ('gap','insufficient_scale','calendar_unverified')
                                   for r in pairs[(etf,d0,d1)].values()) or not pairs[(etf,d0,d1)]
                               for d0,d1 in zip(ds,ds[1:])) if not missing else False
            if missing or insufficient or not verified:
                exclusions.append({'etf': etf, 'reason': 'missing_sessions' if missing else 'unverified_interval', 'missing_dates': missing})
            else:
                cohort.append(etf)
        aggregates = {stock: _aggregate(stock, cohort, ds, records, pairs) for stock in sorted(stocks)}
        windows[key] = {'available': True, 'from_date': ds[0], 'to_date': ds[-1], 'dates': ds[1:],
            'cohort_etfs': cohort, 'expected_etf_count': len(etfs), 'excluded_etfs': exclusions,
            'stocks': aggregates}
    return {'schema_version': 1, 'method': VERSION, 'updated': end, 'history_start': start,
        'stocks': stocks, 'windows': windows, 'intervals': intervals,
        'calendar': {'verified': verified, 'label': '交易日' if verified else '觀測日',
                     'source': calendar.get('source'), 'coverage_end': calendar.get('coverage_end')},
        'quality': {'snapshot_count': len(set(batches)), 'revision_conflicts': len(conflicts),
                    'revisions': conflicts, 'excluded_snapshots': excluded,
                    'limitations': ['持股調整估算，非實際成交；公司行動僅有保守異常篩檢，未接完整調整資料。',
                                    '固定樣本只包含視窗內完整資料；缺漏或疑似公司行動另行排除，不補零。']}}


INTERVAL_FIELDS = ['etf','stock','from_date','to_date','observed_date','previous_shares',
                   'current_shares','raw_delta','adjusted_delta','scale','common_holdings_count',
                   'quality','source_snapshot_refs','source_revision']
STRING_FIELDS = {'etf','stock','from_date','to_date','observed_date','quality'}


def pack_trends(data):
    """Lossless dictionary encoding keeps complete CSV evidence in a standalone page."""
    import copy
    result = copy.deepcopy({k:v for k,v in data.items() if k != 'intervals'})
    strings, ids = [], {}
    def intern(value):
        if value not in ids:
            ids[value] = len(strings); strings.append(value)
        return ids[value]
    rows = []
    for item in data['intervals']:
        row = []
        for key in INTERVAL_FIELDS:
            value = item[key]
            if key in STRING_FIELDS:
                value = intern(value)
            elif key == 'source_snapshot_refs':
                value = [intern(x) for x in value]
            row.append(value)
        rows.append(row)
    result['interval_table'] = {'fields': INTERVAL_FIELDS, 'strings': strings, 'rows': rows}
    return result


def unpack_intervals(data):
    table = data['interval_table'];out = []
    for row in table['rows']:
        item = {}
        for key, value in zip(table['fields'], row):
            if key in STRING_FIELDS:
                value = table['strings'][value]
            elif key == 'source_snapshot_refs':
                value = [table['strings'][x] for x in value]
            item[key] = value
        item.update(method=VERSION, calculation_version=1)
        out.append(item)
    return out
