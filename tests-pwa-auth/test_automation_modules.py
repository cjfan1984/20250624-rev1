import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1] / 'sku-pwa-auth-tools'))
import automation_modules as m


def test_wifi_regression():
    r=m.profit_model(1557,32.26,.07)
    assert r['profit']==48.24
    assert round(r['margin']*100,1)==38.2
    assert r['orPass'] is True


def test_or_rule_profit_only():
    r={'当前阶段':'MODEL_PROFIT_OK','当前优先级':'A','Ozon目标/当前售价RUB':500,'实际/核价采购成本CNY':1,'毛重kg':0.3}
    a=m.enrich_automation(r)
    assert 'orPass' in a['profitGate']


def test_structural_stop():
    r=m.profit_model(180,None,.303)
    assert r['structuralStop'] is True


def test_dedupe():
    p=m.ingest_plan(['24合1精密螺丝刀套装','全新XY产品'],['24合1精密螺丝刀套装'])
    assert p['counts']['existing']==1 and p['counts']['newSku']==1


def test_registry():
    assert len(m.MODULE_REGISTRY)==25
    assert sum(x['status']=='active' for x in m.MODULE_REGISTRY)==6
