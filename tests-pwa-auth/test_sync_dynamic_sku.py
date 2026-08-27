import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "sku-pwa-auth-tools" / "sync_dynamic_sku.py"
spec = importlib.util.spec_from_file_location("sync_dynamic_sku", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(mod)


def row(*, key="0001|测试", sku="测试", stage="MODEL_PROFIT_OK", profit=11, margin=0.1, supplier="待补至3家"):
    return {
        "决策排名": 1,
        "SKU_KEY": key,
        "产品名称/SKU": sku,
        "当前阶段": stage,
        "当前优先级": "A",
        "单件净利润CNY": profit,
        "净利率": margin,
        "实际/核价采购成本CNY": 5,
        "采购价状态": "公开B2B情景价",
        "Ozon目标/当前售价RUB": 500,
        "毛重kg": 0.1,
        "跨境物流": "100 RUB",
        "平台费金额/费率": "20%",
        "候选货源1": supplier,
    }


class DynamicSkuSyncTests(unittest.TestCase):
    def test_or_gate_is_strict_and_uses_or(self):
        self.assertTrue(mod.source_row_to_contract(row(profit=10, margin=0.151), 1)["decisionOrPass"])
        self.assertTrue(mod.source_row_to_contract(row(profit=10.01, margin=0.15), 1)["decisionOrPass"])
        self.assertFalse(mod.source_row_to_contract(row(profit=10, margin=0.15), 1)["decisionOrPass"])

    def test_supplier_placeholder_is_not_url(self):
        record = mod.source_row_to_contract(row(supplier="待补至3家"), 1)
        self.assertEqual(record["supplierUrls"], [])
        record = mod.source_row_to_contract(row(supplier="https://example.com/item"), 1)
        self.assertEqual(record["supplierUrls"], ["https://example.com/item"])

    def test_stop_is_never_profit_rank_eligible(self):
        record = mod.source_row_to_contract(row(stage="STOP", profit=99, margin=0.9), 1)
        self.assertEqual(record["pwaTier"], "STOP_AUDIT")
        self.assertFalse(record["profitRankEligible"])

    def test_master_snapshot_mismatch_fails(self):
        with self.assertRaises(SystemExit):
            mod.validate_master_coverage(["A", "B"], [{"产品名称/SKU": "A"}])
        mod.validate_master_coverage(["A", "B"], [{"产品名称/SKU": "A"}, {"产品名称/SKU": "B"}])

    def test_duplicate_sku_key_fails(self):
        with self.assertRaises(SystemExit):
            mod.build_dataset([row(key="K", sku="A"), row(key="K", sku="B")])

    def test_manifest_does_not_publish_sku_keys_and_hash_is_stable(self):
        records = mod.build_dataset([row(key="0001|A", sku="A"), row(key="0002|B", sku="B", profit=5, margin=0.2)])
        m1 = mod.make_manifest(records, {})
        m2 = mod.make_manifest(records, {r["skuKey"]: r["rowHash"] for r in records})
        self.assertEqual(m1["datasetSha256"], m2["datasetSha256"])
        self.assertEqual(m2["delta"], {"added": 0, "changed": 0, "removed": 0})
        public_text = json.dumps(m1, ensure_ascii=False)
        self.assertNotIn("0001|A", public_text)
        self.assertNotIn("0002|B", public_text)


if __name__ == "__main__":
    unittest.main()
