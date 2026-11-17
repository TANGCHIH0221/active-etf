# -*- coding: utf-8 -*-
"""render_html 結構斷言(非像素):AUTO:DATE、三分頁、資料內嵌、無外部依賴。"""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import render_html

ACTIVE = {
    "updated": "2026-08-05",
    "etfs": {
        "00981A": {"name": "主動統一台股增長", "issuer": "統一", "status": "ok",
                   "data_date": "2026-08-05", "scale": 3.07e11, "holders": 1052004,
                   "nav": 27.75, "close": 27.63, "premium_pct": -0.42,
                   "holdings": [{"code": "2330", "name": "台積電",
                                 "shares": 100, "weight": 20.0}],
                   "events": [{"code": "2330", "name": "台積電", "type": "INCREASE",
                               "weight": 20.0, "shares": 100, "prev_weight": 19.0,
                               "weight_delta": 1.0, "shares_delta_pct": 8.0}]},
        "00999A": {"name": "主動野村臺灣高息", "issuer": "野村", "status": "unsupported",
                   "data_date": None, "scale": None, "holders": None, "nav": None,
                   "close": None, "premium_pct": None, "holdings": [], "events": []},
    },
    "stocks": {"2330": {"name": "台積電", "total_weight": 20.0,
                        "etfs": [{"etf": "00981A", "weight": 20.0, "shares": 100}],
                        "recent_events": [{"etf": "00981A", "type": "INCREASE",
                                           "date": "2026-08-05"}]}},
    "consensus": {"increase": [], "decrease": []},
    "crosslinks": {"dispo": ["2330"], "notes": {}},
}


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.html = render_html.render(ACTIVE, {})

    def test_auto_date_marker_and_title(self):
        self.assertIn("<!-- AUTO:DATE:2026-08-05 -->", self.html)
        self.assertIn("<title>台股主動式ETF追蹤 | Updated 2026-08-05</title>", self.html)

    def test_three_tabs(self):
        for label in ("今日異動", "各檔 ETF", "個股反查"):
            self.assertIn(label, self.html)
        self.assertEqual(self.html.count("<section"), 4)

    def test_data_embedded(self):
        self.assertIn("const DATA = {", self.html)
        self.assertIn("主動統一台股增長", self.html)

    def test_self_contained(self):
        # 不得有任何外部資源(CSP/離線可用)
        self.assertEqual(re.findall(r'<(?:script|link)[^>]+(?:src|href)="http', self.html), [])

    def test_kpi_counts_only_tracked(self):
        # 追蹤 ETF 數只算有持股者(00999A unsupported 不計)
        self.assertRegex(self.html, r'<div class="n">1</div><div class="l">追蹤 ETF</div>')


if __name__ == "__main__":
    unittest.main()


class EscapingTests(unittest.TestCase):
    """opt#4:外部字串(投信網站來的個股/ETF 名稱)要一律 escape 再塞進 innerHTML。

    這些名稱不是使用者可控輸入,不是可被外部連結利用的漏洞,但仍是「未跳脫
    路徑」——某天來源網站的名稱裡出現 < 或 & 就會破壞 DOM 結構甚至被解讀成標籤。
    """

    def setUp(self):
        self.js = render_html.JS

    def test_stock_cell_escapes_name(self):
        """stockCell() 是全站顯示個股名稱的核心函式(共識榜/排行/反查/ETF卡片
        完整持股表都靠它),name 參數必須經過 esc()。"""
        m = re.search(r"function stockCell\(code, name\) \{(.*?)\n\}",
                      self.js, re.S)
        self.assertIsNotNone(m, "找不到 stockCell 定義")
        body = m.group(1)
        self.assertIn("esc(name", body,
                     "stockCell 的 name 必須用 esc() 包住,否則六個呼叫點都沒防護")

    def test_holding_bar_name_escaped(self):
        """etfCard() 權重長條上的個股名稱(h.name)。"""
        self.assertIn("esc(h.name)", self.js)

    def test_etf_card_title_name_escaped(self):
        """etfCard() 卡片標題的 ETF 名稱(e.name)。"""
        m = re.search(r"function etfCard\(code, e\) \{(.*?)\n\}", self.js, re.S)
        self.assertIsNotNone(m, "找不到 etfCard 定義")
        self.assertIn("esc(e.name)", m.group(1))


class KeyboardAccessibilityTests(unittest.TestCase):
    """opt#4:chip 原本是可點擊 <span>,鍵盤使用者無法 Tab 到/用 Enter 切換;
    輸入框只有 placeholder,螢幕閱讀器唸不出用途(輸入後 placeholder 消失,
    使用者連自己填了什麼欄位都不知道)。
    """

    def setUp(self):
        self.html = render_html.render(ACTIVE, {})
        self.js = render_html.JS

    def test_chips_are_buttons_not_spans(self):
        # 用 data-t= 鎖定「篩選 chip 本身」,避免與 .chip-hint 那個純文字提示
        # (class 也以 "chip" 開頭)誤判成同一種元素。
        self.assertNotIn('<span class="chip" data-t=', self.html)
        self.assertIn('<button type="button" class="chip" data-t="ADD"', self.html)

    def test_chips_have_aria_pressed(self):
        self.assertRegex(self.html, r'<button type="button" class="chip[^"]*" '
                                    r'data-t="ADD" aria-pressed="(true|false)"')

    def test_default_filter_chip_pressed_true(self):
        # DEFAULT_FILTER = "INCREASE"
        self.assertRegex(self.html,
                         r'data-t="INCREASE" aria-pressed="true"')
        self.assertRegex(self.html,
                         r'data-t="ADD" aria-pressed="false"')

    def test_click_handler_updates_aria_pressed(self):
        self.assertIn("aria-pressed", self.js)
        self.assertIn("setAttribute('aria-pressed'", self.js)

    def test_search_inputs_have_labels(self):
        self.assertIn('<label for="evQ"', self.html)
        self.assertIn('<label for="lookupQ"', self.html)
        self.assertIn('<label for="etfSel"', self.html)
