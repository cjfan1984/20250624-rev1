from __future__ import annotations

import argparse
import ast
import json
import math
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo


VERSION = "V0.2"
DEFAULT_WORKBOOK_ID = "1y4UIifDu1WaRQSLPxMFdBhsXwrfCyt_Kmu555q4mea0"
ORIGINAL_WORKBOOK_ID = "1a01ljnRehIEQO-LecUEIhZGGSIhN0ABBmots6ToN6AE"
SETTINGS_SHEET = "PY_系统设置"
FIELDS_SHEET = "PY_字段配置"
FORMULAS_SHEET = "PY_公式配置"
LOG_SHEET = "PY_运行日志"
TEST_SHEET = "PY_测试结果"
CONFIG_HEADER_ROW = 4
SOURCE_HEADER_ROW = 5
FALSE_VALUES = {"", "0", "false", "no", "否", "停用", "disabled", "关"}
TRUE_VALUES = {"1", "true", "yes", "是", "启用", "enabled", "开"}
FIELD_REF = re.compile(r"\[([^\[\]]+)\]")


class ConfigError(ValueError):
    """The visible spreadsheet configuration is inconsistent."""


class MissingInput(ValueError):
    """A formula depends on an input that is currently blank."""

    def __init__(self, field: str):
        super().__init__(f"缺少字段 [{field}]")
        self.field = field


@dataclass(frozen=True)
class FieldSpec:
    mode: str
    code: str
    name: str
    source_sheet: str
    role: str
    data_type: str
    enabled: bool
    editable: bool
    required: bool
    description: str = ""


@dataclass(frozen=True)
class Rule:
    mode: str
    order: int
    output: str
    expression: str
    enabled: bool
    version: str = VERSION
    unit: str = ""
    description: str = ""


@dataclass
class Calculation:
    values: dict[str, Any]
    status: str
    missing: list[str]
    errors: list[str]


def is_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() not in FALSE_VALUES


def is_yes(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in TRUE_VALUES


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_mode(value: Any) -> str:
    text = clean_text(value)
    aliases = {
        "cross": "跨境",
        "跨境店": "跨境",
        "local": "本土",
        "本土店": "本土",
        "all": "全部",
    }
    return aliases.get(text.lower(), aliases.get(text, text))


def rows_to_records(values: Sequence[Sequence[Any]], header_row: int) -> list[tuple[int, dict[str, Any]]]:
    if len(values) < header_row:
        return []
    headers = [clean_text(v) for v in values[header_row - 1]]
    records: list[tuple[int, dict[str, Any]]] = []
    for sheet_row, row in enumerate(values[header_row:], start=header_row + 1):
        if not any(clean_text(v) for v in row):
            continue
        record = {
            header: row[index] if index < len(row) else ""
            for index, header in enumerate(headers)
            if header
        }
        records.append((sheet_row, record))
    return records


def settings_from_rows(rows: Iterable[tuple[int, Mapping[str, Any]]]) -> dict[str, str]:
    settings: dict[str, str] = {}
    for _, row in rows:
        key = clean_text(row.get("设置项"))
        if key:
            settings[key] = clean_text(row.get("当前值"))
    return settings


def fields_from_rows(rows: Iterable[tuple[int, Mapping[str, Any]]]) -> list[FieldSpec]:
    fields: list[FieldSpec] = []
    for _, row in rows:
        mode = normalize_mode(row.get("模式"))
        name = clean_text(row.get("字段名称"))
        source_sheet = clean_text(row.get("来源表"))
        if not mode or not name or not source_sheet:
            continue
        fields.append(
            FieldSpec(
                mode=mode,
                code=clean_text(row.get("字段代码")),
                name=name,
                source_sheet=source_sheet,
                role=clean_text(row.get("字段角色")),
                data_type=clean_text(row.get("数据类型")) or "文本",
                enabled=is_enabled(row.get("启用", "是")),
                editable=is_yes(row.get("可编辑")),
                required=is_yes(row.get("必填")),
                description=clean_text(row.get("说明")),
            )
        )
    return fields


def rules_from_rows(rows: Iterable[tuple[int, Mapping[str, Any]]]) -> list[Rule]:
    rules: list[Rule] = []
    for _, row in rows:
        mode = normalize_mode(row.get("模式"))
        output = clean_text(row.get("结果字段") or row.get("输出字段"))
        expression = clean_text(row.get("可见公式（可直接修改）") or row.get("公式（Python读取）"))
        if not mode or not output or not expression or not is_enabled(row.get("启用", "是")):
            continue
        try:
            order = int(float(row.get("顺序", 0)))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"{mode} / {output} 的顺序不是数字") from exc
        rules.append(
            Rule(
                mode=mode,
                order=order,
                output=output,
                expression=expression,
                enabled=True,
                version=clean_text(row.get("版本")) or VERSION,
                unit=clean_text(row.get("单位")),
                description=clean_text(row.get("说明")),
            )
        )
    return sorted(rules, key=lambda item: (item.mode, item.order, item.output))


