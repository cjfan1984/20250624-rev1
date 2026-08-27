from __future__ import annotations

import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse

# Canonical 25-module roadmap shown in the PWA automation center.
# Core phase uses six business bundles, while the registry keeps all 25 capabilities visible.
MODULE_REGISTRY = [
    {"id":"dynamic_ingest","name":"动态SKU入库引擎","number":1,"phase":1,"status":"active","bundle":1},
    {"id":"gap_radar","name":"数据缺口雷达","number":2,"phase":1,"status":"active","bundle":2},
    {"id":"auto_queue","name":"自动补数队列","number":3,"phase":1,"status":"active","bundle":3},
    {"id":"profit_recalc","name":"利润实时重算","number":4,"phase":1,"status":"active","bundle":4},
    {"id":"structural_stop","name":"极限利润判死引擎","number":5,"phase":1,"status":"active","bundle":4},
    {"id":"supplier_compare","name":"供应商比价引擎","number":6,"phase":1,"status":"active","bundle":5},
    {"id":"competitor_refresh","name":"竞品自动换新","number":7,"phase":1,"status":"active","bundle":5},
    {"id":"image_maintenance","name":"图片自动获取/整理","number":8,"phase":1,"status":"active","bundle":5},
    {"id":"data_quality","name":"数据质量审计","number":9,"phase":2,"status":"queued"},
    {"id":"change_log","name":"SKU变更日志","number":10,"phase":2,"status":"queued"},
    {"id":"incremental_sync","name":"自动版本/增量同步","number":11,"phase":1,"status":"active","bundle":6},
    {"id":"local_cross_route","name":"本土/跨境双路线决策","number":12,"phase":2,"status":"queued"},
    {"id":"price_sensitivity","name":"价格敏感性模拟器","number":13,"phase":2,"status":"queued"},
    {"id":"purchase_cap","name":"采购价反推器","number":14,"phase":2,"status":"queued"},
    {"id":"moq_cash","name":"MOQ资金占用模型","number":15,"phase":2,"status":"queued"},
    {"id":"inventory_risk","name":"库存/现金流风险评分","number":16,"phase":2,"status":"queued"},
    {"id":"sales_trend","name":"销量趋势/爆品预警","number":17,"phase":3,"status":"queued"},
    {"id":"rank_change","name":"排名变化检测","number":18,"phase":3,"status":"queued"},
    {"id":"anomaly_detection","name":"异常检测","number":19,"phase":3,"status":"queued"},
    {"id":"similar_cluster","name":"相似SKU聚类","number":20,"phase":3,"status":"queued"},
    {"id":"spec_matrix","name":"规格矩阵机会发现","number":21,"phase":3,"status":"queued"},
    {"id":"supply_reuse","name":"供应链复用分析","number":22,"phase":3,"status":"queued"},
    {"id":"review_pain","name":"评论痛点统计","number":23,"phase":4,"status":"queued"},
    {"id":"qc_generator","name":"QC自动生成器","number":24,"phase":4,"status":"queued"},
    {"id":"next_action","name":"自动任务生成器","number":25,"phase":2,"status":"queued"},
]

CORE_BUNDLES = [
    {"bundle":1,"name":"动态SKU入库","modules":[1]},
    {"bundle":2,"name":"缺口雷达","modules":[2]},
    {"bundle":3,"name":"自动补数队列","modules":[3]},
    {"bundle":4,"name":"利润/极限判死","modules":[4,5]},
    {"bundle":5,"name":"供应商/竞品自动维护","modules":[6,7,8]},
    {"bundle":6,"name":"增量PWA同步","modules":[11]},
]

DEFAULT_PARAMS = {
    "rub_per_cny": 12.31981,
    "platform_rate": 0.215,
    "fixed_fee_cny": 3.0,
    "profit_threshold_cny": 10.0,
    "margin_threshold": 0.15,
    "target_margin": 0.20,
}

PENDING_TOKENS = ("待补", "待核", "待研究", "待询价", "缺", "未闭环", "未取得", "待建模")
SEARCH_URL_TOKENS = ("/search/", "search.aspx", "search_result", "search/?text")


