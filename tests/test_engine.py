import unittest

from lemon_profit_cloud import (
    ConfigError,
    FieldSpec,
    FormulaEngine,
    Rule,
    calculate_record,
    validate_configuration,
)


class FormulaEngineTests(unittest.TestCase):
    def test_visible_field_references_and_lazy_if(self):
        engine = FormulaEngine()
        value = engine.evaluate(
            'IF([利润率] >= [目标利润率], "可销售", 1 / [空字段])',
            {"利润率": 0.2, "目标利润率": 0.15, "空字段": None},
        )
        self.assertEqual(value, "可销售")

    def test_round_up_10(self):
        self.assertEqual(FormulaEngine().evaluate("ROUNDUP10([价格])", {"价格": 472.12}), 480)

    def test_unsafe_expression_is_blocked(self):
        with self.assertRaises(ValueError):
            FormulaEngine().evaluate('__import__("os")', {})


class ConfigurationTests(unittest.TestCase):
    def test_unknown_dependency_is_rejected(self):
        fields = [FieldSpec("跨境", "price", "售价", "源表", "输入", "数字", True, True, True)]
        rules = [Rule("跨境", 10, "结果", "[不存在] + 1", True)]
        with self.assertRaises(ConfigError):
            validate_configuration(fields, rules)

    def test_blank_required_value_is_not_zero(self):
        fields = [
            FieldSpec("跨境", "cost", "成本", "源表", "输入", "数字", True, True, True),
            FieldSpec("跨境", "result", "结果", "源表", "结果", "数字", True, False, False),
        ]
        rules = [Rule("跨境", 10, "结果", "[成本] + 1", True)]
        result = calculate_record({"成本": ""}, fields, rules)
        self.assertEqual(result.status, "待补充")
        self.assertIsNone(result.values["成本"])


if __name__ == "__main__":
    unittest.main()
