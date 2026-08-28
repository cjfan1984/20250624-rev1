from __future__ import annotations

import math,re,statistics
from collections import Counter,defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from automation_modules import DEFAULT_PARAMS, identity_similarity, number, text, profit_model


def data_quality_audit(record:dict[str,Any])->dict[str,Any]:
    issues=[]
    src=record.get('source') or record
    price=number(record.get('price') if 'price' in record else src.get('Ozon目标/当前售价RUB'))
    cost=number(record.get('cost') if 'cost' in record else src.get('实际/核价采购成本CNY'))
    weight=number(record.get('weight') if 'weight' in record else src.get('毛重kg'))
    sheet_profit=number(record.get('profit') if 'profit' in record else src.get('单件净利润CNY'))
    if weight is not None and weight<=0:issues.append({'severity':'high','code':'WEIGHT_NONPOSITIVE','message':'毛重≤0'})
    if weight is not None and weight>30:issues.append({'severity':'high','code':'WEIGHT_OUTLIER','message':f'毛重异常 {weight}kg'})
    if price is not None and price<=0:issues.append({'severity':'high','code':'PRICE_NONPOSITIVE','message':'售价≤0'})
    if cost is not None and cost<0:issues.append({'severity':'high','code':'COST_NEGATIVE','message':'采购价<0'})
    if price is not None and cost is not None and weight is not None:
        calc=profit_model(price,cost,weight)
        if sheet_profit is not None and calc.get('profit') is not None and abs(calc['profit']-sheet_profit)>1.0:
            issues.append({'severity':'high','code':'PROFIT_DRIFT','message':f"Python净利{calc['profit']}与表内{sheet_profit}偏差>{1.0}"})
    urls=[]
    for key in ('supplierUrls','ozonCompetitorUrl','wbCompetitorUrl'):
        v=record.get(key)
        if isinstance(v,list):urls.extend(v)
        elif v:urls.append(v)
    if len(urls)!=len(set(urls)):issues.append({'severity':'medium','code':'DUPLICATE_URL','message':'存在重复货源/竞品链接'})
    updated=text(src.get('快照更新时间') or src.get('更新时间'))
    if not updated:
        issues.append({'severity':'low','code':'NO_UPDATED_AT','message':'缺更新时间'})
    elif not re.fullmatch(r'\d{4}-\d{2}-\d{2}',updated):
        issues.append({'severity':'high','code':'UPDATED_AT_INVALID','message':'更新时间不是 YYYY-MM-DD，疑似字段错位'})
    high=sum(i['severity']=='high' for i in issues)
    return {'issueCount':len(issues),'highRiskCount':high,'issues':issues,'status':'high' if high else ('review' if issues else 'ok')}


def change_log(previous:dict[str,Any]|None,current:dict[str,Any])->dict[str,Any]:
    if not previous:return {'changed':True,'changes':[{'field':'__new__','before':None,'after':'NEW_SKU'}]}
    keys=['stage','priority','price','cost','weight','profit','margin','localWbProfit','localOzonProfit','ozonCompetitorUrl','wbCompetitorUrl','supplierUrls','primaryBlocker','queueLevel']
    changes=[]
    for k in keys:
        if previous.get(k)!=current.get(k):changes.append({'field':k,'before':previous.get(k),'after':current.get(k)})
    return {'changed':bool(changes),'changes':changes}


def route_decision(record:dict[str,Any])->dict[str,Any]:
    cross='STOP' if record.get('stage')=='STOP' else ('P1' if record.get('decisionOrPass') else ('待补' if not record.get('profitKnown') else 'P2'))
    wb=number(record.get('localWbProfit'));oz=number(record.get('localOzonProfit'))
    wb_route='P1' if wb is not None and wb>10 else ('P2' if wb is not None and wb>0 else ('STOP' if wb is not None else '待补'))
    oz_route='P1' if oz is not None and oz>10 else ('P2' if oz is not None and oz>0 else ('STOP' if oz is not None else '待补'))
    return {'crossBorder':cross,'localWB':wb_route,'localOzon':oz_route,'summary':f'跨境{cross} / Ozon本土{oz_route} / WB本土{wb_route}'}


