#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主動式 ETF 買賣日曆:從 data/history/ 快照算每檔 ETF 每天的主動調整,
輸出手機看的 calendar/index.html 與給 Telegram 用的 calendar/summary.json。

主動量 adj = 今日股數 − 昨日股數 × scale,scale = median(今日股數/昨日股數)
(申贖倍率,同上游 diffengine 與 tg_report.py)。
訊號:|adj| ≥ 1000 股 且(|adj/昨日股數| ≥ 2% 或 新建倉 / 清倉)
—— 與研究端 quant/research/active_etf_daytrade/02_continuation.py 相同。
金額 = adj × 估計股價;股價 = 權重 × 淨資產 / 股數,取當天持有該股權重最大的
那檔 ETF 推回(權重只有兩位小數,權重越大誤差越小)。

連續天數只在「相鄰交易日」都同方向有訊號時累加;某檔 ETF 缺一天資料就斷。
「歷史續買率」= 在全部歷史裡,同方向已連 k 天的訊號,下一個交易日繼續同方向的比例。
"""
import glob
import json
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
INFO_PATH = HERE / "stock_info.json"
INFO_MAX_AGE_DAYS = 7
WINDOW = 30            # 日曆顯示最近幾個交易日
MIN_LOTS = 1000        # 訊號門檻:至少 1 張
MIN_PCT = 0.02         # 訊號門檻:調整 ≥ 昨日持股 2%
TOP_RUNS = 10          # summary.json 給 TG 的筆數
STALE_DAYS = 3         # ETF 最新資料日落後全體最新超過幾個交易日 → 不算「進行中」
# FinMind 同一代號常同時有大類與細類兩列(如 半導體業 + 電子工業),大類只在沒有細類時才用
GENERIC_IND = {"電子工業", "化學生技醫療", "觀光餐旅", "貿易百貨", "其他"}
PAGES_URL = "https://tangchih0221.github.io/active-etf/calendar/"
TPE = timezone(timedelta(hours=8))


# ------------------------------------------------------------------ 產業 / 市場

def load_stock_info():
    """FinMind TaiwanStockInfo(免費),快取 7 天;抓不到就用舊快取,不讓整支掛掉。"""
    cache = None
    if INFO_PATH.exists():
        cache = json.loads(INFO_PATH.read_text(encoding="utf-8"))
        age = time.time() - cache.get("fetched_ts", 0)
        if age < INFO_MAX_AGE_DAYS * 86400:
            return cache["stocks"]
    try:
        import requests
        r = requests.get("https://api.finmindtrade.com/api/v4/data",
                         params={"dataset": "TaiwanStockInfo"}, timeout=60)
        rows = r.json()["data"]
        stocks = {}
        # 同一代號可能有多列(大類/細類、改名),先比「是不是細類」再比日期
        for x in sorted(rows, key=lambda x: (x["industry_category"] not in GENERIC_IND,
                                             x.get("date") or "")):
            stocks[x["stock_id"]] = {"ind": x["industry_category"], "mkt": x["type"],
                                     "name": x["stock_name"]}
        INFO_PATH.write_text(json.dumps({"fetched_ts": time.time(), "stocks": stocks},
                                        ensure_ascii=False), encoding="utf-8")
        return stocks
    except Exception as e:  # noqa: BLE001 —— 產業只是分組用,失敗退回快取
        print("[warn] TaiwanStockInfo 抓取失敗: %r" % e, file=sys.stderr)
        return cache["stocks"] if cache else {}


# ------------------------------------------------------------------ 資料層

def load_snapshots():
    snaps = defaultdict(dict)   # etf -> data_date -> {"h": {code: (shares, weight)}, "aum": float}
    names = {}                  # code -> 股票名稱(以最新快照為準)
    for f in sorted(glob.glob(str(ROOT / "data" / "history" / "*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for etf, e in d["etfs"].items():
            if e.get("status") != "ok" or not e.get("holdings"):
                continue
            h = {}
            for x in e["holdings"]:
                h[x["code"]] = (x["shares"], x.get("weight"))
                names[x["code"]] = x.get("name") or x["code"]
            snaps[etf][e["data_date"]] = {"h": h, "aum": (e.get("meta") or {}).get("scale")}
    return snaps, names


def price_map(snaps):
    """(資料日, 股票) -> 估計股價,用當天權重最大的 ETF 推回。"""
    best = {}
    for etf, by_d in snaps.items():
        for dd, s in by_d.items():
            if not s["aum"]:
                continue
            for c, (sh, w) in s["h"].items():
                if sh and w:
                    k = (dd, c)
                    if k not in best or w > best[k][0]:
                        best[k] = (w, w / 100 * s["aum"] / sh)
    return {k: v[1] for k, v in best.items()}


def build_signals(snaps, days):
    idx = {d: i for i, d in enumerate(days)}
    px = price_map(snaps)
    out = []   # 每筆 = 某 ETF 某資料日某股票有訊號(sig ≠ 0)或是持有中無訊號(sig = 0)
    for etf, by_d in snaps.items():
        ds = sorted(by_d)
        for i in range(1, len(ds)):
            d0, d1 = ds[i - 1], ds[i]
            h0, h1 = by_d[d0]["h"], by_d[d1]["h"]
            common = [c for c in h1 if c in h0 and h0[c][0] > 0 and h1[c][0] > 0]
            scale = statistics.median(h1[c][0] / h0[c][0] for c in common) if common else 1.0
            consec = idx[d1] - idx[d0] == 1
            for c in set(h0) | set(h1):
                s0 = h0.get(c, (0, None))[0]
                s1 = h1.get(c, (0, None))[0]
                adj = s1 - s0 * scale
                kind = "entry" if s0 == 0 else "exit" if s1 == 0 else "adj"
                big = abs(adj) >= MIN_LOTS and (kind != "adj" or abs(adj) / s0 >= MIN_PCT)
                p = px.get((d1, c)) or px.get((d0, c))
                out.append({"etf": etf, "date": d1, "code": c, "consec": consec,
                            "sig": (1 if adj > 0 else -1) if big else 0, "kind": kind,
                            "adj": adj, "amt": adj * p if (big and p) else None})
    return out


def add_runs(rows, key):
    """依 key 分組、時間排序,算每筆訊號已經同方向連續第幾天(run)。"""
    g = defaultdict(list)
    for r in rows:
        g[key(r)].append(r)
    for rs in g.values():
        rs.sort(key=lambda r: r["date"])
        prev = None
        for r in rs:
            if r["sig"] != 0 and prev is not None and r["consec"] and prev["sig"] == r["sig"]:
                r["run"] = prev["run"] + 1
                r["run_amt"] = (prev["run_amt"] or 0) + (r["amt"] or 0)
                r["run_start"] = prev["run_start"]
            elif r["sig"] != 0:
                r["run"], r["run_amt"], r["run_start"] = 1, r["amt"] or 0, r["date"]
            else:
                r["run"], r["run_amt"], r["run_start"] = 0, 0, None
            prev = r
    return g


def continuation_stats(groups):
    """{方向: {k: [續, 總]}}:已連 k 天(4 代表 ≥4)後,下一個相鄰交易日同方向的次數。"""
    st = {"1": defaultdict(lambda: [0, 0]), "-1": defaultdict(lambda: [0, 0])}
    for rs in groups.values():
        for a, b in zip(rs, rs[1:]):
            if a["sig"] == 0 or a.get("kind") == "exit" or not b["consec"]:
                continue
            k = min(a["run"], 4)
            st[str(a["sig"])][k][1] += 1
            st[str(a["sig"])][k][0] += b["sig"] == a["sig"]
    return {d: {str(k): v for k, v in sorted(m.items())} for d, m in st.items()}


def stock_level(rows, days):
    """合併所有主動 ETF:每天每股淨金額。沒有任何 ETF 有訊號 → 不列。"""
    agg = {}
    for r in rows:
        if r["sig"] == 0:
            continue
        k = (r["date"], r["code"])
        a = agg.setdefault(k, {"date": r["date"], "code": r["code"], "amt": 0.0,
                               "nb": 0, "ns": 0, "consec": True, "kind": "adj"})
        a["amt"] += r["amt"] or 0
        a["nb" if r["sig"] > 0 else "ns"] += 1
    # 補齊每檔股票在每個交易日的列(無訊號 = 0),連續天數才算得對
    codes = {c for _, c in agg}
    out = []
    for c in codes:
        for d in days:
            a = agg.get((d, c))
            if a:
                a["sig"] = 1 if a["amt"] > 0 else -1 if a["amt"] < 0 else 0
                out.append(a)
            else:
                out.append({"date": d, "code": c, "amt": 0.0, "nb": 0, "ns": 0,
                            "consec": True, "kind": "adj", "sig": 0})
    return out


# ------------------------------------------------------------------ 主流程

def main():
    snaps, names = load_snapshots()
    days = sorted({dd for by_d in snaps.values() for dd in by_d})
    if len(days) < 2:
        print("[error] 快照不足兩天", file=sys.stderr)
        return 1
    info = load_stock_info()
    active = json.loads((ROOT / "active.json").read_text(encoding="utf-8"))
    etf_meta = {k: {"name": v.get("name") or k, "issuer": v.get("issuer") or ""}
                for k, v in (active.get("etfs") or {}).items()}

    rows = build_signals(snaps, days)
    g_etf = add_runs(rows, key=lambda r: (r["etf"], r["code"]))
    stats_etf = continuation_stats(g_etf)
    srows = stock_level(rows, days)
    # 合併層級:交易日序列本身就相鄰,第一天之外 consec 一律成立
    g_stk = add_runs(srows, key=lambda r: r["code"])
    stats_stk = continuation_stats(g_stk)

    latest = {etf: max(by_d) for etf, by_d in snaps.items()}
    last_day = days[-1]
    stale = {e for e, d in latest.items() if days.index(last_day) - days.index(d) > STALE_DAYS}
    win = days[-WINDOW:]
    wi = {d: i for i, d in enumerate(win)}

    def stock(c):
        i = info.get(c) or {}
        return {"n": names.get(c, i.get("name", c)), "ind": i.get("ind") or "未分類",
                "mkt": i.get("mkt") or ""}

    def rate(stats, sig, run):
        n_ok, n = stats[str(sig)].get(str(min(run, 4)), [0, 0])
        return [n_ok, n]

    # 進行中的 run:ETF 層級以該 ETF 自己的最新資料日為準
    runs_etf = []
    for (etf, c), rs in g_etf.items():
        r = rs[-1]
        if (r["sig"] != 0 and r["date"] == latest[etf] and r["kind"] != "exit"
                and etf not in stale):
            runs_etf.append({"etf": etf, "c": c, "sig": r["sig"], "run": r["run"],
                             "start": r["run_start"], "date": r["date"],
                             "cum": r["run_amt"], "last": r["amt"] or 0, "kind": r["kind"],
                             "p": rate(stats_etf, r["sig"], r["run"])})
    runs_etf.sort(key=lambda x: (-x["run"], -abs(x["cum"])))
    runs_stk = []
    for c, rs in g_stk.items():
        r = rs[-1]
        if r["sig"] != 0 and r["date"] == last_day:
            runs_stk.append({"c": c, "sig": r["sig"], "run": r["run"], "start": r["run_start"],
                             "cum": r["run_amt"], "last": r["amt"], "nb": r["nb"], "ns": r["ns"],
                             "p": rate(stats_stk, r["sig"], r["run"])})
    runs_stk.sort(key=lambda x: (-x["run"], -abs(x["cum"])))

    cells_etf = [[r["etf"], r["code"], wi[r["date"]], round((r["amt"] or 0) / 1e8, 3),
                  r["sig"], r["kind"], round(r["adj"] / 1000), r["run"]]
                 for r in rows if r["sig"] != 0 and r["date"] in wi]
    cells_stk = [[r["code"], wi[r["date"]], round(r["amt"] / 1e8, 3), r["nb"], r["ns"], r["run"]]
                 for r in srows if r["sig"] != 0 and r["date"] in wi]
    used = {x[1] for x in cells_etf} | {x["c"] for x in runs_etf}
    built = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")

    data = {
        "built": built, "days": win, "last_day": last_day, "first_day": days[0],
        "n_days": len(days), "stale": sorted(stale),
        "etfs": {e: dict(etf_meta.get(e, {"name": e, "issuer": ""}), latest=latest[e])
                 for e in sorted(snaps)},
        "stocks": {c: stock(c) for c in sorted(used)},
        "cells_etf": cells_etf, "cells_stk": cells_stk,
        "runs_etf": runs_etf, "runs_stk": runs_stk,
        "stats_etf": stats_etf, "stats_stk": stats_stk,
    }
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False,
                                                       separators=(",", ":")))
    (HERE / "index.html").write_text(html, encoding="utf-8")

    # 給 TG:連 ≥2 天的進行中 run
    def tg_item(x, with_etf):
        s = stock(x["c"])
        d = {"code": x["c"], "name": s["n"], "ind": s["ind"], "mkt": s["mkt"],
             "sig": x["sig"], "run": x["run"], "cum": x["cum"], "last": x["last"],
             "p_cont": x["p"]}
        if with_etf:
            d.update(etf=x["etf"], etf_name=etf_meta.get(x["etf"], {}).get("name", x["etf"]),
                     date=x["date"])
        else:
            d.update(nb=x["nb"], ns=x["ns"])
        return d
    summary = {
        "built": built, "last_day": last_day, "url": PAGES_URL, "stale": sorted(stale),
        "runs_etf": [tg_item(x, True) for x in runs_etf if x["run"] >= 2][:TOP_RUNS],
        "runs_stk": [tg_item(x, False) for x in runs_stk if x["run"] >= 2][:TOP_RUNS],
    }
    (HERE / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    print("日曆完成:%d 交易日(%s ~ %s)、%d 檔 ETF、ETF 層級進行中 %d(≥2 天 %d)、合併層級 %d" % (
        len(days), days[0], last_day, len(snaps), len(runs_etf),
        sum(x["run"] >= 2 for x in runs_etf), len(runs_stk)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
