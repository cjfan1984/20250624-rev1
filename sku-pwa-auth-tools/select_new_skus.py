from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


OZON_SHEET = "OZON官方动态源"
WB_SHEET = "WB官方动态源"
DAILY_SHEET = "每日新品_决策卡数据层"
MASTER_SHEET = "三级SKU主库"
STATE_SCHEMA = "SKU-SOURCE-FINGERPRINT-V1"

DAILY_HEADERS = [
    "主库行", "首次发现日期", "最近研究日期", "一级系统", "产品族", "产品/型号/规格", "尺寸等级",
    "平台", "数据粒度", "Ozon商品ID", "Ozon商品卡", "后台统计周期", "Ozon28天销量",
    "Ozon28天销售额RUB", "成交均价RUB", "趋势%", "日均销量", "日均销售额RUB", "赎回率%",
    "缺货天数", "错失销售RUB", "后台体积L", "前台当前价RUB", "评分", "评价数", "WB证据粒度",
    "WB证据", "货源平台/供应商", "货源链接", "货源匹配级别", "公开参考采购价", "MOQ",
    "净重/产品重量kg", "产品尺寸", "毛重kg", "包装长cm", "包装宽cm", "包装高cm", "体积重kg",
    "计费重kg", "物流渠道", "平台费用", "跨境运费", "利润状态", "预计月销量状态", "当前优先级",
    "当前动作", "缺失字段", "证据完整度", "源数据链接", "最近证据日期", "当日轮换平台",
    "轮换商品证据", "轮换平台结论", "轮换证据链接", "轮换证据日期",
]

HIGH_RISK_TOKENS = (
    "药", "医疗", "保健", "婴儿", "儿童", "食品", "化妆", "香水", "电子烟", "武器", "刀具",
)


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def normalize(value: Any) -> str:
    value = unicodedata.normalize("NFKC", text(value)).lower().replace("×", "x")
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


def direct_product_url(value: Any) -> bool:
    url = text(value)
    return bool(re.match(r"^https://(?:www\.)?ozon\.ru/product/", url, re.I))


def product_id(row: dict[str, Any]) -> str:
    article = text(row.get("货号"))
    url = text(row.get("商品链接"))
    match = re.search(r"(?:-|/)(\d{6,})(?:/|$|\?)", url)
    return match.group(1) if match else article


