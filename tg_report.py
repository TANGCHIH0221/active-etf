#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主動式 ETF 每日持股異動 → Telegram 推播。

讀 repo 根目錄的 active.json,把「經理人主動調整」換算成金額後推到 Telegram。

為什麼要看 adjusted_shares_delta 而不是 shares_delta:
    ETF 被申購/贖回時,全部持股會等比例增減,那是資金流不是經理人決策。
    上游 scripts/diffengine.py 以「全體共同持股股數比值的中位數」當規模效應
    基準(事件裡的 scale 欄位),adjusted_shares_delta = 今日股數 − 昨日股數 × scale。
    已用 data/history/ 的前後快照獨立重算驗證過(58/58 相符)。
    注意:etfs[x].scale 是淨資產(元),events[i].scale 是申贖倍率,同名不同義。

為什麼需要狀態檔:
    active.json 的 events 只在「data_date 前進的那一次執行」才有內容,之後會被
    清空。所以(1)每檔 ETF 只能跟自己的上一個資料日比,(2)漏跑一天該日事件就從
    active.json 消失、只剩 data/history/ 撈得回來 → 偵測到斷層時自動補發。
"""
import argparse
import copy
import glob
import json
from datetime import date, datetime, timezone
from pathlib import Path

from tg_common import (esc, fmt_amount, fmt_lots, load_state, now_tpe,
                       save_state, session_date, tg_send)

ROOT = Path(__file__).resolve().parent

DETAIL_TOTAL = 3e8      # 單一 ETF 單日主動調整總額 ≥ 3 億才逐筆詳列
DETAIL_MIN_ITEM = 1e7   # 詳列時單筆 ≥ 1000 萬
DETAIL_MAX_ITEMS = 8    # 詳列最多幾筆
MAX_BACKFILL_DAYS = 3   # 單檔 ETF 一次最多補幾個資料日。實測從最早快照全回溯會
                        # 產生 24 則訊息,不但觸發 Telegram 限流,也根本讀不完。
                        # 正常斷層只有 1-2 天,設 3 天已足夠;更早的略過並在結尾告知。
MULTI_ETF_MIN = 2       # 多檔同向榜:至少幾檔 ETF 同方向才上榜
MULTI_ETF_MAX = 10
# 只在 status == "stale" 時提醒。stale 的語意是「抓取失敗或投信回了舊快取」
# (見 scripts/update_dashboard.py:carry_stale),是真的有問題。
# 反之 status == "ok" 但資料日較舊,是投信自己公布得慢(野村/安聯常態),
# 用日曆天數當判準會天天誤報,變成狼來了。
STALE_MAX_LIST = 6      # 提醒最多列幾檔

MARK = {"INCREASE": "🔴", "DECREASE": "🟢", "ADD": "✨", "REMOVE": "❌"}
VERB = {"INCREASE": "加碼", "DECREASE": "減碼", "ADD": "新增", "REMOVE": "剔除"}


# ------------------------------------------------------------------ 資料層

def build_history_index(root):
    """{etf: {data_date: etf_info}}。

    同一個 data_date 會在多份快照裡重複出現(資料沒更新的日子照樣存檔),只有
    「第一次出現」那份的 events 有內容,後面都是空陣列 → 一律取第一次出現。
    """
    idx = {}
    for f in sorted(glob.glob(str(Path(root) / "data" / "history" / "*.json"))):
        try:
            with open(f, encoding="utf-8") as fh:
                snap = json.load(fh)
        except (ValueError, OSError) as e:
            print("[warn] 快照 %s 讀取失敗: %s" % (f, e))
            continue
        for etf, info in (snap.get("etfs") or {}).items():
            dd = info.get("data_date")
            if dd:
                idx.setdefault(etf, {}).setdefault(dd, info)
    return idx


def active_shares(ev):
    """這筆事件的「主動調整股數」。算不出來回傳 None。"""
    t = ev.get("type")
    if t in ("INCREASE", "DECREASE"):
        # 舊快照(2026-09 之前)還沒有 adjusted_shares_delta 這個欄位,補發時要退回原始差額
        for k in ("adjusted_shares_delta", "shares_delta"):
            if ev.get(k) is not None:
                return ev[k]
        if ev.get("shares") is not None and ev.get("prev_shares") is not None:
            return ev["shares"] - ev["prev_shares"]
    elif t == "ADD":
        for k in ("shares_delta", "shares"):
            if ev.get(k) is not None:
                return ev[k]
    elif t == "REMOVE":
        if ev.get("shares_delta") is not None:
            return ev["shares_delta"]
        if ev.get("prev_shares") is not None:
            return -ev["prev_shares"]
    return None


def event_amount(ev, etf_info, stocks):
    """回傳 (主動股數, 金額元, 金額是否為估算)。

    收盤價優先用 stocks 索引;查不到(多半是 REMOVE,個股已不在任何 ETF 裡)才用
    權重 × 淨資產 ÷ 股數 反推。反推誤差中位數 0.35%、p90 4.3%,但尾端可到 90%
    以上(少數 ETF 的權重基準與淨資產不一致),所以估算值一律標記。
    """
    sh = active_shares(ev)
    if sh is None:
        return None, None, False
    px = (stocks.get(ev.get("code")) or {}).get("close")
    est = False
    if not px:
        nav_total = etf_info.get("scale")   # 淨資產(元)
        if ev.get("type") == "REMOVE":
            w, s = ev.get("prev_weight"), ev.get("prev_shares")
        else:
            w, s = ev.get("weight"), ev.get("shares")
        if nav_total and w and s:
            px, est = w / 100.0 * nav_total / s, True
    if not px:
        return sh, None, False
    return sh, sh * px, est


# ------------------------------------------------------------------ 計算層

def collect(active, state, root, force=False, first_run=False):
    """回傳 (records, processed, hist_used, skipped)。

    records:   每筆事件一個 dict
    processed: {etf: [(data_date, is_backfill), ...]} 這次新處理到的資料日
    hist_used: 有沒有動用到 data/history/(代表發生過補發)
    skipped:   {etf: 因超過 MAX_BACKFILL_DAYS 而略過的天數}
    """
    stocks = active.get("stocks") or {}
    hist_idx = None
    records, processed, skipped = [], {}, {}

    for etf, info in sorted((active.get("etfs") or {}).items()):
        cur = info.get("data_date")
        if not cur:
            continue
        seen = (state["etfs"].get(etf) or {}).get("data_date")
        if seen and cur < seen:
            # 資料來源抽風把資料日往回寫,不處理也不覆蓋狀態,避免重複推播
            print("[warn] %s 資料日倒退 %s → %s,跳過" % (etf, seen, cur))
            continue
        if seen == cur and not force:
            continue

        days = []
        if seen and not first_run and not force:
            if hist_idx is None:
                hist_idx = build_history_index(root)
            gap = [d for d in sorted(hist_idx.get(etf, {})) if seen < d < cur]
            if len(gap) > MAX_BACKFILL_DAYS:
                skipped[etf] = len(gap) - MAX_BACKFILL_DAYS
                gap = gap[-MAX_BACKFILL_DAYS:]
            days.extend((d, True) for d in gap)
        days.append((cur, False))
        processed[etf] = days

        for dd, is_bf in days:
            if is_bf:
                evs = (hist_idx[etf].get(dd) or {}).get("events") or []
            else:
                evs = info.get("events") or []
            for ev in evs:
                sh, amt, est = event_amount(ev, info, stocks)
                if sh is None or sh == 0:
                    continue
                code = ev.get("code")
                records.append({
                    "etf": etf,
                    "etf_name": info.get("name") or etf,
                    "data_date": dd,
                    "backfill": is_bf,
                    "type": ev.get("type"),
                    "code": code,
                    # 各投信寫的股名不一致(「貿聯-KY」/「貿聯控股」/「貿聯 -KY」),
                    # 一律以 stocks 索引的名稱為準,跨 ETF 才聚得起來
                    "name": (stocks.get(code) or {}).get("name") or ev.get("name") or code,
                    "shares": sh,
                    "amount": amt,
                    "estimated": est,
                })
    return records, processed, hist_idx is not None, skipped


def update_streaks(state, records, processed):
    """標記「同一檔 ETF、同一檔股票、連續資料日同方向」的連續天數。

    某個資料日沒出現事件 → 連續中斷(所以每個資料日都用當日出現的股票重建)。
    """
    by_key = {}
    for r in records:
        by_key.setdefault((r["etf"], r["data_date"]), []).append(r)

    for etf, days in processed.items():
        node = state["etfs"].setdefault(etf, {})
        streaks = node.get("streaks") or {}
        for dd, _ in days:                      # days 已是資料日升冪
            new = {}
            for r in by_key.get((etf, dd), []):
                d = 1 if r["shares"] > 0 else -1
                prev = streaks.get(r["code"])
                n = prev["days"] + 1 if prev and prev.get("dir") == d else 1
                new[r["code"]] = {"dir": d, "days": n}
                r["streak"] = n
                r["streak_dir"] = d
            streaks = new
        node["streaks"] = streaks
        node["data_date"] = days[-1][0]


# ------------------------------------------------------------------ 呈現層

def _item_line(r):
    s = " %s <b>%s</b> <code>%s</code> %s" % (
        MARK.get(r["type"], "•"), esc(r["name"]), esc(r["code"]), fmt_lots(r["shares"]))
    if r["amount"] is not None:
        s += "　%s%s" % ("~" if r["estimated"] else "", fmt_amount(r["amount"]))
    if r["type"] in ("ADD", "REMOVE"):
        s += "　(%s)" % VERB[r["type"]]
    n = r.get("streak", 1)
    if n >= 2:
        s += "　連%d天%s" % (n, "加碼" if r["streak_dir"] > 0 else "減碼")
    return s


def render_report(records, processed, active, skipped=None):
    tpe = now_tpe()
    lines = ["<b>📊 主動式 ETF 持股異動</b>",
             "%s ・ 新資料 %d 檔 ・ 有異動 %d 檔" % (
                 tpe.strftime("%m/%d %H:%M"), len(processed),
                 len({r["etf"] for r in records}))]

    groups = {}
    for r in records:
        groups.setdefault((r["etf"], r["data_date"]), []).append(r)

    def gross(rs):
        return sum(abs(r["amount"]) for r in rs if r["amount"] is not None)

    detail = [(k, v) for k, v in groups.items() if gross(v) >= DETAIL_TOTAL]
    brief = [(k, v) for k, v in groups.items() if gross(v) < DETAIL_TOTAL]
    # 補發的排在當日資料後面,且補發之間按資料日升冪 —— 不然一次補好幾天時
    # 日期會跳來跳去很難讀,而「今天的異動」也會被舊資料擠到下面。
    def order(kv):
        (etf, dd), rs = kv
        return (1 if rs[0]["backfill"] else 0, dd if rs[0]["backfill"] else "", -gross(rs))
    detail.sort(key=order)
    brief.sort(key=order)

    for (etf, dd), rs in detail:
        tag = "［補］" if rs[0]["backfill"] else ""
        lines.append("")
        lines.append("<b>%s%s</b> <code>%s</code>" % (tag, esc(rs[0]["etf_name"]), esc(etf)))
        lines.append("資料日 %s ・ 主動調整 %s ・ %d 筆" % (
            dd[5:], fmt_amount(gross(rs)).lstrip("+"), len(rs)))
        shown = [r for r in rs
                 if r["amount"] is None or abs(r["amount"]) >= DETAIL_MIN_ITEM]
        shown.sort(key=lambda r: -(abs(r["amount"]) if r["amount"] is not None else 0))
        for r in shown[:DETAIL_MAX_ITEMS]:
            lines.append(_item_line(r))
        rest = len(rs) - len(shown[:DETAIL_MAX_ITEMS])
        if rest > 0:
            lines.append(" …另 %d 筆較小" % rest)

    if brief:
        lines.append("")
        lines.append("<b>其他有異動(未達 %s)</b>" % fmt_amount(DETAIL_TOTAL).lstrip("+"))
        for (etf, dd), rs in brief:
            tag = "［補］" if rs[0]["backfill"] else ""
            lines.append(" %s%s <code>%s</code> %d 筆 ・ %s ・ %s" % (
                tag, esc(rs[0]["etf_name"]), esc(etf), len(rs),
                fmt_amount(gross(rs)).lstrip("+"), dd[5:]))

    # 多檔同向調整榜
    per_stock = {}
    for r in records:
        d = 1 if r["shares"] > 0 else -1
        k = (r["code"], d)
        e = per_stock.setdefault(k, {"name": r["name"], "etfs": set(), "amt": 0.0})
        e["etfs"].add(r["etf"])
        if r["amount"] is not None:
            e["amt"] += r["amount"]
    multi = [(k, v) for k, v in per_stock.items() if len(v["etfs"]) >= MULTI_ETF_MIN]
    multi.sort(key=lambda kv: -abs(kv[1]["amt"]))
    if multi:
        lines.append("")
        lines.append("<b>多檔同向</b>")
        for (code, d), v in multi[:MULTI_ETF_MAX]:
            lines.append(" <b>%s</b> <code>%s</code>　%d 檔%s　%s" % (
                esc(v["name"]), esc(code), len(v["etfs"]),
                "加碼" if d > 0 else "減碼", fmt_amount(v["amt"])))

    # 抓取異常提醒。這一段只是附註,不值得為了格式問題讓整支腳本掛掉,
    # 所以日期解析失敗就退成「只報 status」。
    today = date.fromisoformat(session_date(tpe))
    stale = []
    for etf, info in sorted((active.get("etfs") or {}).items()):
        if info.get("status") == "ok":
            continue
        dd = info.get("data_date")
        try:
            note = "(停在 %s,%d 天)" % (dd[5:], (today - date.fromisoformat(dd)).days)
        except (TypeError, ValueError):
            note = "(資料日 %s)" % dd if dd else ""
        stale.append("%s %s%s" % (etf, info.get("status") or "?", note))
    if skipped:
        lines.append("")
        lines.append("<b>ℹ️ 略過較早的補發</b>")
        if len(skipped) > 4:
            lines.append(" %d 檔 ETF 的斷層超過 %d 天,只補最近 %d 天(最多略過 %d 天)"
                         % (len(skipped), MAX_BACKFILL_DAYS, MAX_BACKFILL_DAYS,
                            max(skipped.values())))
        else:
            lines.append(" " + "、".join("%s 略過 %d 天" % kv
                                        for kv in sorted(skipped.items())))

    if stale:
        lines.append("")
        lines.append("<b>⚠️ 抓取異常</b>")
        lines.append(" " + "、".join(stale[:STALE_MAX_LIST]))
        if len(stale) > STALE_MAX_LIST:
            lines.append(" …另 %d 檔" % (len(stale) - STALE_MAX_LIST))

    return "\n".join(lines)


# ------------------------------------------------------------------ 主流程

def main():
    ap = argparse.ArgumentParser(description="主動式 ETF 持股異動 Telegram 推播")
    ap.add_argument("--dry-run", action="store_true", help="只印訊息,不發 Telegram")
    ap.add_argument("--late", action="store_true",
                    help="晚班:若今天完全沒新資料就推一則提醒")
    ap.add_argument("--force", action="store_true",
                    help="忽略狀態重新產生最新一天的報告(測試用,不寫回狀態)")
    ap.add_argument("--active", default=str(ROOT / "active.json"))
    ap.add_argument("--state", default=str(ROOT / "tg_state" / "state.json"))
    ap.add_argument("--root", default=str(ROOT), help="data/history/ 的所在目錄")
    args = ap.parse_args()

    with open(args.active, encoding="utf-8") as f:
        active = json.load(f)

    state = load_state(args.state)
    first_run = state is None
    if first_run:
        state = {"version": 1, "etfs": {}}
    state.setdefault("etfs", {})

    records, processed, hist_used, skipped = collect(
        active, state, args.root, force=args.force, first_run=first_run)
    # 連續天數要先算出來才能渲染訊息,但萬一推播失敗,狀態不能跟著前進 ——
    # 否則這批事件在 active.json 被清空後就永遠消失,補發機制也救不回來
    # (補發靠的是「狀態裡的資料日落後」才會去翻 data/history/)。
    # 故先留一份副本,推播失敗時整份回滾,下一輪自然重試。
    state_before = copy.deepcopy(state)
    update_streaks(state, records, processed)

    tpe = now_tpe()
    sess = session_date(tpe)
    sent_ok = True

    if records:
        body = render_report(records, processed, active, skipped)
        if first_run:
            body = ("<b>✅ 主動式 ETF 推播已啟動</b>\n"
                    "之後每個交易日晚間自動推送。以下是最新一天的異動。\n\n") + body
        if hist_used:
            body += "\n\n<i>［補］= 之前漏推、從 data/history/ 補發</i>"
        sent_ok = tg_send(body, dry_run=args.dry_run)
        if sent_ok:
            state["last_advance_session"] = sess
            state["last_advance_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        else:
            print("[error] 推播失敗,回滾狀態讓下一輪重試")
            state = state_before
    elif processed:
        # 有 ETF 的資料日前進了,但門檻內沒有任何主動異動 → 不吵人,只記狀態
        print("[info] %d 檔資料日前進但無主動異動,不推播" % len(processed))
        state["last_advance_session"] = sess
        state["last_advance_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    elif args.late:
        if state.get("last_advance_session") == sess:
            print("[info] 今天已推播過,晚班靜默")
        else:
            dds = sorted({(i.get("data_date") or "?")
                          for i in (active.get("etfs") or {}).values()})
            sent_ok = tg_send(
                "<b>🌙 今天沒有新資料</b>\n"
                "%s 晚間檢查:%d 檔 ETF 的資料日都沒有前進。\n"
                "可能是休市,也可能是 PCF 抓取失敗 —— 若隔天仍無資料請上 GitHub Actions 看 log。\n"
                "目前各檔資料日範圍:%s ~ %s" % (
                    tpe.strftime("%m/%d %H:%M"), len(active.get("etfs") or {}),
                    dds[0], dds[-1]),
                dry_run=args.dry_run)
    else:
        print("[info] 沒有新資料,一般班靜默")

    # 每次執行都寫狀態:(1) 記錄心跳 (2) 讓 workflow 每天都有 commit,
    # 公開 repo 連續 60 天沒活動 GitHub 會自動停用排程。
    # dry-run 也不能寫:否則下一次正式執行會以為已推過而靜默,訊息就漏掉了。
    if args.force or args.dry_run:
        print("[info] %s 模式,不寫回狀態檔" % ("--force" if args.force else "--dry-run"))
    else:
        state["last_run_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        state["last_run_tpe"] = tpe.strftime("%Y-%m-%d %H:%M:%S")
        save_state(args.state, state)

    return 0 if sent_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
