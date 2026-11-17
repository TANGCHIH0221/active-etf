# -*- coding: utf-8 -*-
"""上市/上櫃全股收盤價(ETF 折溢價、事件日收盤用)。

作法移植自 twse-disposition(已驗證):
- TWSE STOCK_DAY_ALL:response=json 實際回 CSV(2026-07 起),欄位
  0=日期(民國7碼) 1=代號 3=成交股數 8=收盤價 → 用 csv 解析。
- TPEx openapi tpex_mainboard_quotes:JSON,Date 為民國 7 碼。
"""
import csv
import io

from adapters.base import AdapterError, get

TWSE_STOCK_DAY = "https://www.twse.com.tw/exchangeReport/STOCK_DAY_ALL?response=json"
TPEX_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes"


def _roc_to_iso(roc7):
    return "{}-{}-{}".format(int(roc7[:3]) + 1911, roc7[3:5], roc7[5:7])


def parse_twse_csv(text):
    """回傳 (date_iso, {code: close})"""
    date_iso, out = None, {}
    for r in csv.reader(io.StringIO(text)):
        if len(r) < 11 or not (r[0].isdigit() and len(r[0]) == 7):
            continue
        if date_iso is None:
            date_iso = _roc_to_iso(r[0])
        code = r[1].strip()
        try:
            out[code] = float(r[8].replace(",", ""))
        except (ValueError, IndexError):
            continue
    return date_iso, out


def parse_tpex_json(rows):
    """回傳 (date_iso, {code: close})"""
    date_iso, out = None, {}
    for r in rows:
        code = (r.get("SecuritiesCompanyCode") or "").strip()
        if not code:
            continue
        d = (r.get("Date") or "").strip()
        if date_iso is None and len(d) == 7 and d.isdigit():
            date_iso = _roc_to_iso(d)
        try:
            out[code] = float((r.get("Close") or "").replace(",", ""))
        except ValueError:
            continue
    return date_iso, out


class QuoteMap(dict):
    """Backward-compatible price mapping with explicit per-security provenance."""
    def __init__(self, values=None, dates=None):
        super().__init__(values or {})
        self.dates = dates or {}


def merge_quotes(twse, tpex, failed):
    """((date,dict) | None, (date,dict) | None, [失敗市場]) → (date, 合併 dict, 失敗清單)。

    日期以 TWSE 為準(上市股票佔絕大多數);TWSE 掛掉才退而用 TPEx 的日期。
    """
    date_iso, out = None, QuoteMap()
    if twse:
        date_iso = twse[0]
        out.update(twse[1])
        out.dates.update({c: twse[0] for c in twse[1]})
    if tpex:
        for code, close in tpex[1].items():
            if code not in out:
                out[code] = close
                out.dates[code] = tpex[0]
        date_iso = date_iso or tpex[0]
    return date_iso, out, failed


def fetch_all():
    """合併上市+上櫃收盤 → (date_iso, {code: close}, [失敗市場])。

    **單一市場抓失敗不中斷整批。** 2026-09-13 實際發生過:持股 22 檔全部抓成功、
    事件也算完了,卻因為 TPEx 回 IncompleteRead 讓整個流程在寫入前炸掉,
    快照與 active.json 全停在舊版。持股才是主產品,報價只影響折溢價與市值估算,
    不該有一票否決權。
    """
    twse = tpex = None
    failed = []
    try:
        twse = parse_twse_csv(get(TWSE_STOCK_DAY).text)
    except (AdapterError, ValueError) as e:
        failed.append("TWSE")
        print("  ⚠️ TWSE 報價抓取失敗(折溢價與市值將留白):{}".format(str(e)[:120]), flush=True)
    try:
        tpex = parse_tpex_json(get(TPEX_QUOTES).json())
    except (AdapterError, ValueError) as e:
        failed.append("TPEx")
        print("  ⚠️ TPEx 報價抓取失敗(上櫃個股市值將留白):{}".format(str(e)[:120]), flush=True)
    return merge_quotes(twse, tpex, failed)