def canonical_sha(ozon_rows: list[dict[str, Any]], wb_rows: list[dict[str, Any]]) -> str:
    projection = {
        "ozon": [{key: row.get(key) for key in sorted(row)} for row in ozon_rows],
        "wb": [{key: row.get(key) for key in sorted(row)} for row in wb_rows],
    }
    raw = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _wb_match(row: dict[str, Any], wb_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    needles = [normalize(row.get("中文子类目")), normalize(row.get("查询主题")), normalize(row.get("商品名称"))]
    needles = [value for value in needles if value]
    best: tuple[float, dict[str, Any] | None] = (0.0, None)
    for wb in wb_rows:
        candidate = normalize(wb.get("中文产品"))
        if not candidate:
            continue
        scores = []
        for needle in needles:
            if candidate in needle or needle in candidate:
                scores.append(1.0)
            else:
                scores.append(SequenceMatcher(None, needle, candidate).ratio())
        score = max(scores, default=0.0)
        if score > best[0]:
            best = (score, wb)
    return best[1] if best[0] >= 0.72 else None


def _candidate_score(row: dict[str, Any], wb: dict[str, Any] | None) -> float:
    blue = number(row.get("蓝海综合分")) or 0.0
    wb_score = number(wb.get("综合分")) if wb else None
    boost = min(8.0, max(0.0, (wb_score - 70.0) / 4.0)) if wb_score is not None else 0.0
    return round(blue + boost, 2)


def select_candidates(
    ozon_rows: list[dict[str, Any]],
    wb_rows: list[dict[str, Any]],
    *,
    existing_names: list[str],
    existing_urls: list[str],
    existing_ids: list[str],
    max_new: int = 5,
    min_blue_score: float = 72.0,
    min_units: float = 100.0,
) -> list[dict[str, Any]]:
    known_names = [normalize(name) for name in existing_names if normalize(name)]
    known_urls = {text(url) for url in existing_urls if text(url)}
    known_ids = {text(item) for item in existing_ids if text(item)}
    ranked: list[dict[str, Any]] = []
    for row in ozon_rows:
        name = text(row.get("商品名称"))
        url = text(row.get("商品链接"))
        item_id = product_id(row)
        blue = number(row.get("蓝海综合分")) or 0.0
        units = number(row.get("已订购商品_件")) or 0.0
        price = number(row.get("平均购买价格_RUB")) or 0.0
        freight_ratio = number(row.get("CEL运费占售价"))
        risk_text = "|".join(text(row.get(key)) for key in ("产品大类", "中文子类目", "商品名称", "风险提示"))
        if not name or not direct_product_url(url):
            continue
        if blue < min_blue_score or units < min_units or price < 350:
            continue
        if freight_ratio is not None and freight_ratio > 0.55:
            continue
        if any(token in risk_text for token in HIGH_RISK_TOKENS):
            continue
        normalized_name = normalize(name)
        if url in known_urls or (item_id and item_id in known_ids):
            continue
        if any(SequenceMatcher(None, normalized_name, known).ratio() >= 0.94 for known in known_names):
            continue
        wb = _wb_match(row, wb_rows)
        ranked.append(
            {
                "ozon": row,
                "wb": wb,
                "score": _candidate_score(row, wb),
                "productId": item_id,
                "dedupeKey": normalized_name,
            }
        )
    ranked.sort(
        key=lambda item: (
            item["score"],
            number(item["ozon"].get("已订购商品_件")) or 0,
            number(item["ozon"].get("平均购买价格_RUB")) or 0,
        ),
        reverse=True,
    )
    result = []
    families: set[str] = set()
    for candidate in ranked:
        family = normalize(candidate["ozon"].get("中文子类目") or candidate["ozon"].get("查询主题"))
        if family in families:
            continue
        families.add(family)
        result.append(candidate)
        if len(result) >= max_new:
            break
    return result


def _system_for(row: dict[str, Any]) -> str:
    category = text(row.get("产品大类"))
    if "汽车" in category:
        return "S6 汽车维修系统"
    if any(token in category for token in ("工具", "耗材", "标准件")):
        return "S1 工具耗材系统"
    if any(token in category for token in ("家居", "厨房", "收纳")):
        return "S4 家居系统"
    if "宠物" in category:
        return "S5 宠物系统"
    return "S9 程序候选池"


def candidate_to_daily(candidate: dict[str, Any], today: str) -> dict[str, Any]:
    ozon = candidate["ozon"]
    wb = candidate.get("wb")
    item_id = candidate.get("productId") or text(ozon.get("货号"))
    article = text(ozon.get("货号"))
    base_name = text(ozon.get("商品名称"))
    name = f"{base_name}（{article}）" if article and normalize(article) not in normalize(base_name) else base_name
    units = number(ozon.get("已订购商品_件"))
    sales = number(ozon.get("订购金额_RUB"))
    period = text(ozon.get("数据周期")) or "Ozon官方周期"
    wb_evidence = ""
    wb_grain = "无匹配"
    if wb:
        wb_grain = "WB搜索词/产品族，非精确SKU"
        wb_evidence = (
            f"{text(wb.get('中文产品'))}｜搜索量{text(wb.get('月搜索量')) or '待核'}｜"
            f"下单{text(wb.get('下单量')) or '待核'}｜综合分{text(wb.get('综合分')) or '待核'}"
        )
    row = {header: "" for header in DAILY_HEADERS}
    row.update(
        {
            "首次发现日期": today,
            "最近研究日期": today,
            "一级系统": _system_for(ozon),
            "产品族": text(ozon.get("中文子类目")) or text(ozon.get("查询主题")),
            "产品/型号/规格": name,
            "尺寸等级": f"后台体积 {text(ozon.get('商品体积_L')) or '待核'}L；重量/三边模型值不写入事实列",
            "平台": "Ozon＋WB产品族" if wb else "Ozon",
            "数据粒度": "Ozon精确商品链接/后台；WB仅产品族验证" if wb else "Ozon精确商品链接/后台",
            "Ozon商品ID": item_id,
            "Ozon商品卡": text(ozon.get("商品链接")),
            "后台统计周期": period,
            "Ozon28天销量": units,
            "Ozon28天销售额RUB": sales,
            "成交均价RUB": number(ozon.get("平均购买价格_RUB")),
            "趋势%": number(ozon.get("动态_pct")),
            "日均销量": round(units / 28, 2) if units is not None and "28" in period else "",
            "日均销售额RUB": round(sales / 28, 2) if sales is not None and "28" in period else "",
            "赎回率%": number(ozon.get("认购份额_pct")),
            "缺货天数": number(ozon.get("无库存天数")),
            "错失销售RUB": number(ozon.get("已错过销售_RUB")),
            "后台体积L": number(ozon.get("商品体积_L")),
            "WB证据粒度": wb_grain,
            "WB证据": wb_evidence,
            "利润状态": "程序候选：缺正式采购、平台费、实称包装和运费，不计算正式利润",
            "预计月销量状态": "竞品后台需求证据，不等于自营销量预测",
            "当前优先级": "A" if candidate["score"] >= 82 else "B",
            "当前动作": "程序筛选通过｜只补同BOM正式PI、实称包装与平台费用；缺任一项不进入利润发布",
            "缺失字段": "精确BOM、正式采购价/MOQ、单件实称毛重和包装三边、平台费、跨境运费、差评",
            "证据完整度": f"Ozon后台A/精确商品链接A/WB产品族{'B' if wb else 'D'}/供应D/物流D/利润D｜规则分{candidate['score']}",
            "源数据链接": text(ozon.get("商品链接")),
            "最近证据日期": today,
            "当日轮换平台": "程序规则",
            "轮换商品证据": text(ozon.get("源文件")),
            "轮换平台结论": "满足确定性阈值；进入候选池，不自动宣称可上架",
            "轮换证据链接": text(ozon.get("商品链接")),
            "轮换证据日期": today,
        }
    )
    return row


def google_credentials(write: bool = False):
    from google.oauth2.service_account import Credentials

    raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    filename = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets" if write else "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=scopes)
    if filename:
        return Credentials.from_service_account_file(filename, scopes=scopes)
    raise SystemExit("Google credentials missing")


