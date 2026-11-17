# -*- coding: utf-8 -*-
"""registry 固定測資:ETF 清單偵測/海外分類/unsupported 判定。
執行:python3 -m unittest discover -s tests -q
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import registry

FIXTURE = Path(__file__).parent / "fixtures" / "twse_stock_day_all.json"


def load_rows():
    return json.loads(FIXTURE.read_text())


class DetectTests(unittest.TestCase):
    def test_detect_etfs_filters_00xxxA(self):
        etfs = registry.detect_etfs(load_rows())
        codes = {e["code"] for e in etfs}
        self.assertIn("00981A", codes)
        self.assertNotIn("0050", codes)
        self.assertTrue(all(len(c) == 6 and c.endswith("A") for c in codes))
        self.assertEqual(len(codes), 29)

    def test_foreign_classified(self):
        etfs = {e["code"]: e for e in registry.detect_etfs(load_rows())}
        self.assertEqual(etfs["00988A"]["market"], "foreign")  # 主動統一全球創新
        self.assertEqual(etfs["00402A"]["market"], "foreign")  # 主動安聯美國科技
        self.assertEqual(etfs["00983A"]["market"], "foreign")  # 中信ARK創新實持美股
        self.assertEqual(etfs["00981A"]["market"], "tw")

    def test_issuer_and_adapter_mapping(self):
        etfs = {e["code"]: e for e in registry.detect_etfs(load_rows())}
        self.assertEqual(etfs["00981A"]["issuer"], "統一")
        self.assertEqual(etfs["00991A"]["adapter"], "fuhhwa")
        self.assertEqual(etfs["00405A"]["adapter"], "fubon")


class RegistryFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "etf_registry.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_code_unsupported(self):
        # load_and_update 不再落盤(見 opt#7):呼叫端要自己決定何時 save_registry,
        # 這裡手動存檔模擬「兩次獨立執行」。
        fetched = registry.detect_etfs(load_rows())
        fetched.append({"code": "00998A", "name": "主動未知投信基金", "market": "tw"})
        reg = registry.load_and_update(self.path, fetched)
        self.assertEqual(reg["00998A"]["status"], "unsupported")
        self.assertEqual(reg["00981A"]["status"], "active")
        registry.save_registry(self.path, reg)
        reg2 = registry.load_and_update(self.path, fetched)
        self.assertEqual(reg2["00998A"]["status"], "unsupported")
        self.assertEqual(len(reg2), len(reg))

    def test_load_and_update_does_not_write(self):
        """純記憶體操作:不呼叫 save_registry 就不該有任何檔案落地。"""
        fetched = registry.detect_etfs(load_rows())
        registry.load_and_update(self.path, fetched)
        self.assertFalse(self.path.exists(),
                         "load_and_update 不應自行落盤(整批失敗前不可寫入 registry)")

    def test_manual_override_preserved(self):
        fetched = registry.detect_etfs(load_rows())
        reg = registry.load_and_update(self.path, fetched)
        reg["00981A"]["market"] = "foreign"  # 模擬手動覆寫
        registry.save_registry(self.path, reg)
        reg2 = registry.load_and_update(self.path, fetched)
        self.assertEqual(reg2["00981A"]["market"], "foreign")


if __name__ == "__main__":
    unittest.main()


class ReclassifyTests(unittest.TestCase):
    """名稱看不出海外型時,以實際持股的台股權重為準(00990A 類案例)。"""

    def _reg(self, tmp):
        p = Path(tmp) / "reg.json"
        p.write_text(json.dumps({
            "00981A": {"code": "00981A", "name": "主動統一台股增長", "market": "tw"},
            "00990A": {"code": "00990A", "name": "主動元大AI新經濟", "market": "tw"},
        }, ensure_ascii=False))
        return p

    def test_foreign_heavy_etf_demoted(self):
        import tempfile
        from adapters.base import Holding
        with tempfile.TemporaryDirectory() as tmp:
            p = self._reg(tmp)
            results = {
                "00981A": {"status": "ok", "holdings": [
                    Holding("2330", "台積電", 100, 60.0),
                    Holding("2454", "聯發科", 100, 25.0)]},
                "00990A": {"status": "ok", "holdings": [
                    Holding("LITE US", "LUMENTUM", 100, 60.0),
                    Holding("2330", "台積電", 100, 18.0)]},
            }
            reg = json.loads(p.read_text())
            w = registry.reclassify_by_holdings(p, reg, results)
            # reclassify_by_holdings 不再落盤(見 opt#7),改判結果只反映在傳入的
            # 記憶體物件裡;呼叫端要另外呼叫 save_registry 才會寫檔。
            self.assertEqual(reg["00981A"]["market"], "tw")
            self.assertEqual(reg["00990A"]["market"], "foreign")
            self.assertAlmostEqual(w["00990A"], 18.0, places=1)

    def test_reclassify_does_not_write(self):
        import tempfile
        from adapters.base import Holding
        with tempfile.TemporaryDirectory() as tmp:
            p = self._reg(tmp)
            before = p.read_text()
            reg = json.loads(before)
            results = {"00990A": {"status": "ok", "holdings": [
                Holding("LITE US", "LUMENTUM", 100, 60.0),
                Holding("2330", "台積電", 100, 18.0)]}}
            registry.reclassify_by_holdings(p, reg, results)
            self.assertEqual(p.read_text(), before,
                             "reclassify_by_holdings 不應自行落盤")

    def test_tw_weight_ignores_foreign_codes(self):
        from adapters.base import Holding
        self.assertAlmostEqual(registry.tw_weight([
            Holding("2330", "台積電", 1, 10.0),
            Holding("TSLA US", "TESLA", 1, 5.0),
            Holding("00878", "國泰永續高股息", 1, 2.0)]), 12.0, places=1)


class StatusDerivationTests(unittest.TestCase):
    """補完 adapter 後,既有 ETF 的 status 必須自動由 unsupported 轉 active。"""

    def test_status_refreshes_when_adapter_implemented(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reg.json"
            p.write_text(json.dumps({"00980A": {
                "code": "00980A", "name": "主動野村臺灣優選", "market": "tw",
                "issuer": "野村", "adapter": "nomura", "status": "unsupported"}},
                ensure_ascii=False))
            reg = registry.load_and_update(p, [])
            self.assertEqual(reg["00980A"]["status"], "active")

    def test_disabled_is_preserved(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reg.json"
            p.write_text(json.dumps({"00981A": {
                "code": "00981A", "name": "主動統一台股增長", "market": "tw",
                "issuer": "統一", "adapter": "president", "status": "disabled"}},
                ensure_ascii=False))
            reg = registry.load_and_update(p, [])
            self.assertEqual(reg["00981A"]["status"], "disabled")

    def test_empty_adapter_backfilled_when_issuer_added(self):
        """偵測時投信未在對照表 → issuer/adapter 為空;對照表補上後要自動接上。"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reg.json"
            p.write_text(json.dumps({"00413A": {
                "code": "00413A", "name": "主動玉山關鍵科技", "market": "tw",
                "issuer": "", "adapter": "", "status": "unsupported"}},
                ensure_ascii=False))
            reg = registry.load_and_update(p, [])
            self.assertEqual(reg["00413A"]["issuer"], "玉山")
            self.assertEqual(reg["00413A"]["adapter"], "esun")
            self.assertEqual(reg["00413A"]["status"], "active")


