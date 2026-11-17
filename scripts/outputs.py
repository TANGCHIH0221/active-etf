# -*- coding: utf-8 -*-
"""輸出層:每日快照(history)、防呆狀態(last_counts)、事件庫(perf_stats)、
active.json(下游 API)。所有檔案內容確定性——不含執行時間戳,同輸入同 bytes。
"""
import json
from trading_calendar import adjacent
from pathlib import Path


def _dump(obj, path):
    """原子寫入:先寫暫存檔再 rename。

    直接 write_text 若在中途失敗(磁碟滿、程序被砍),會留下半截的 JSON,
    下次讀取就整個炸掉——而這些是歷史快照與事件庫,壞了很難重建。
    """
    write_text_atomic(
        path, json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def write_text_atomic(path, text):
    """同目錄暫存檔 + os.replace(同檔案系統上為原子操作)。"""
    import os
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def write_bundle_atomic(files):
    """Stage and validate every output first; restore the previous bundle on replace failure.

    A crash between renames can leave a mixed bundle; inspect the last success marker
    and rebuild after recovery. Writers must be serialized with the CLI/workflow lock.
    """
    import os
    import tempfile
    staged, originals, replaced = {}, {}, []
    try:
        for raw, content in files.items():
            path = Path(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            originals[path] = path.read_bytes() if path.exists() else None
            fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=str(path.parent))
            os.close(fd)
            staged[path] = Path(name)
            staged[path].write_text(content, encoding='utf-8')
        for path, temp in staged.items():
            os.replace(str(temp), str(path))
            replaced.append(path)
    except BaseException:
        for path in reversed(replaced):
            if originals[path] is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(originals[path])
        raise
    finally:
        for temp in staged.values():
            temp.unlink(missing_ok=True)


def json_text(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True, allow_nan=False) + "\n"


def iter_snapshots(history_dir):
    root = Path(history_dir)
    paths = list(root.glob('*.json')) + list((root / 'revisions').glob('*.json'))
    docs = [(p, json.loads(p.read_text())) for p in paths]
    # Revisions have deterministic priority within a batch; revision number is monotone.
    return sorted(docs, key=lambda x: (x[1].get('date', ''), x[1].get('revision', 0), x[0].name))


def load_latest_snapshot(history_dir):
    etfs, watermark = {}, ''
    for path, doc in iter_snapshots(history_dir):
        watermark = max(watermark, doc.get('date', ''))
        for code, entry in doc.get('etfs', {}).items():
            if entry.get('holdings') and entry.get('data_date', '') >= etfs.get(code, {}).get('data_date', ''):
                etfs[code] = entry
    return {'date': watermark, 'etfs': etfs}


def load_baselines(history_dir, results):
    etfs = {}
    for path, doc in iter_snapshots(history_dir):
        for code, entry in doc.get('etfs', {}).items():
            day = entry.get('data_date') or ''
            current = results.get(code, {}).get('data_date') or ''
            if entry.get('holdings') and day < current and day >= (etfs.get(code, {}).get('data_date') or ''):
                etfs[code] = entry
    return {'etfs': etfs}


def snapshot_document(date, results):
    return {'date': date, 'etfs': {c: {
        'status': r['status'], 'data_date': r.get('data_date'),
        'holdings': holdings_to_json(r.get('holdings') or []),
        'events': r.get('events') or [], 'meta': r.get('meta') or {}}
        for c, r in sorted(results.items())}}


def snapshot_destination(history_dir, doc):
    """Never overwrite raw history: corrected same-day snapshots become new revisions."""
    root = Path(history_dir)
    existing = [d for _, d in iter_snapshots(root) if d.get('date') == doc['date']]
    plain = {k: v for k, v in doc.items() if k != 'revision'}
    if existing and {k: v for k, v in existing[-1].items() if k != 'revision'} == plain:
        return None
    if not existing:
        return root / (doc['date'] + '.json')
    doc['revision'] = max(d.get('revision', 0) for d in existing) + 1
    return root / 'revisions' / ('{}-{:04d}.json'.format(doc['date'], doc['revision']))


def holdings_to_json(holdings):
    return [{"code": h.code, "name": h.name, "shares": h.shares,
             "weight": h.weight} for h in holdings]


def write_snapshot(date, etf_results, history_dir):
    """etf_results: {code: {status, data_date, holdings(list of Holding), events, meta}}

    meta(規模/NAV/受益人數/nav_date)一定要一起存:抓取失敗時 carry_stale 會從
    快照沿用,沒存 meta 的話持股留得住、基本面卻整組消失(ETF 卡片的規模與折溢價
    會空掉,連排序都會跟著跳)。2026-09-08 的 26 份既有快照都沒有這個欄位,
    讀取端一律要能容忍缺漏。
    """
    history_dir = Path(history_dir)
    history_dir.mkdir(parents=True, exist_ok=True)
    doc = {"date": date, "etfs": {}}
    for code, r in sorted(etf_results.items()):
        doc["etfs"][code] = {
            "status": r["status"],
            "data_date": r.get("data_date"),
            "holdings": holdings_to_json(r.get("holdings") or []),
            "events": r.get("events") or [],
            "meta": r.get("meta") or {},
        }
    path = history_dir / "{}.json".format(date)
    _dump(doc, path)
    return path


def load_prev_snapshot(history_dir, before_date):
    """回傳 before_date(不含)之前最近一份快照 dict,無則 None。"""
    history_dir = Path(history_dir)
    if not history_dir.exists():
        return None
    candidates = sorted(p.stem for p in history_dir.glob("*.json")
                        if p.stem < before_date)
    if not candidates:
        return None
    return json.loads((history_dir / (candidates[-1] + ".json")).read_text())


def load_snapshot(history_dir, date):
    """讀取指定資料日的快照(同一日重跑時用來避免蓋掉先前抓到的較新資料)。"""
    p = Path(history_dir) / (date + ".json")
    return json.loads(p.read_text()) if p.exists() else None


def results_fingerprint(etf_results):
    """逐檔 {code: "data_date:狀態:持股雜湊"},作為「這批資料是否真的變了」的依據。

    只比全域資料日的眾數不夠:眾數不變但單檔前進、stale 恢復、或同日官方更正
    內容,都應該要更新。野村連續數日 stale 就是被眾數閘門擋住的
    (第一輪寫入當日日期後,18:00 補跑必定跳過)。
    """
    import hashlib
    out = {}
    for code, r in sorted((etf_results or {}).items()):
        rows = sorted((h.code, h.shares, round(h.weight, 4))
                      for h in (r.get("holdings") or []))
        digest = hashlib.sha256(json.dumps([rows, r.get("meta") or {}], sort_keys=True).encode("utf-8")).hexdigest()[:16]
        out[code] = "{}:{}:{}".format(r.get("data_date") or "", r.get("status") or "", digest)
    return out


def should_skip_results(etf_results, last_fingerprint):
    """逐檔指紋完全相同才跳過。任何一檔的日期/狀態/持股有變就要更新。"""
    if not last_fingerprint:
        return False
    return results_fingerprint(etf_results) == last_fingerprint


def should_skip(data_date, last_counts_path):
    """資料日 ≤ 上次已處理日 → True(呼叫端須 log「跳過更新」)。

    **已由 should_skip_results 取代為主要閘門**,保留供既有測試與回溯參考。
    """
    p = Path(last_counts_path)
    if not p.exists():
        return False
    last = json.loads(p.read_text()).get("data_date", "")
    return bool(data_date and last and data_date <= last)


def check_anomaly(counts, last_counts_path):
    """單檔持股檔數對上次驟降 >50% → 該檔列入異常名單。counts: {etf: n}"""
    p = Path(last_counts_path)
    if not p.exists():
        return []
    prev = json.loads(p.read_text()).get("counts", {})
    bad = []
    for etf, n in counts.items():
        pn = prev.get(etf)
        if pn and n < pn * 0.5:
            bad.append(etf)
    return bad


def update_last_counts(data_date, counts, last_counts_path, fingerprint=None):
    doc = {"data_date": data_date, "counts": counts}
    if fingerprint is not None:
        doc["fingerprint"] = fingerprint
    _dump(doc, last_counts_path)


def load_fingerprint(last_counts_path):
    p = Path(last_counts_path)
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("fingerprint")


def build_perf_stats(doc, date, etf_results, quotes):
    # Each successful ETF replaces its own actual period end, never a global batch date.
    authoritative = {(etf, r.get('data_date') or date) for etf, r in etf_results.items()
                     if r.get('status') == 'ok'}
    # Legacy events used a global batch date. Preserve them verbatim, but never
    # mix their unverified periods with versioned events or guess corrected dates.
    legacy = list(doc.get('legacy_events', []))
    verified = []
    for e in doc.get('events', []):
        if not e.get('observed_date') and not (e.get('from_date') and e.get('to_date')):
            legacy.append(e)
        else:
            verified.append(e)
    kept = [e for e in verified
            if (e.get('etf'), e.get('date')) not in authoritative]
    for etf, r in sorted(etf_results.items()):
        if r.get('status') != 'ok':
            continue
        for ev in r.get('events') or []:
            day = ev.get('to_date') or date
            qd = getattr(quotes, 'dates', {}).get(ev['code'], date if not hasattr(quotes, 'dates') else None)
            kept.append({**ev, 'date': day, 'etf': etf,
                         'quote_date': qd, 'observed_date': date,
                         'close': quotes.get(ev['code']) if qd == day else None})
    kept.sort(key=lambda e: (e.get('date') or '', e.get('etf') or '',
                             e.get('code') or '', e.get('type') or ''))
    return {**doc, 'schema_version': 3, 'events': kept, 'legacy_events': legacy,
            'legacy_event_policy': 'Unverified batch-dated events archived verbatim; excluded from period-based analytics.'}


def append_events(perf_stats_path, date, etf_results, quotes):
    p = Path(perf_stats_path)
    doc = json.loads(p.read_text()) if p.exists() else {'events': []}
    updated = build_perf_stats(doc, date, etf_results, quotes)
    _dump(updated, p)
    return updated


def build_active_json(date, registry, etf_results, fundamentals, crosslinks=None,
                      quotes=None):
    """下游 API 主檔。schema 見 README。"""
    crosslinks = crosslinks or {}
    quotes = quotes or {}
    etfs, stocks, cons_inc, cons_dec = {}, {}, {}, {}
    for code, reg in sorted(registry.items()):
        if reg.get("market") != "tw" or reg.get("status") == "disabled":
            continue
        r = etf_results.get(code)
        f = (fundamentals or {}).get(code) or {}
        entry = {
            "name": reg.get("name"), "issuer": reg.get("issuer"),
            "status": (r or {}).get("status", reg.get("status", "unsupported")),
            "data_date": (r or {}).get("data_date"),
            "scale": f.get("scale"), "holders": f.get("holders"),
            "nav": f.get("nav_per_unit"), "close": f.get("close"),
            "premium_pct": f.get("premium_pct"),
            # 折溢價只在 NAV 日 == 收盤價日時才有值;不一致時 premium_note 說明原因
            "nav_date": f.get("nav_date"), "quote_date": f.get("quote_date"),
            "premium_note": f.get("premium_note"),
            "holdings": holdings_to_json((r or {}).get("holdings") or []),
            "events": (r or {}).get("events") or [],
        }
        etfs[code] = entry
        for h in entry["holdings"]:
            s = stocks.setdefault(h["code"], {
                "name": h["name"], "total_weight": 0.0, "total_shares": 0,
                "etfs": [], "recent_events": []})
            # total_weight 是各檔權重「相加」,跨基金相加無量綱意義,只當熱度指標;
            # 要比較個股被主動式 ETF 持有的實際規模請用 total_value(股數×收盤價)。
            s["total_weight"] = round(s["total_weight"] + h["weight"], 4)
            s["total_shares"] += h["shares"]
            s["etfs"].append({"etf": code, "weight": h["weight"],
                              "shares": h["shares"]})
        for ev in entry["events"]:
            s = stocks.setdefault(ev["code"], {
                "name": ev["name"], "total_weight": 0.0, "total_shares": 0,
                "etfs": [], "recent_events": []})
            s["recent_events"].append({"etf": code, "type": ev["type"],
                                       "date": ev.get("to_date") or entry.get("data_date") or date,
                                       "from_date": ev.get("from_date"),
                                       "to_date": ev.get("to_date") or entry.get("data_date") or date})
            # 累加成該股的「主動調整估算股數」。用校正後的 adjusted_shares_delta,
            # 不用原始 shares_delta——後者含申購贖回造成的等比例增減,大額申購日
            # 會與事件方向相反(INCREASE 卻是負張數)。沒有校正值時退回原始值。
            if (ev.get("to_date") or entry.get("data_date") or date) != date:
                continue
            if ev.get("from_date") and not adjacent(ev["from_date"], ev.get("to_date") or date):
                continue
            delta = ev.get("adjusted_shares_delta")
            if delta is None and "adjusted_shares_delta" in ev:
                continue
            if delta is None:
                delta = ev.get("shares_delta") or 0
            group = (ev["code"], ev.get("from_date"), ev.get("to_date") or date)
            if ev["type"] in ("INCREASE", "ADD"):
                c = cons_inc.setdefault(group, {"name": ev["name"], "etfs": [],
                                                     "shares_delta": 0})
                c["etfs"].append(code)
                c["shares_delta"] += delta
            elif ev["type"] in ("DECREASE", "REMOVE"):
                c = cons_dec.setdefault(group, {"name": ev["name"], "etfs": [],
                                                     "shares_delta": 0})
                c["etfs"].append(code)
                c["shares_delta"] += delta
    for scode, s_ in stocks.items():
        px = quotes.get(scode)
        s_["close"] = px
        s_["quote_date"] = getattr(quotes, "dates", {}).get(scode)
        s_["total_value"] = round(s_["total_shares"] * px) if px and (not hasattr(quotes, "dates") or quotes.dates.get(scode)) else None
        s_["etf_count"] = len(s_["etfs"])
    consensus = {
        "increase": [{"code": c[0], "from_date": c[1], "to_date": c[2], **v} for c, v in sorted(cons_inc.items(), key=lambda x: str(x[0]))
                     if len(v["etfs"]) >= 2],
        "decrease": [{"code": c[0], "from_date": c[1], "to_date": c[2], **v} for c, v in sorted(cons_dec.items(), key=lambda x: str(x[0]))
                     if len(v["etfs"]) >= 2],
    }
    return {"updated": date, "etfs": etfs, "stocks": stocks,
            "consensus": consensus, "crosslinks": crosslinks}


from contextlib import contextmanager


@contextmanager
def project_lock(root):
    """Serialize local writers; workflow concurrency serializes hosted writers."""
    import fcntl
    path = Path(root) / '.update.lock'
    with path.open('a') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('已有更新／重建程序執行中，請待完成後重試。')
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