def price_sensitivity(price:float|None,cost:float|None,weight:float|None,params:dict[str,float]|None=None,steps=(-.10,-.05,0,.05,.10)):
    if price is None:return []
    out=[]
    for pct in steps:
        p=round(price*(1+pct),2);m=profit_model(p,cost,weight,params)
        out.append({'priceChangePct':round(pct*100,1),'priceRub':p,'profit':m.get('profit'),'margin':m.get('margin'),'orPass':m.get('orPass'),'structuralStop':m.get('structuralStop')})
    return out


def purchase_reverse(price:float|None,weight:float|None,params:dict[str,float]|None=None)->dict[str,Any]:
    p={**DEFAULT_PARAMS,**(params or {})}
    if price is None or weight is None:return {'ready':False}
    base=profit_model(price,0,weight,p);zero=base.get('zeroCostProfit')
    return {'ready':True,'maxCostForProfit10':round(zero-p['profit_threshold_cny'],2),'maxCostForMargin15':base.get('purchaseCap15'),'maxCostConservative':round(min(zero-p['profit_threshold_cny'],base.get('purchaseCap15')),2)}


def moq_cash_model(cost:float|None,moq:float|None,monthly_units:float|None)->dict[str,Any]:
    if cost is None or moq is None:return {'ready':False,'reason':'缺成本或MOQ'}
    capital=cost*moq
    days=None
    if monthly_units and monthly_units>0:days=moq/monthly_units*30
    return {'ready':True,'capitalCny':round(capital,2),'sellThroughDays':round(days,1) if days is not None else None}


def inventory_risk(cash:dict[str,Any])->dict[str,Any]:
    if not cash.get('ready'):return {'status':'待补','score':None}
    capital=cash.get('capitalCny') or 0;days=cash.get('sellThroughDays')
    score=0
    score+=0 if capital<1000 else 20 if capital<3000 else 40 if capital<8000 else 60
    if days is None:score+=20
    else:score+=0 if days<=30 else 15 if days<=60 else 30 if days<=90 else 40
    return {'score':min(100,score),'status':'低' if score<30 else '中' if score<60 else '高'}


def sales_trend(values:list[float|int])->dict[str,Any]:
    xs=[float(x) for x in values if isinstance(x,(int,float))]
    if len(xs)<2:return {'ready':False}
    def change(n):
        if len(xs)<n*2:return None
        prev=sum(xs[-2*n:-n]);cur=sum(xs[-n:]);return None if prev==0 else round((cur/prev-1)*100,1)
    return {'ready':True,'latest':xs[-1],'change7':change(7),'change14':change(14),'change30':change(30)}


def rank_change(current:float|None,previous:float|None)->dict[str,Any]:
    if current is None or previous is None:return {'ready':False}
    delta=previous-current
    return {'ready':True,'current':current,'previous':previous,'change':delta,'text':f"从第{int(previous)}{'升到' if delta>0 else '降到' if delta<0 else '保持'}第{int(current)}"}


def anomaly_detection(values:list[float|int])->dict[str,Any]:
    xs=[float(x) for x in values if isinstance(x,(int,float))]
    if len(xs)<5:return {'ready':False,'anomalies':[]}
    med=statistics.median(xs);dev=[abs(x-med) for x in xs];mad=statistics.median(dev) or 1e-9
    anomalies=[]
    for i,x in enumerate(xs):
        z=0.6745*(x-med)/mad
        if abs(z)>3.5:anomalies.append({'index':i,'value':x,'robustZ':round(z,2)})
    return {'ready':True,'anomalies':anomalies}


