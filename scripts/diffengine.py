# -*- coding: utf-8 -*-
"""持股異動判定:比對同一 ETF 兩份快照,產生 ADD/REMOVE/INCREASE/DECREASE 事件。

核心:ETF 被申購/贖回時全部持股股數會「等比例」增減,那是資金流不是經理人
操作。以全體共同持股股數比值的中位數當規模效應基準(scale),個股偏離基準
超過門檻才視為主動加減碼;權重差同時要過門檻(權重受股價被動影響,單獨
不可靠,但可濾掉「股數動、佔比根本沒變」的噪音)。
"""
import statistics

SHARES_THR = 0.05   # 校正後股數變化 ≥5%
MIN_COMMON = 3

def valid_scale(scale, common_count):
    return common_count >= MIN_COMMON and scale is not None and 0.2 <= scale <= 5


WEIGHT_THR = 0.1    # 且權重變化 ≥0.1 個百分點


def _ev(h, typ, prev=None, adj=None, scale=None):
    e = {"code": h.code, "name": h.name, "type": typ,
         "weight": h.weight, "shares": h.shares}
    if prev is not None:
        e["prev_weight"] = prev.weight
        e["weight_delta"] = round(h.weight - prev.weight, 4)
        e["prev_shares"] = prev.shares
        # 兩個數字都要留,語意不同、不可互相取代:
        #   shares_delta          原始差額(含申購贖回造成的等比例增減),可追溯
        #   adjusted_shares_delta 扣掉規模效應後的主動調整估算,與事件方向一致
        # 大量申購時原始差額可能與方向相反(INCREASE 卻是負張數),
        # 所以顯示「經理人買了多少」要用校正後那個。
        e["shares_delta"] = h.shares - prev.shares
        if scale:
            e["scale"] = round(scale, 6)
            e["adjusted_shares_delta"] = int(round(h.shares - prev.shares * scale))
    else:
        e["shares_delta"] = h.shares  # ADD:整個部位都是新建的
    if adj is not None:
        e["shares_delta_pct"] = round(adj * 100, 2)
    return e


def compute_events(prev, curr, shares_thr=SHARES_THR, weight_thr=WEIGHT_THR):
    """prev/curr: {code: Holding}。回傳事件 list(dict)。"""
    common = [c for c in curr if c in prev and prev[c].shares > 0 and curr[c].shares > 0]
    ratios = [curr[c].shares / prev[c].shares for c in common]
    # 必須是真中位數:偶數筆時 ratios[len//2] 取的是右側中央值,會讓 scale 偏移、
    # 進而改變事件是否跨過 5% 門檻(既有歷史 26 份快照中有 1 筆因此被漏判)。
    scale = statistics.median(ratios) if ratios else 1.0
    events = []
    for c, h in curr.items():
        if c not in prev:
            e = _ev(h, "ADD")
            e.update(adjusted_shares_delta=h.shares, scale=scale, common_holdings_count=len(common))
            events.append(e)
            continue
        p = prev[c]
        adj = (h.shares / (p.shares * scale) - 1) if p.shares and scale else 0.0
        dw = h.weight - p.weight
        if adj >= shares_thr and dw >= weight_thr:
            events.append(_ev(h, "INCREASE", p, adj, scale))
        elif adj <= -shares_thr and dw <= -weight_thr:
            events.append(_ev(h, "DECREASE", p, adj, scale))
    for c, p in prev.items():
        if c not in curr:
            events.append({"code": p.code, "name": p.name, "type": "REMOVE",
                           "prev_weight": p.weight, "prev_shares": p.shares,
                           "shares_delta": -p.shares,
                           "adjusted_shares_delta": round(-p.shares * scale, 6) if common and scale > 0 else None,
                           "scale": scale if common else None,
                           "common_holdings_count": len(common)})  # 出清:全數賣出
    for event in events:
        event["common_holdings_count"] = len(common)
        event["quality"] = "ok" if valid_scale(scale, len(common)) else "insufficient_scale"
        if event["quality"] != "ok":
            event["adjusted_shares_delta"] = None
    return events