def text(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            return None
        return float(value)
    s = str(value).strip().replace(",", "").replace("¥", "").replace("RUB", "")
    is_pct = s.endswith("%")
    s = s.rstrip("%").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100.0 if is_pct else v


def is_pending(value: Any) -> bool:
    s = text(value)
    return bool(s and any(t in s for t in PENDING_TOKENS))


def is_url(value: Any) -> bool:
    s = text(value)
    return bool(s and re.match(r"^https?://", s, re.I))


def is_direct_product_url(value: Any) -> bool:
    s = text(value)
    if not is_url(s):
        return False
    low = s.lower()
    return not any(token in low for token in SEARCH_URL_TOKENS)


def normalize_identity(value: Any) -> str:
    s = unicodedata.normalize("NFKC", text(value) or "").lower()
    s = s.replace("×", "x").replace("＊", "x")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[^0-9a-z\u4e00-\u9fff.+x/-]+", "", s)
    return s


def identity_similarity(a: Any, b: Any) -> float:
    na, nb = normalize_identity(a), normalize_identity(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def cel_rub(price_rub: float | None, weight_kg: float | None) -> float | None:
    if price_rub is None or weight_kg is None:
        return None
    if weight_kg <= 0.5 and price_rub <= 1500:
        return round(78 + 0.287 * weight_kg * 1000, 3)
    return round(161 + 465 * weight_kg, 3)


def profit_model(price_rub: float | None, cost_cny: float | None, weight_kg: float | None, params: dict[str, float] | None = None) -> dict[str, Any]:
    p = {**DEFAULT_PARAMS, **(params or {})}
    if price_rub is None or weight_kg is None:
        return {"calculable": False, "reason": "缺Ozon价" if price_rub is None else "缺重量"}
    freight_rub = cel_rub(price_rub, weight_kg)
    revenue_cny = price_rub / p["rub_per_cny"]
    zero_profit = revenue_cny * (1 - p["platform_rate"]) - freight_rub / p["rub_per_cny"] - p["fixed_fee_cny"]
    zero_margin = zero_profit / revenue_cny if revenue_cny else None
    structural_stop = not (zero_profit > p["profit_threshold_cny"] or (zero_margin is not None and zero_margin > p["margin_threshold"]))
    purchase_cap_15 = revenue_cny * (1 - p["platform_rate"] - p["margin_threshold"]) - freight_rub / p["rub_per_cny"] - p["fixed_fee_cny"]
    result = {
        "calculable": cost_cny is not None,
        "celRub": freight_rub,
        "revenueCny": round(revenue_cny, 4),
        "zeroCostProfit": round(zero_profit, 2),
        "zeroCostMargin": round(zero_margin, 4) if zero_margin is not None else None,
        "structuralStop": structural_stop,
        "purchaseCap15": round(purchase_cap_15, 2),
    }
    if cost_cny is not None:
        profit = zero_profit - cost_cny
        margin = profit / revenue_cny if revenue_cny else None
        result.update({
            "profit": round(profit, 2),
            "margin": round(margin, 4) if margin is not None else None,
            "orPass": bool(profit > p["profit_threshold_cny"] or (margin is not None and margin > p["margin_threshold"])),
        })
    return result


def local_profit(price_rub: float | None, cost_cny: float | None, rub_per_cny: float = DEFAULT_PARAMS["rub_per_cny"]) -> float | None:
    if price_rub is None or cost_cny is None:
        return None
    price_cny = price_rub / rub_per_cny
    return round(price_cny * 1.2 - cost_cny / 0.35, 2)


def gap_radar(source: dict[str, Any]) -> dict[str, Any]:
    checks = [
        ("purchaseCost", source.get("实际/核价采购成本CNY"), "采购价"),
        ("grossWeight", source.get("毛重kg"), "毛重"),
        ("packageL", source.get("包装长cm"), "包装长"),
        ("packageW", source.get("包装宽cm"), "包装宽"),
        ("packageH", source.get("包装高cm"), "包装高"),
        ("ozonPrice", source.get("Ozon目标/当前售价RUB"), "Ozon价"),
        ("wbPrice", source.get("WB目标/当前售价RUB"), "WB价"),
        ("supplier1", source.get("候选货源1"), "货源1"),
        ("supplier2", source.get("候选货源2"), "货源2"),
        ("supplier3", source.get("候选货源3"), "货源3"),
        ("ozonCompetitor", source.get("Ozon有效竞品链接"), "Ozon竞品"),
        ("wbCompetitor", source.get("WB有效竞品链接"), "WB竞品"),
        ("image", source.get("PWA参考图URL"), "参考图"),
    ]
    gaps=[]
    present=0
    for key,value,label in checks:
        ok = is_direct_product_url(value) if key in {"supplier1","supplier2","supplier3","ozonCompetitor","wbCompetitor"} else (number(value) is not None if key in {"purchaseCost","grossWeight","packageL","packageW","packageH","ozonPrice","wbPrice"} else bool(text(value)))
        if ok:
            present += 1
        else:
            gaps.append({"key":key,"label":label})
    completion = round(present/len(checks)*100,1)
    critical_order = ["采购价","毛重","Ozon价","Ozon竞品","货源1","包装长","包装宽","包装高","WB竞品","WB价","货源2","货源3","参考图"]
    gap_labels={g["label"] for g in gaps}
    blocker=next((x for x in critical_order if x in gap_labels),None)
    return {"completion":completion,"gapCount":len(gaps),"gaps":gaps,"primaryBlocker":blocker}


def queue_score(source: dict[str, Any], gaps: dict[str, Any], profit: dict[str, Any]) -> dict[str, Any]:
    stage=text(source.get("当前阶段")) or ""
    if stage == "STOP" or profit.get("structuralStop") is True:
        return {"score":-999,"level":"暂停","reason":"结构性STOP/已停止"}
    priority=(text(source.get("当前优先级")) or "C").upper()
    base={"S":70,"A+":65,"A":60,"B":45,"C":25}.get(priority,20)
    oz=number(source.get("Ozon28天件数")) or number(source.get("Ozon预计月销量")) or 0
    wb=number(source.get("WB30天下单")) or 0
    demand=min(25, math.log10(max(1,oz+wb))*8)
    gap_bonus=max(0,15-min(15,gaps["gapCount"]))
    profit_bonus=20 if profit.get("orPass") else (10 if profit.get("calculable") else 0)
    score=round(base+demand+gap_bonus+profit_bonus,1)
    level="P1" if score>=75 else "P2" if score>=55 else "P3"
    reason=f"{priority}｜需求分{demand:.1f}｜缺口{gaps['gapCount']}｜利润{'通过' if profit.get('orPass') else '待补'}"
    return {"score":score,"level":level,"reason":reason}


def source_competitor_state(source: dict[str, Any]) -> dict[str, Any]:
    suppliers=[source.get("候选货源1"),source.get("候选货源2"),source.get("候选货源3")]
    supplier_urls=[text(x) for x in suppliers if is_direct_product_url(x)]
    oz=text(source.get("Ozon有效竞品链接")) if is_direct_product_url(source.get("Ozon有效竞品链接")) else None
    wb=text(source.get("WB有效竞品链接")) if is_direct_product_url(source.get("WB有效竞品链接")) else None
    image=text(source.get("PWA参考图URL")) if is_url(source.get("PWA参考图URL")) else None
    tasks=[]
    if len(supplier_urls)<1: tasks.append("找首个精确货源")
    elif len(supplier_urls)<3: tasks.append(f"补货源至3家（当前{len(supplier_urls)}）")
    if not oz: tasks.append("换/补Ozon有效竞品")
    if not wb: tasks.append("换/补WB有效竞品")
    if not image: tasks.append("补平台/链接页/供应商参考图")
    domains=[]
    for u in supplier_urls:
        try: domains.append(urlparse(u).netloc.lower())
        except Exception: pass
    return {"supplierCount":len(supplier_urls),"supplierUrls":supplier_urls,"ozonCurrent":bool(oz),"wbCurrent":bool(wb),"imageCurrent":bool(image),"supplierDomains":domains,"tasks":tasks}


def ingestion_state(source: dict[str, Any]) -> dict[str, Any]:
    sku_key=text(source.get("SKU_KEY"))
    first=text(source.get("首次发现日期")) or text(source.get("选品日期")) or text(source.get("快照时间"))
    return {"inMaster":bool(sku_key),"skuKey":sku_key,"firstSeen":first,"dedupeStatus":"主库已标准化" if sku_key else "待生成SKU_KEY"}


def enrich_automation(source: dict[str, Any], params: dict[str,float] | None=None) -> dict[str, Any]:
    price=number(source.get("Ozon目标/当前售价RUB"))
    cost=number(source.get("实际/核价采购成本CNY"))
    weight=number(source.get("毛重kg"))
    profit=profit_model(price,cost,weight,params)
    gaps=gap_radar(source)
    queue=queue_score(source,gaps,profit)
    sourcing=source_competitor_state(source)
    ingest=ingestion_state(source)
    return {
        "modulesVersion":"AUTOMATION-P1-V2",
        "coreBundles":CORE_BUNDLES,
        "ingestion":ingest,
        "gaps":gaps,
        "queue":queue,
        "profitGate":profit,
        "sourcing":sourcing,
        "sync":{"rowHashReady":True,"incremental":True,"networkFirstTarget":True},
    }


def best_match(candidate_name: str, master_names: list[str]) -> tuple[str|None,float]:
    best=None; score=0.0
    for name in master_names:
        s=identity_similarity(candidate_name,name)
        if s>score:
            best=name;score=s
    return best,round(score,4)


def ingest_plan(candidate_names:list[str], master_names:list[str]) -> dict[str,Any]:
    exact=[];review=[];new=[]
    for candidate in candidate_names:
        candidate=text(candidate)
        if not candidate: continue
        match,score=best_match(candidate,master_names)
        if score>=0.985:
            exact.append({"candidate":candidate,"match":match,"score":score})
        elif score>=0.80:
            review.append({"candidate":candidate,"match":match,"score":score})
        else:
            new.append({"candidate":candidate,"closest":match,"score":score})
    return {"existing":exact,"reviewDuplicate":review,"newSku":new,"counts":{"existing":len(exact),"reviewDuplicate":len(review),"newSku":len(new)}}
