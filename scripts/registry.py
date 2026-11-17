# -*- coding: utf-8 -*-
"""ETF 清單自動偵測與 etf_registry.json 維護。

資料源:TWSE OpenAPI STOCK_DAY_ALL(全部上市證券,含 ETF)。
台股主動式 ETF 代號規則:00xxxA(第 6 碼 A=股票型主動式;D=債券型不納入)。
新掛牌若投信已有 adapter 自動納入;未知投信標 unsupported,UI 顯示待支援。
registry 檔內的 market/status 等欄位可手動覆寫,重跑不會蓋掉既有值。
"""
import json
import re
from pathlib import Path

import outputs

CODE_RE = re.compile(r"^00\d{3}A$")

# 名稱含這些關鍵字視為海外型,排除於追蹤(registry 可手動覆寫 market)。
# "ARK":00983A 主動中信ARK創新名稱無地區字樣但實持美股(2026-08-05 實查)。
FOREIGN_KEYWORDS = ("美國", "全球", "日本", "越南", "世界", "印度", "ARK")

# ETF 名稱一律「主動<投信><系列名>」,以投信名前綴對照 adapter 模組名
ISSUER_ADAPTERS = [
    ("統一", "president"),
    ("野村", "nomura"),
    ("群益", "capital"),
    ("中信", "ctbc"),
    ("安聯", "allianz"),
    ("復華", "fuhhwa"),
    ("台新", "taishin"),
    ("元大", "yuanta"),
    ("國泰", "cathay"),
    ("摩根", "jpmorgan"),
    ("富邦", "fubon"),
    ("聯博", "ab"),
    ("凱基", "kgi"),
    ("第一金", "firstsec"),
    ("永豐", "sinopac"),
    ("兆豐", "megafunds"),
    ("玉山", "esun"),
]

# 第一階段已實作的 adapter(其餘投信標 unsupported,陸續補)
IMPLEMENTED_ADAPTERS = {"president", "fuhhwa", "fubon", "capital", "ctbc",
                        "nomura", "allianz", "kgi", "taishin",
                        "sinopac", "cathay", "megafunds",
                        "firstsec", "ab", "jpmorgan", "esun"}


def _classify(name):
    for kw in FOREIGN_KEYWORDS:
        if kw in name:
            return "foreign"
    return "tw"


TW_CODE_RE = re.compile(r"^\d{4,6}$")  # 台股代號純數字;海外持股形如 'TSLA US'

# 台股權重低於此比例視為海外型(名稱看不出來的,如 00990A「主動元大AI新經濟」
# 實為美股 61%/台股 18%)。名稱關鍵字只是抓不到持股前的初判。
TW_WEIGHT_MIN = 50.0


def tw_weight(holdings):
    """持股中台股代號的權重合計(%)。"""
    return sum(h.weight for h in holdings if TW_CODE_RE.match(h.code))


def reclassify_by_holdings(path, reg, results):
    """以實際持股的台股權重覆寫 market,**就地更新傳入的 reg** 再寫回檔案。

    名稱關鍵字判不出來的海外型只有看持股才知道,故抓到資料後一律以持股為準。
    必須改傳入的那份 reg(而不是自己重讀一份),否則本次執行的 active.json 仍會
    沿用舊分類,改判要等下一次執行才生效。回傳 {code: tw_weight}。
    """
    weights = {}
    for code, r in results.items():
        if r.get("status") != "ok" or not r.get("holdings"):
            continue
        w = round(tw_weight(r["holdings"]), 2)
        weights[code] = w
        if code in reg:
            reg[code]["market"] = "tw" if w >= TW_WEIGHT_MIN else "foreign"
            reg[code]["tw_weight"] = w
    # 不在此落盤(見 opt#7 / save_registry):呼叫端可能還在整批流程中途,
    # 此時寫檔會讓 registry.json 比 active.json/index.html 早一步變更,
    # 一旦後續步驟失敗就留下不一致的狀態。改判結果只反映在傳入的 reg 物件。
    return weights


def _issuer_adapter(name):
    base = name[2:] if name.startswith("主動") else name  # 去「主動」前綴
    for issuer, adapter in ISSUER_ADAPTERS:
        if base.startswith(issuer):
            return issuer, adapter
    return "", ""


def detect_etfs(rows):
    """從 STOCK_DAY_ALL 列資料篩出主動式 ETF。回傳 [{code,name,market,issuer,adapter}]"""
    out = []
    for r in rows:
        code = (r.get("Code") or "").strip()
        if not CODE_RE.match(code):
            continue
        name = (r.get("Name") or "").strip()
        issuer, adapter = _issuer_adapter(name)
        out.append({
            "code": code,
            "name": name,
            "market": _classify(name),
            "issuer": issuer,
            "adapter": adapter,
        })
    return out


def load_and_update(path, fetched):
    """讀取並更新 registry(純記憶體操作,不落盤)。新代號加入;既有代號只補缺漏欄位。

    **呼叫端要另外呼叫 save_registry 才會寫檔**——原本這裡會直接寫入,但
    fetch_registry() 是整批流程最早呼叫的步驟,若持股後續全部抓取失敗
    (fetch_all_holdings 回傳空),registry.json 卻已經被新偵測到的 ETF 清單
    覆寫,等於整批失敗時仍留下一次「半成功」的寫入。分離讀取/更新與落盤,
    讓呼叫端可以自己決定何時才算「這次執行真的成功了」。
    """
    path = Path(path)
    reg = json.loads(path.read_text()) if path.exists() else {}
    for e in fetched:
        code = e["code"]
        if code in reg:
            for k, v in e.items():  # 只補新欄位(如改名不覆寫手動值)
                reg[code].setdefault(k, v)
        else:
            issuer, adapter = e.get("issuer", ""), e.get("adapter", "")
            if not (issuer and adapter):
                issuer, adapter = _issuer_adapter(e.get("name", ""))
            entry = dict(e)
            entry["issuer"] = issuer
            entry["adapter"] = adapter
            entry.setdefault("first_snapshot_date", None)
            reg[code] = entry
    # status 一律由 adapter 是否已實作推導,不沿用舊值——否則補完 adapter 後既有
    # ETF 會永遠卡在 unsupported。掃全表(不只本次偵測到的)。手動停用設 "disabled"。
    for entry in reg.values():
        # 偵測當時投信還沒進對照表的代號會留下空的 issuer/adapter;對照表補上後
        # 要能自動接上(上面的 setdefault 填不進已存在的空字串)。掃全表。
        if not entry.get("adapter"):
            issuer, adapter = _issuer_adapter(entry.get("name", ""))
            if adapter:
                entry["issuer"], entry["adapter"] = issuer, adapter
        if entry.get("status") != "disabled":
            entry["status"] = ("active" if entry.get("adapter") in IMPLEMENTED_ADAPTERS
                               else "unsupported")
    return reg


def save_registry(path, reg):
    """原子寫入 registry.json。呼叫端應在確認整批更新成功後才呼叫這個函式。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    outputs.write_text_atomic(
        path, json.dumps(reg, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