def _records(values: list[list[Any]], header_row: int = 1) -> list[dict[str, Any]]:
    if len(values) < header_row:
        return []
    headers = [text(value).lstrip("\ufeff") for value in values[header_row - 1]]
    return [
        {headers[index]: row[index] if index < len(row) else "" for index in range(len(headers))}
        for row in values[header_row:]
        if any(text(value) for value in row)
    ]


def load_google(spreadsheet_id: str, *, write: bool = False):
    import gspread

    gc = gspread.authorize(google_credentials(write))
    spreadsheet = gc.open_by_key(spreadsheet_id)
    ozon = _records(spreadsheet.worksheet(OZON_SHEET).get_all_values())
    wb = _records(spreadsheet.worksheet(WB_SHEET).get_all_values())
    master_values = spreadsheet.worksheet(MASTER_SHEET).get_all_values()
    master = _records(master_values)
    daily_ws = spreadsheet.worksheet(DAILY_SHEET)
    daily_values = daily_ws.get_all_values()
    daily = _records(daily_values, header_row=3)
    return ozon, wb, master, daily, daily_ws


def existing_evidence(master: list[dict[str, Any]], daily: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    names = [text(row.get("三级SKU")) for row in master] + [text(row.get("产品/型号/规格")) for row in daily]
    urls = [text(row.get("OZON源数据")) for row in master] + [text(row.get("Ozon商品卡")) for row in daily]
    ids = [text(row.get("Ozon商品ID")) for row in daily]
    return names, urls, ids


def read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Zero-GPT deterministic Ozon/WB candidate selector with a source-hash gate.")
    parser.add_argument("--spreadsheet-id", required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    parser.add_argument("--max-new", type=int, default=5)
    parser.add_argument("--min-blue-score", type=float, default=72.0)
    parser.add_argument("--min-units", type=float, default=100.0)
    parser.add_argument("--bootstrap-if-missing", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_new <= 5:
        raise SystemExit("--max-new must be between 1 and 5")

    ozon, wb, master, daily, daily_ws = load_google(args.spreadsheet_id, write=args.apply)
    source_sha = canonical_sha(ozon, wb)
    previous = read_state(args.state)
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    state = {
        "schema": STATE_SCHEMA,
        "sourceSha256": source_sha,
        "updatedAt": now.isoformat(timespec="seconds"),
        "rows": {"ozon": len(ozon), "wb": len(wb)},
    }
    if not previous and args.bootstrap_if_missing:
        write_json(args.state, state)
        status = {"state": "BOOTSTRAPPED", "sourceChanged": False, "applied": 0, "sourceSha256": source_sha}
        write_json(args.status, status)
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return
    if previous.get("sourceSha256") == source_sha:
        status = {"state": "NO_CHANGE", "sourceChanged": False, "applied": 0, "sourceSha256": source_sha}
        write_json(args.status, status)
        print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))
        return

    names, urls, ids = existing_evidence(master, daily)
    selected = select_candidates(
        ozon,
        wb,
        existing_names=names,
        existing_urls=urls,
        existing_ids=ids,
        max_new=args.max_new,
        min_blue_score=args.min_blue_score,
        min_units=args.min_units,
    )
    daily_rows = [candidate_to_daily(candidate, now.date().isoformat()) for candidate in selected]
    if args.apply and daily_rows:
        actual_headers = [text(value) for value in daily_ws.row_values(3)]
        if actual_headers[: len(DAILY_HEADERS)] != DAILY_HEADERS:
            raise SystemExit("daily candidate header contract drifted; refusing write")
        daily_ws.append_rows(
            [[row.get(header, "") for header in DAILY_HEADERS] for row in daily_rows],
            value_input_option="USER_ENTERED",
        )
    if args.apply or not selected:
        write_json(args.state, state)
    status = {
        "state": "APPLIED" if args.apply and selected else "SOURCE_CHANGED_NO_CANDIDATE" if not selected else "CANDIDATES_READY",
        "sourceChanged": True,
        "selected": len(selected),
        "applied": len(selected) if args.apply else 0,
        "sourceSha256": source_sha,
        "candidates": [
            {
                "productId": item.get("productId"),
                "name": text(item["ozon"].get("商品名称")),
                "family": text(item["ozon"].get("中文子类目")),
                "score": item["score"],
                "url": text(item["ozon"].get("商品链接")),
            }
            for item in selected
        ],
    }
    write_json(args.status, status)
    print(json.dumps(status, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
