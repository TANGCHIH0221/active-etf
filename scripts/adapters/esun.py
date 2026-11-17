# -*- coding: utf-8 -*-
"""玉山投信(esunam.com)adapter。

玉山投信是 2025 年收購保德信投信後更名,網域是 **esunam.com**(不是 .com.tw)。

資料源(2026-11-13 探勘,ETF 專區是 Angular SPA,資料走 JSON API):
- POST https://www.esunam.com/ETFAPI/GetETFFundSelectList  {"TypeID": 5542}
    5542 =「主動式ETF」類別(GetETFFundTypes 查得)。回 Entries[]:
    FundNo(如 "54")/ FundShortName(如「主動玉山關鍵科技」,與 registry 名稱相同)。
    清單**不含股票代號**,只能以簡稱對照。
- POST https://www.esunam.com/ETFAPI/GetFundTradeInfo  {"FundNo": "54", "Date": null}
    Date=null 回最新一份。Entries:
      CNavDt     基準日 T(取這個)
      CPcfdate   公告生效日 T+1(勿用)
      CAnceTotalAv / CAnceTotalIssues / CAnceNav  淨資產 / 單位數 / 每單位淨值
      CBeneficiariesCount  受益人數;未揭露時為 0 且日期為 1900-01-01 → 視為 None
      DynamicTableData[]   TableTitle「股票」:Columns 股票代號/股票名稱/股數/權重(%),
                           Rows 為字串陣列(股數含千分位)。
    回應不含股票代號,無法像兆豐那樣以代號複核;改以 CFundShortName 複核名稱。
"""
from .base import (ADAPTERS, AdapterError, Holding, parse_dotnet_date, post,
                   to_num, validate_holdings)

API = "https://www.esunam.com/ETFAPI/"
ACTIVE_TYPE_ID = 5542
HEADERS = {"Content-Type": "application/json",
           "Referer": "https://www.esunam.com/ETF/trad-info"}
STOCK_TABLE = "股票"


def _call(name, payload):
    r = post(API + name, json=payload, headers=HEADERS)
    try:
        d = r.json()
    except ValueError:
        raise AdapterError("esun: {} 回非 JSON(改版或被擋?)".format(name))
    if d.get("StatusCode") != 0:
        raise AdapterError("esun: {} StatusCode={} {}".format(
            name, d.get("StatusCode"), d.get("Message") or ""))
    return d.get("Entries")


def pick_fund_no(entries, etf_name):
    """清單 → FundNo。簡稱與 registry 名稱一致(皆含「主動」前綴)。"""
    name = etf_name.strip()
    for e in entries or []:
        if (e.get("FundShortName") or "").strip() == name and e.get("FundNo"):
            return str(e["FundNo"])
    return None


def _col(columns, label):
    names = [c.get("Name") for c in columns]
    if label not in names:
        raise AdapterError("esun: 股票表缺欄位「{}」(改版?)欄位={}".format(label, names))
    return names.index(label)


def parse_trade_info(e, etf_code, etf_name=None):
    """GetFundTradeInfo 的 Entries → (data_date, [Holding], meta)"""
    if not e:
        raise AdapterError("{}: GetFundTradeInfo 無資料".format(etf_code))
    if etf_name and (e.get("CFundShortName") or "").strip() != etf_name.strip():
        raise AdapterError("{}: 回應基金「{}」與 registry「{}」不符".format(
            etf_code, e.get("CFundShortName"), etf_name))
    if not e.get("CNavDt"):
        raise AdapterError("{}: 缺基準日 CNavDt(改版?)".format(etf_code))
    data_date = parse_dotnet_date(e["CNavDt"])
    tables = [t for t in e.get("DynamicTableData") or []
              if t.get("TableTitle") == STOCK_TABLE]
    if not tables:
        raise AdapterError("{}: 找不到「股票」表(改版?)".format(etf_code))
    t = tables[0]
    cols = t.get("Columns") or []
    ic, iname, ishares, iw = (_col(cols, "股票代號"), _col(cols, "股票名稱"),
                              _col(cols, "股數"), _col(cols, "權重(%)"))
    holdings = []
    for row in t.get("Rows") or []:
        shares, weight = to_num(row[ishares]), to_num(row[iw])
        if shares is None or weight is None:
            raise AdapterError("{}: {} 股數/權重無法解析: {}".format(etf_code, row[ic], row))
        holdings.append(Holding(code=str(row[ic]), name=str(row[iname]),
                                shares=int(shares), weight=weight))
    holders = e.get("CBeneficiariesCount")
    if not holders or str(e.get("CBeneficiariesCountDate") or "").startswith("1900"):
        holders = None
    meta = {"scale": to_num(e.get("CAnceTotalAv")),
            "units": to_num(e.get("CAnceTotalIssues")),
            "nav_per_unit": to_num(e.get("CAnceNav")),
            "holders": holders}
    return data_date, validate_holdings(holdings, etf_code), meta


def fetch_holdings(etf):
    code, name = etf["code"], (etf.get("name") or "").strip()
    fund_no = pick_fund_no(_call("GetETFFundSelectList", {"TypeID": ACTIVE_TYPE_ID}), name)
    if not fund_no:
        raise AdapterError("esun: {}「{}」不在主動式 ETF 清單".format(code, name))
    e = _call("GetFundTradeInfo", {"FundNo": fund_no, "Date": None})
    return parse_trade_info(e, code, name)


ADAPTERS["esun"] = fetch_holdings