def similar_clusters(records:list[dict[str,Any]],threshold:float=.78)->list[list[str]]:
    names=[text(r.get('sku') or (r.get('source') or {}).get('产品名称/SKU')) for r in records];names=[n for n in names if n]
    unused=set(names);clusters=[]
    while unused:
        seed=unused.pop();group=[seed]
        for other in list(unused):
            if identity_similarity(seed,other)>=threshold:group.append(other);unused.remove(other)
        if len(group)>1:clusters.append(sorted(group))
    return clusters


def spec_matrix(records:list[dict[str,Any]])->dict[str,Any]:
    fam=defaultdict(list)
    for r in records:
        family=text(r.get('family') or (r.get('source') or {}).get('产品族'))
        if family:fam[family].append(r)
    opportunities=[]
    for family,items in fam.items():
        if len(items)<2:continue
        profitable=[x for x in items if x.get('decisionOrPass')]
        if profitable:opportunities.append({'family':family,'variants':len(items),'profitableVariants':len(profitable),'suggestion':'优先补同族缺失规格/颜色/件数矩阵'})
    return {'families':len(fam),'opportunities':opportunities}


def supply_reuse(records:list[dict[str,Any]])->list[dict[str,Any]]:
    by=defaultdict(set)
    for r in records:
        for u in r.get('supplierUrls') or []:
            try:domain=urlparse(u).netloc.lower()
            except:continue
            if domain:by[domain].add(r.get('sku'))
    return [{'supplierDomain':d,'skuCount':len(s),'skus':sorted(s)} for d,s in by.items() if len(s)>1]


def review_pain(texts:list[str])->dict[str,Any]:
    stop={'商品','产品','这个','使用','一个','没有','可以','非常','质量','good','very','the','and','для','что','это'}
    words=[]
    for raw in texts:
        for w in re.findall(r'[A-Za-zА-Яа-яЁё]{3,}|[\u4e00-\u9fff]{2,6}',str(raw or '').lower()):
            if w not in stop:words.append(w)
    top=Counter(words).most_common(12)
    return {'sampleTerms':len(words),'topTerms':[{'term':k,'count':v} for k,v in top]}


def qc_generator(record:dict[str,Any],pain:dict[str,Any]|None=None)->list[str]:
    src=record.get('source') or record;checks=['核对型号/BOM/配件数量','实称净重/毛重并拍照','实测包装三边与计费重','抽检外观/功能/包装一致性']
    spec=text(src.get('完整目标产品规格')) or ''
    if any(k in spec.lower() for k in ('电池','usb','wifi','zigbee','220v','12v','5v')):checks+=['通电/电池/接口功能测试','核对电气标识与必要合规文件']
    if pain and pain.get('topTerms'):checks.append('针对Top差评词逐项做故障复现/抽检')
    return checks


def next_task(record:dict[str,Any])->dict[str,Any]:
    auto=record.get('automation') or {};gaps=auto.get('gaps') or {};sourcing=auto.get('sourcing') or {};profit=auto.get('profitGate') or {}
    blocker=gaps.get('primaryBlocker')
    mapping={'采购价':'找100/300件正式报价并锁BOM','毛重':'取得目标包装实称毛重','Ozon价':'补当前Ozon精确竞品售价','WB价':'补当前WB精确竞品售价','Ozon竞品':'更换/补Ozon有效竞品','WB竞品':'更换/补WB有效竞品','货源1':'找首个精确同BOM货源','包装长':'补包装三边','包装宽':'补包装三边','包装高':'补包装三边','参考图':'抓平台/竞品/供应商参考图'}
    if profit.get('structuralStop'):return {'action':'停止跨境深搜；只保留本土/提价/组合装路线','reason':'零采购成本极限也过不了OR门槛'}
    if blocker:return {'action':mapping.get(blocker,f'补{blocker}'),'reason':f'当前唯一高价值缺口：{blocker}'}
    if sourcing.get('tasks'):return {'action':sourcing['tasks'][0],'reason':'供应链/竞品维护缺口'}
    return {'action':'进入正式报价/样品/QC闭环','reason':'核心公开数据已基本闭环'}