def coerce_value(value: Any, data_type: str = "") -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    if data_type == "文本":
        return text
    accounting_negative = text.startswith("(") and text.endswith(")")
    if accounting_negative:
        text = text[1:-1].strip()
    normalized = (
        text.replace(",", "")
        .replace("RUB", "")
        .replace("RMB", "")
        .replace("₽", "")
        .replace("¥", "")
        .strip()
    )
    if normalized.endswith("%"):
        try:
            number = float(normalized[:-1]) / 100.0
            return -number if accounting_negative else number
        except ValueError:
            return text
    try:
        number = float(normalized)
        return -number if accounting_negative else number
    except ValueError:
        return text


def round_up_10(value: Any) -> float:
    return math.ceil(float(value) / 10.0) * 10.0


class FormulaEngine:
    """Small, auditable expression evaluator for formulas stored in Google Sheets."""

    _binary = {
        ast.Add: lambda left, right: left + right,
        ast.Sub: lambda left, right: left - right,
        ast.Mult: lambda left, right: left * right,
        ast.Div: lambda left, right: left / right,
        ast.Pow: lambda left, right: left**right,
        ast.Mod: lambda left, right: left % right,
    }
    _unary = {
        ast.UAdd: lambda value: +value,
        ast.USub: lambda value: -value,
        ast.Not: lambda value: not value,
    }
    _compare = {
        ast.Lt: lambda left, right: left < right,
        ast.LtE: lambda left, right: left <= right,
        ast.Gt: lambda left, right: left > right,
        ast.GtE: lambda left, right: left >= right,
        ast.Eq: lambda left, right: left == right,
        ast.NotEq: lambda left, right: left != right,
    }
    _functions = {
        "MIN": min,
        "MAX": max,
        "ABS": abs,
        "ROUND": round,
        "CEIL": math.ceil,
        "FLOOR": math.floor,
        "ROUNDUP10": round_up_10,
        "ROUND_UP_10": round_up_10,
    }

    @staticmethod
    def dependencies(expression: str) -> list[str]:
        return list(dict.fromkeys(clean_text(match) for match in FIELD_REF.findall(expression)))

    def evaluate(self, expression: str, values: Mapping[str, Any]) -> Any:
        alias_to_field: dict[str, str] = {}

        def replace_ref(match: re.Match[str]) -> str:
            field = clean_text(match.group(1))
            alias = f"_field_{len(alias_to_field)}"
            alias_to_field[alias] = field
            return alias

        translated = FIELD_REF.sub(replace_ref, expression)
        try:
            tree = ast.parse(translated, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"公式语法错误：{exc.msg}") from exc
        return self._evaluate_node(tree, values, alias_to_field)

    def _name_value(
        self,
        name: str,
        values: Mapping[str, Any],
        aliases: Mapping[str, str],
    ) -> Any:
        if name in aliases:
            field = aliases[name]
            value = values.get(field)
            if value is None:
                raise MissingInput(field)
            return value
        if name in values:
            value = values.get(name)
            if value is None:
                raise MissingInput(name)
            return value
        if name.upper() == "TRUE":
            return True
        if name.upper() == "FALSE":
            return False
        raise ValueError(f"不允许的名称：{name}")

    def _evaluate_node(
        self,
        node: ast.AST,
        values: Mapping[str, Any],
        aliases: Mapping[str, str],
    ) -> Any:
        if isinstance(node, ast.Expression):
            return self._evaluate_node(node.body, values, aliases)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float, str, bool)) or node.value is None:
                return node.value
            raise ValueError("公式包含不支持的常量")
        if isinstance(node, ast.Name):
            return self._name_value(node.id, values, aliases)
        if isinstance(node, ast.BinOp) and type(node.op) in self._binary:
            left = self._evaluate_node(node.left, values, aliases)
            right = self._evaluate_node(node.right, values, aliases)
            return self._binary[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._unary:
            return self._unary[type(node.op)](self._evaluate_node(node.operand, values, aliases))
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for item in node.values:
                    result = self._evaluate_node(item, values, aliases)
                    if not result:
                        return result
                return result
            if isinstance(node.op, ast.Or):
                for item in node.values:
                    result = self._evaluate_node(item, values, aliases)
                    if result:
                        return result
                return result
        if isinstance(node, ast.Compare):
            left = self._evaluate_node(node.left, values, aliases)
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._evaluate_node(comparator, values, aliases)
                function = self._compare.get(type(operator))
                if function is None:
                    raise ValueError("公式包含不支持的比较符")
                if not function(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            condition = self._evaluate_node(node.test, values, aliases)
            branch = node.body if condition else node.orelse
            return self._evaluate_node(branch, values, aliases)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.keywords:
                raise ValueError("只允许白名单函数，且不允许命名参数")
            function_name = node.func.id.upper()
            if function_name == "IF":
                if len(node.args) != 3:
                    raise ValueError("IF 必须有3个参数")
                condition = self._evaluate_node(node.args[0], values, aliases)
                branch = node.args[1] if condition else node.args[2]
                return self._evaluate_node(branch, values, aliases)
            function = self._functions.get(function_name)
            if function is None:
                raise ValueError(f"不允许的函数：{node.func.id}")
            args = [self._evaluate_node(argument, values, aliases) for argument in node.args]
            return function(*args)
        raise ValueError(f"公式语法不允许：{type(node).__name__}")


def validate_configuration(fields: Sequence[FieldSpec], rules: Sequence[Rule]) -> None:
    enabled_fields = [field for field in fields if field.enabled]
    if not enabled_fields:
        raise ConfigError("PY_字段配置 没有启用字段")
    if not rules:
        raise ConfigError("PY_公式配置 没有启用公式")
    errors: list[str] = []
    for mode in ("跨境", "本土"):
        mode_fields = [field for field in enabled_fields if field.mode == mode]
        mode_rules = [rule for rule in rules if rule.mode == mode and rule.enabled]
        if not mode_fields and not mode_rules:
            continue
        if not mode_fields:
            errors.append(f"{mode} 有启用公式但没有启用字段")
            continue
        if not mode_rules:
            errors.append(f"{mode} 有启用字段但没有启用公式")
            continue
        names = [field.name for field in mode_fields]
        codes = [field.code for field in mode_fields if field.code]
        if len(names) != len(set(names)):
            errors.append(f"{mode} 字段名称重复")
        if len(codes) != len(set(codes)):
            errors.append(f"{mode} 字段代码重复")
        sheets = {field.source_sheet for field in mode_fields}
        if len(sheets) != 1:
            errors.append(f"{mode} 启用字段必须来自同一张源表，当前为 {sorted(sheets)}")
        known = set(names)
        seen_outputs: set[str] = set()
        for rule in mode_rules:
            if rule.output not in known:
                errors.append(f"{mode} 公式输出字段 [{rule.output}] 不在字段配置")
            if rule.output in seen_outputs:
                errors.append(f"{mode} 公式输出字段 [{rule.output}] 重复")
            for dependency in FormulaEngine.dependencies(rule.expression):
                if dependency not in known:
                    errors.append(f"{mode} / {rule.output} 引用了未知字段 [{dependency}]")
                dependency_spec = next((field for field in mode_fields if field.name == dependency), None)
                if dependency_spec and dependency_spec.role == "结果" and dependency not in seen_outputs:
                    errors.append(f"{mode} / {rule.output} 在计算前引用了尚未生成的结果 [{dependency}]")
            seen_outputs.add(rule.output)
    if errors:
        raise ConfigError("；".join(dict.fromkeys(errors)))


def calculate_record(
    raw_record: Mapping[str, Any],
    specs: Sequence[FieldSpec],
    rules: Sequence[Rule],
    engine: FormulaEngine | None = None,
) -> Calculation:
    engine = engine or FormulaEngine()
    values = {
        spec.name: coerce_value(raw_record.get(spec.name), spec.data_type)
        for spec in specs
        if spec.enabled
    }
    required = [
        spec.name
        for spec in specs
        if spec.enabled and spec.required and spec.role != "结果"
    ]
    missing = [name for name in required if values.get(name) is None]
    if missing:
        return Calculation(values=values, status="待补充", missing=missing, errors=[])
    errors: list[str] = []
    for rule in rules:
        if not rule.enabled:
            continue
        dependencies = FormulaEngine.dependencies(rule.expression)
        blank_dependencies = [name for name in dependencies if values.get(name) is None]
        if blank_dependencies:
            missing.extend(blank_dependencies)
            return Calculation(
                values=values,
                status="待补充",
                missing=list(dict.fromkeys(missing)),
                errors=[],
            )
        try:
            values[rule.output] = engine.evaluate(rule.expression, values)
        except MissingInput as exc:
            missing.append(exc.field)
            return Calculation(
                values=values,
                status="待补充",
                missing=list(dict.fromkeys(missing)),
                errors=[],
            )
        except Exception as exc:  # precise formula context is added here
            values[rule.output] = None
            errors.append(f"{rule.output}: {exc}")
            return Calculation(values=values, status="公式错误", missing=[], errors=errors)
    return Calculation(values=values, status="完整", missing=[], errors=[])


def comparable_number(value: Any) -> float | None:
    converted = coerce_value(value)
    if isinstance(converted, (int, float)) and not isinstance(converted, bool):
        return float(converted)
    return None


def compare_values(python_value: Any, sheet_value: Any, data_type: str, unit: str) -> tuple[Any, str]:
    if python_value is None:
        return "", "待补充"
    if sheet_value is None or sheet_value == "":
        return "", "仅Python"
    python_number = comparable_number(python_value)
    sheet_number = comparable_number(sheet_value)
    if python_number is not None and sheet_number is not None:
        # Source sheets often display percentages to one decimal point and money
        # to two decimals. These tolerances distinguish display rounding from a
        # material formula discrepancy; live runs read unformatted values.
        tolerance = 0.00055 if data_type == "百分比" or unit == "%" else 0.05
        difference = python_number - sheet_number
        return difference, "OK" if abs(difference) <= tolerance else "差异"
    return "", "OK" if clean_text(python_value) == clean_text(sheet_value) else "差异"


def output_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return ""
    return value


def utc_run_id() -> str:
    return os.getenv("GITHUB_RUN_ID") or f"LOCAL-{uuid.uuid4().hex[:10].upper()}"


def now_china() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


def _worksheet_values(book: Any, title: str) -> list[list[Any]]:
    from gspread.utils import ValueRenderOption

    return book.worksheet(title).get_all_values(value_render_option=ValueRenderOption.unformatted)


def _upsert_setting(book: Any, key: str, value: str) -> None:
    worksheet = book.worksheet(SETTINGS_SHEET)
    values = worksheet.get_all_values()
    for row_number, row in enumerate(values, start=1):
        if row and clean_text(row[0]) == key:
            worksheet.update_cell(row_number, 2, value)
            return
    worksheet.append_row([key, value, "系统自动写入", "系统", "最近一次云端运行状态"])


def _ensure_sheet(book: Any, title: str, rows: int, cols: int) -> Any:
    try:
        return book.worksheet(title)
    except Exception:
        return book.add_worksheet(title=title, rows=rows, cols=cols)


def _write_test_results(book: Any, rows: Sequence[Sequence[Any]]) -> None:
    worksheet = _ensure_sheet(book, TEST_SHEET, max(500, len(rows) + 50), 14)
    worksheet.clear()
    worksheet.update(values=[list(row) for row in rows], range_name="A1", value_input_option="RAW")


def _append_logs(book: Any, rows: Sequence[Sequence[Any]]) -> None:
    worksheet = _ensure_sheet(book, LOG_SHEET, 2000, 10)
    existing = worksheet.get_all_values()
    if len(existing) < CONFIG_HEADER_ROW or not existing[CONFIG_HEADER_ROW - 1]:
        worksheet.clear()
        worksheet.update(
            values=[
                [f"PYTHON 运行日志｜{VERSION}"],
                ["说明：每次运行按模式追加一条；不会改价、采购或投放。"],
                [],
                ["运行时间", "运行ID", "模式", "来源表", "处理SKU数", "成功数", "待补数", "异常数", "公式版本", "备注"],
            ],
            range_name="A1",
            value_input_option="RAW",
        )
    if rows:
        worksheet.append_rows([list(row) for row in rows], value_input_option="RAW")


def _column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _apply_results(book: Any, updates: Sequence[tuple[str, int, str, Any]]) -> None:
    if not updates:
        return
    sheet_headers: dict[str, list[str]] = {}
    data: list[dict[str, Any]] = []
    for sheet_name, row_number, field_name, value in updates:
        if sheet_name not in sheet_headers:
            values = book.worksheet(sheet_name).get_all_values()
            sheet_headers[sheet_name] = [clean_text(item) for item in values[SOURCE_HEADER_ROW - 1]]
        headers = sheet_headers[sheet_name]
        if field_name not in headers:
            continue
        column = _column_letter(headers.index(field_name) + 1)
        escaped_sheet = sheet_name.replace("'", "''")
        data.append({"range": f"'{escaped_sheet}'!{column}{row_number}", "values": [[output_cell(value)]]})
    if data:
        book.values_batch_update({"valueInputOption": "RAW", "data": data})


def run_google(sheet_id: str | None = None) -> dict[str, Any]:
    import gspread
    from google.oauth2.service_account import Credentials

    raw_credentials = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw_credentials:
        raise RuntimeError("缺少 GOOGLE_SERVICE_ACCOUNT_JSON；Google Sheet 尚未授权给 GitHub 云端任务")
    try:
        credential_info = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON 不是有效 JSON") from exc
    credentials = Credentials.from_service_account_info(
        credential_info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ],
    )
    workbook_id = sheet_id or os.getenv("LEMON_SHEET_ID") or DEFAULT_WORKBOOK_ID
    book = gspread.authorize(credentials).open_by_key(workbook_id)

    settings = settings_from_rows(rows_to_records(_worksheet_values(book, SETTINGS_SHEET), CONFIG_HEADER_ROW))
    fields = fields_from_rows(rows_to_records(_worksheet_values(book, FIELDS_SHEET), CONFIG_HEADER_ROW))
    rules = rules_from_rows(rows_to_records(_worksheet_values(book, FORMULAS_SHEET), CONFIG_HEADER_ROW))
    validate_configuration(fields, rules)

    if not is_enabled(settings.get("自动化启用", "是")):
        print("自动化总开关为否，本次安全退出")
        return {"status": "disabled", "workbook_id": workbook_id}

    selected = normalize_mode(settings.get("运行范围", "全部"))
    modes = ["跨境", "本土"] if selected in ("", "全部") else [selected]
    invalid_modes = [mode for mode in modes if mode not in {"跨境", "本土"}]
    if invalid_modes:
        raise ConfigError(f"运行范围无效：{invalid_modes}")

    run_mode = clean_text(settings.get("运行方式", "audit")).lower() or "audit"
    allow_writeback = is_yes(settings.get("允许写回结果"))
    protect_original = is_yes(settings.get("保护原表", "是"))
    configured_original = settings.get("原表ID") or ORIGINAL_WORKBOOK_ID
    if run_mode not in {"audit", "apply"}:
        raise ConfigError("运行方式只能是 audit 或 apply")
    if run_mode == "apply" and not allow_writeback:
        raise ConfigError("运行方式为 apply，但“允许写回结果”不是“是”")
    if run_mode == "apply" and protect_original and workbook_id == configured_original:
        raise ConfigError("原表保护已开启，拒绝向正式原表写回 Python 结果")

    timestamp = now_china()
    run_id = utc_run_id()
    formula_version = settings.get("当前公式版本") or max((rule.version for rule in rules), default=VERSION)
    test_rows: list[list[Any]] = [
        [f"PYTHON 测试结果｜{formula_version}"],
        ["说明：逐SKU读取可见配置并与现有表格结果对算；未知值保持空白。"],
        [],
        ["测试时间", "模式", "SKU", "测试项", "表格值", "Python值", "差异", "状态", "缺失字段", "公式版本", "来源行", "备注"],
    ]
    log_rows: list[list[Any]] = []
    writeback: list[tuple[str, int, str, Any]] = []
    summary: dict[str, Any] = {"run_id": run_id, "workbook_id": workbook_id, "run_mode": run_mode, "modes": {}}
    engine = FormulaEngine()

    for mode in modes:
        mode_specs = [field for field in fields if field.enabled and field.mode == mode]
        mode_rules = [rule for rule in rules if rule.enabled and rule.mode == mode]
        source_sheet = next(iter({field.source_sheet for field in mode_specs}))
        source_values = _worksheet_values(book, source_sheet)
        source_records = rows_to_records(source_values, SOURCE_HEADER_ROW)
        result_specs = {field.name: field for field in mode_specs if field.role == "结果"}
        processed = successful = pending = failed = 0

        for sheet_row, source_record in source_records:
            sku = clean_text(source_record.get("SKU"))
            if not sku or sku == "__APP_TEMPLATE__":
                continue
            processed += 1
            calculation = calculate_record(source_record, mode_specs, mode_rules, engine)
            if calculation.status == "完整":
                successful += 1
            elif calculation.status == "待补充":
                pending += 1
            else:
                failed += 1

            missing_text = "、".join(calculation.missing)
            error_text = "；".join(calculation.errors)
            for rule in mode_rules:
                spec = result_specs.get(rule.output)
                data_type = spec.data_type if spec else ""
                sheet_value = coerce_value(source_record.get(rule.output), data_type)
                python_value = calculation.values.get(rule.output)
                if calculation.status == "完整":
                    difference, comparison_status = compare_values(python_value, sheet_value, data_type, rule.unit)
                elif calculation.status == "待补充":
                    difference, comparison_status = "", "待补充"
                else:
                    difference, comparison_status = "", "公式错误"
                test_rows.append(
                    [
                        timestamp,
                        mode,
                        sku,
                        rule.output,
                        output_cell(sheet_value),
                        output_cell(python_value),
                        output_cell(difference),
                        comparison_status,
                        missing_text,
                        rule.version or formula_version,
                        sheet_row,
                        error_text or rule.description,
                    ]
                )
                if run_mode == "apply" and python_value is not None:
                    writeback.append((source_sheet, sheet_row, rule.output, python_value))

        log_rows.append(
            [
                timestamp,
                run_id,
                mode,
                source_sheet,
                processed,
                successful,
                pending,
                failed,
                formula_version,
                "审计对算；未改主表" if run_mode == "audit" else "已按显化配置写回工作副本结果列",
            ]
        )
        summary["modes"][mode] = {
            "source_sheet": source_sheet,
            "processed": processed,
            "successful": successful,
            "pending": pending,
            "failed": failed,
        }

    if run_mode == "apply":
        _apply_results(book, writeback)
    _write_test_results(book, test_rows)
    _append_logs(book, log_rows)
    total_failed = sum(item["failed"] for item in summary["modes"].values())
    total_pending = sum(item["pending"] for item in summary["modes"].values())
    _upsert_setting(book, "最后云端运行", timestamp)
    _upsert_setting(book, "最近运行结果", f"异常 {total_failed}｜待补 {total_pending}｜运行ID {run_id}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def _cross_test_configuration() -> tuple[list[FieldSpec], list[Rule]]:
    inputs = [
        ("当前售价 RUB", "数字"),
        ("汇率 RUB/RMB", "数字"),
        ("产品成本 RMB", "数字"),
        ("CEL物流 RMB", "数字"),
        ("其他固定成本 RMB", "数字"),
        ("最终采用佣金率", "百分比"),
        ("广告率", "百分比"),
        ("促销/积分率", "百分比"),
        ("支付/提现率", "百分比"),
        ("税费率", "百分比"),
        ("目标利润率", "百分比"),
        ("促销底线利润率", "百分比"),
    ]
    outputs = [
        ("销售收入 RMB", "数字"),
        ("固定成本合计 RMB", "数字"),
        ("比例费合计 RMB", "数字"),
        ("模型净利润 RMB", "数字"),
        ("模型利润率", "百分比"),
        ("模型 ROI", "百分比"),
        ("保本售价 RUB", "数字"),
        ("目标售价 RUB", "数字"),
        ("建议售价 RUB", "数字"),
        ("最低促销价 RUB", "数字"),
        ("判断", "文本"),
    ]
    specs = [
        FieldSpec("跨境", f"i{index}", name, "06_跨境SKU核价", "输入", dtype, True, True, True)
        for index, (name, dtype) in enumerate(inputs)
    ] + [
        FieldSpec("跨境", f"o{index}", name, "06_跨境SKU核价", "结果", dtype, True, False, False)
        for index, (name, dtype) in enumerate(outputs)
    ]
    formulas = [
        (10, "销售收入 RMB", "[当前售价 RUB] / [汇率 RUB/RMB]"),
        (20, "固定成本合计 RMB", "[产品成本 RMB] + [CEL物流 RMB] + [其他固定成本 RMB]"),
        (30, "比例费合计 RMB", "[销售收入 RMB] * ([最终采用佣金率] + [广告率] + [促销/积分率] + [支付/提现率] + [税费率])"),
        (40, "模型净利润 RMB", "[销售收入 RMB] - [固定成本合计 RMB] - [比例费合计 RMB]"),
        (50, "模型利润率", "[模型净利润 RMB] / [销售收入 RMB]"),
        (60, "模型 ROI", "[模型净利润 RMB] / [固定成本合计 RMB]"),
        (70, "保本售价 RUB", "[固定成本合计 RMB] / (1 - [最终采用佣金率] - [广告率] - [促销/积分率] - [支付/提现率] - [税费率]) * [汇率 RUB/RMB]"),
        (80, "目标售价 RUB", "[固定成本合计 RMB] / (1 - [最终采用佣金率] - [广告率] - [促销/积分率] - [支付/提现率] - [税费率] - [目标利润率]) * [汇率 RUB/RMB]"),
        (90, "建议售价 RUB", "ROUNDUP10([目标售价 RUB])"),
        (100, "最低促销价 RUB", "[固定成本合计 RMB] / (1 - [最终采用佣金率] - [广告率] - [促销/积分率] - [支付/提现率] - [税费率] - [促销底线利润率]) * [汇率 RUB/RMB]"),
        (110, "判断", 'IF([模型利润率] >= [目标利润率], "可销售", IF([模型利润率] >= [促销底线利润率], "观察", "不建议"))'),
    ]
    rules = [Rule("跨境", order, output, expression, True, VERSION) for order, output, expression in formulas]
    return specs, rules


def self_test() -> None:
    specs, rules = _cross_test_configuration()
    validate_configuration(specs, rules)
    record = {
        "当前售价 RUB": 640,
        "汇率 RUB/RMB": 12.31981,
        "产品成本 RMB": 13.74,
        "CEL物流 RMB": 11.66,
        "其他固定成本 RMB": 2,
        "最终采用佣金率": 0.12,
        "广告率": 0,
        "促销/积分率": 0,
        "支付/提现率": 0.015,
        "税费率": 0,
        "目标利润率": 0.15,
        "促销底线利润率": 0.05,
    }
    result = calculate_record(record, specs, rules)
    assert result.status == "完整", result
    assert abs(result.values["模型净利润 RMB"] - 17.535757937825338) < 1e-8
    assert result.values["建议售价 RUB"] == 480
    assert result.values["判断"] == "可销售"

    missing_record = dict(record)
    missing_record["产品成本 RMB"] = ""
    missing = calculate_record(missing_record, specs, rules)
    assert missing.status == "待补充"
    assert "产品成本 RMB" in missing.missing
    assert missing.values["产品成本 RMB"] is None

    engine = FormulaEngine()
    assert engine.evaluate('IF([a] > 1, "高", "低")', {"a": 2}) == "高"
    try:
        engine.evaluate('__import__("os").system("echo unsafe")', {})
    except ValueError:
        pass
    else:
        raise AssertionError("unsafe expression was not blocked")
    print(f"SELF-TEST OK | {VERSION}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LEMON PROFIT 配置驱动利润核验")
    parser.add_argument("--self-test", action="store_true", help="运行内核与安全测试")
    parser.add_argument("--google", action="store_true", help="读取并更新 Google Sheet 审计页")
    parser.add_argument("--sheet-id", default=None, help="覆盖默认工作副本 ID")
    args = parser.parse_args()
    if not args.self_test and not args.google:
        parser.print_help()
        return
    if args.self_test:
        self_test()
    if args.google:
        run_google(args.sheet_id)


if __name__ == "__main__":
    main()
