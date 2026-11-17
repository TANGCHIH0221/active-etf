# -*- coding: utf-8 -*-
"""玉山投信 adapter 固定測資測試(fixture 為 2026-11-13 實抓)。"""
import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from adapters import esun
from adapters.base import ADAPTERS, AdapterError

FIX = Path(__file__).parent / "fixtures" / "esun"


def _entries(name):
    return json.loads((FIX / name).read_text())["Entries"]


class EsunTests(unittest.TestCase):
    def test_pick_fund_no(self):
        fl = _entries("fundlist_active.json")
        self.assertEqual(esun.pick_fund_no(fl, "主動玉山關鍵科技"), "54")
        self.assertIsNone(esun.pick_fund_no(fl, "主動玉山不存在"))

    def test_parse_trade_info(self):
        e = _entries("tradeinfo_00413A.json")
        data_date, holdings, meta = esun.parse_trade_info(e, "00413A", "主動玉山關鍵科技")
        # CNavDt 是基準日 T;CPcfdate(2026-11-16)是公告生效日,不可取
        self.assertEqual(data_date, "2026-11-13")
        self.assertEqual(len(holdings), 29)
        by_code = {h.code: h for h in holdings}
        self.assertEqual(by_code["2330"].shares, 70000)
        self.assertAlmostEqual(by_code["2330"].weight, 10.3)
        self.assertEqual(by_code["2330"].name, "台積電")
        self.assertAlmostEqual(meta["scale"], 1600504141.0)
        self.assertAlmostEqual(meta["units"], 149650000.0)
        self.assertAlmostEqual(meta["nav_per_unit"], 10.69)
        # 受益人數 0 + 日期 1900-01-01 = 未揭露
        self.assertIsNone(meta["holders"])

    def test_name_mismatch_rejected(self):
        e = _entries("tradeinfo_00413A.json")
        with self.assertRaises(AdapterError):
            esun.parse_trade_info(e, "00413A", "主動玉山其他基金")

    def test_missing_stock_table_rejected(self):
        e = copy.deepcopy(_entries("tradeinfo_00413A.json"))
        e["DynamicTableData"] = []
        with self.assertRaises(AdapterError):
            esun.parse_trade_info(e, "00413A")

    def test_column_change_rejected(self):
        e = copy.deepcopy(_entries("tradeinfo_00413A.json"))
        e["DynamicTableData"][0]["Columns"][3]["Name"] = "比重"
        with self.assertRaises(AdapterError):
            esun.parse_trade_info(e, "00413A")

    def test_registered(self):
        self.assertIn("esun", ADAPTERS)


if __name__ == "__main__":
    unittest.main()