class ReclassifyUpdatesInMemoryTests(unittest.TestCase):
    """改判必須改到傳入的 reg 本身,否則本次執行的 active.json 仍是舊分類。"""

    def test_in_memory_reg_is_mutated(self):
        import tempfile
        from adapters.base import Holding
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reg.json"
            reg = {"00986A": {"code": "00986A", "name": "主動台新龍頭成長",
                              "market": "tw"}}
            p.write_text(json.dumps(reg, ensure_ascii=False))
            results = {"00986A": {"status": "ok", "holdings": [
                Holding("MU US", "MICRON", 1, 70.0),
                Holding("2330", "台積電", 1, 8.9)]}}
            registry.reclassify_by_holdings(p, reg, results)
            self.assertEqual(reg["00986A"]["market"], "foreign")
            self.assertAlmostEqual(reg["00986A"]["tw_weight"], 8.9, places=1)


class SaveRegistryTests(unittest.TestCase):
    """opt#7:registry 寫入要原子化,且只在明確呼叫 save_registry 時才落盤——
    不可在整批持股是否成功判定之前就先寫入(review 明確點名的問題)。
    """

    def test_save_registry_writes_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reg.json"
            registry.save_registry(p, {"00981A": {"code": "00981A", "market": "tw"}})
            self.assertEqual(json.loads(p.read_text())["00981A"]["market"], "tw")

    def test_save_registry_is_atomic_no_tmp_leftover(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "reg.json"
            registry.save_registry(p, {"A": {"code": "A"}})
            leftovers = list(Path(tmp).glob("*.tmp"))
            self.assertEqual(leftovers, [], "不應留下暫存檔")

    def test_save_registry_creates_parent_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "nested" / "reg.json"
            registry.save_registry(p, {"A": {"code": "A"}})
            self.assertTrue(p.exists())
