# -*- coding: utf-8 -*-
"""adapter 共用層:資料結構、HTTP 工具、持股驗證、adapter 註冊表。

每家投信 adapter 模組需提供
    fetch_holdings(etf: dict) -> (data_date, [Holding], meta)
並以 ADAPTERS["<name>"] = fetch_holdings 註冊(name 同 registry 的 adapter 欄位)。

各家 adapter 的「資料日」取自哪個欄位——**這張表是踩過坑才建的,改 adapter 前先看**。
投信頁面上常同時有「公告(生效)日 T+1」與「持股/淨值基準日 T」,取錯會讓該檔比其他家
整整多一天,共識榜就會把不同持股日的 ETF 併成「今日同步調整」。

    投信        欄位                      語意
    統一        pcf[0].TranDate           基準日
    野村        CNavDtStr                 基準日(CPcfdate 是公告日,勿用)
    安聯        CNavDt                    基準日(同上)
    群益        data.pcf.date2            基準日(date1 是公告日,勿用)
    中信        FundAssets[0].資料日期     基準日
    復華        result[0].dDate           基準日
    富邦        頁面「資料日期：」          基準日
    凱基        頁面「持股比重 (日期)」     基準日(== LatestNAVDate,2026-09-10 查證)
    永豐        頁面「資料日期：」          基準日
    國泰        BuySale.preDateC          基準日(date 是公告生效日 T+1,勿用)
    兆豐        查詢日期之後那個日期        基準日(查詢日期本身是公告生效日)
    第一金      sdate                     基準日
    聯博        holdings asOfDate         基準日(先取 basket.asOfDate 再帶入查詢)
    摩根        sheet 標題 (YYYY-MM-DD)    公告日;無獨立基準日欄位,已知比基準日新
    台新        NAV_DATE                  基準日(PUB_DATE 是公告生效日 T+1,勿用)
    玉山        CNavDt                    基準日(CPcfdate 是公告生效日 T+1,勿用)

meta 為該檔基本面 dict(缺漏欄位給 None,不影響主流程):
    scale        基金淨資產(元)
    units        已發行受益權單位總數
    nav_per_unit 每受益權單位淨值
    holders      受益人數
基本面一律取自各投信 PCF 原始回應——那是官方公告值,且與持股同一份資料,
不另外去第三方湊。
"""
import math
import time
from dataclasses import dataclass

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# 主動式 ETF 現金/期貨部位可觀(實測 00403A 股票僅 84%),此檢查只為抓解析錯誤
# (權重尺度錯置、整批漏列),不是投資組合完整性檢查。
WEIGHT_SUM_MIN = 50.0
WEIGHT_SUM_MAX = 105.0


class AdapterError(Exception):
    """單檔 ETF 抓取/解析/驗證失敗。主流程捕捉後標 stale,不中斷整批。"""


@dataclass
class Holding:
    code: str
    name: str
    shares: int
    weight: float  # 百分比數值,如 25.1


_session = None


def get(url, **kw):
    """共用 GET:帶 UA、timeout、失敗重試 2 次。kw 透傳 requests(headers 會合併)。"""
    return _request("GET", url, **kw)


def post(url, **kw):
    return _request("POST", url, **kw)


def _request(method, url, **kw):
    global _session
    if _session is None:
        _session = requests.Session()
    headers = {"User-Agent": UA}
    headers.update(kw.pop("headers", {}))
    kw.setdefault("timeout", 30)
    last = None
    for attempt in range(3):
        try:
            r = _session.request(method, url, headers=headers, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise AdapterError("{} 抓取失敗: {}".format(url, last))


# 常見圖檔的起始位元組。投信站台若啟用機器人防護,會用 HTTP 200 回一張驗證圖
# 而不是 JSON——若不辨識,錯誤訊息會變成「回非 JSON(改版?)」而誤導成程式壞掉。
_IMAGE_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8")


def is_bot_challenge(resp):
    """回應是圖片(而非預期的資料)→ 視為站方的機器人驗證挑戰。"""
    body = resp.content[:8]
    return any(body.startswith(m) for m in _IMAGE_MAGIC)


def validate_holdings(holdings, etf_code):
    """空資料/權重合計異常/負股數 → AdapterError;回傳代號正規化後的清單。"""
    if not holdings:
        raise AdapterError("{}: 持股為空".format(etf_code))
    total = sum(x.weight for x in holdings)
    if not (WEIGHT_SUM_MIN <= total <= WEIGHT_SUM_MAX):
        raise AdapterError("{}: 權重合計 {:.2f} 超出 {}-{}".format(
            etf_code, total, WEIGHT_SUM_MIN, WEIGHT_SUM_MAX))
    out, seen = [], set()
    for x in holdings:
        code = x.code.strip().upper()
        # 空代號通常是把「現金」「合計」那種列當成持股抓進來了
        if not code:
            raise AdapterError("{}: 出現空的持股代號(誤抓合計/現金列?)".format(etf_code))
        # 重複代號兩邊結論會不一致:diffengine 用 dict 會覆蓋(少算),
        # 反查卻會累加(多算)。同一份資料算出兩種答案,寧可當場擋下。
        if code in seen:
            raise AdapterError("{}: 持股代號重複 {}".format(etf_code, code))
        seen.add(code)
        if x.shares < 0:
            raise AdapterError("{}: {} 股數為負".format(etf_code, code))
        w = float(x.weight)
        if not math.isfinite(w) or not math.isfinite(float(x.shares)):
            raise AdapterError("{}: {} 權重或股數非有限數值".format(etf_code, code))
        if w < 0 or w > 100.0:
            raise AdapterError("{}: {} 單筆權重 {:.2f} 超過 100%".format(etf_code, code, w))
        out.append(Holding(code=code, name=x.name.strip(), shares=int(x.shares),
                           weight=w))
    return out


def parse_dotnet_date(s):
    """解析 .NET JSON 日期,兩種形式都出現過:
    '2026-08-04T00:00:00' 或 '/Date(1785772800000)/'(ms epoch,UTC)。
    回傳 'YYYY-MM-DD'。"""
    import datetime
    import re as _re
    m = _re.match(r"/Date\((\d+)\)/", s)
    if m:
        # ms 值實測為台灣午夜之 epoch(如 1785772800000 → 2026-08-04 00:00 台北)
        # 用 UTC 解會少一天,必須以 +8 時區解
        tz = datetime.timezone(datetime.timedelta(hours=8))
        dt = datetime.datetime.fromtimestamp(int(m.group(1)) / 1000, tz)
        return dt.strftime("%Y-%m-%d")
    return s[:10]


def to_num(v):
    """'30,372,771,968' / 'NT$8.10' / 8.1 / None → float 或 None。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("NT$", "").replace("$", "").strip()
    if not s or s in ("-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def roc_date(dt):
    """datetime.date → 民國年字串 '115/08/05'"""
    return "{}/{:02d}/{:02d}".format(dt.year - 1911, dt.month, dt.day)


# adapter 註冊表:模組 import 時自行填入
ADAPTERS = {}
