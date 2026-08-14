from __future__ import annotations
import argparse, ast, json, math, os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

SPREADSHEET_ID = os.getenv('LEMON_SHEET_ID', '1a01ljnRehIEQO-LecUEIhZGGSIhN0ABBmots6ToN6AE')

@dataclass(frozen=True)
class Rule:
    mode: str
    order: int
    output: str
    expr: str
    enabled: bool = True

FALSES = {'0','false','no','否','停用','disabled',''}
def enabled(v: Any) -> bool:
    return v if isinstance(v,bool) else str(v).strip().lower() not in FALSES

def rules_from_rows(rows: list[dict[str,Any]]) -> list[Rule]:
    out=[]
    for r in rows:
        mode=str(r.get('模式','')).strip(); field=str(r.get('输出字段','')).strip(); expr=str(r.get('公式（Python读取）','')).strip()
        if not mode or not field or not expr or not enabled(r.get('启用',True)): continue
        out.append(Rule(mode,int(float(r.get('顺序',0))),field,expr,True))
    return sorted(out,key=lambda x:(x.mode,x.order))

def round_up_10(x): return math.ceil(float(x)/10.0)*10.0
FUNCS={'min':min,'max':max,'abs':abs,'round':round,'ceil':math.ceil,'floor':math.floor,'round_up_10':round_up_10}
BIN={ast.Add:lambda a,b:a+b, ast.Sub:lambda a,b:a-b, ast.Mult:lambda a,b:a*b, ast.Div:lambda a,b:a/b, ast.Pow:lambda a,b:a**b, ast.Mod:lambda a,b:a%b}
UN={ast.UAdd:lambda x:+x, ast.USub:lambda x:-x}
CMP={ast.Lt:lambda a,b:a<b, ast.LtE:lambda a,b:a<=b, ast.Gt:lambda a,b:a>b, ast.GtE:lambda a,b:a>=b, ast.Eq:lambda a,b:a==b, ast.NotEq:lambda a,b:a!=b}

def ev(n, env: Mapping[str,Any]):
    if isinstance(n,ast.Expression): return ev(n.body,env)
    if isinstance(n,ast.Constant):
        if isinstance(n.value,(int,float,str,bool)) or n.value is None: return n.value
        raise ValueError('unsupported constant')
    if isinstance(n,ast.Name):
        if n.id in env: return env[n.id]
        if n.id in FUNCS: return FUNCS[n.id]
        raise ValueError(f'缺字段 {n.id}')
    if isinstance(n,ast.BinOp) and type(n.op) in BIN: return BIN[type(n.op)](ev(n.left,env),ev(n.right,env))
    if isinstance(n,ast.UnaryOp) and type(n.op) in UN: return UN[type(n.op)](ev(n.operand,env))
    if isinstance(n,ast.Call):
        fn=ev(n.func,env)
        if fn not in FUNCS.values(): raise ValueError('function not allowed')
        return fn(*[ev(a,env) for a in n.args])
    if isinstance(n,ast.IfExp): return ev(n.body,env) if ev(n.test,env) else ev(n.orelse,env)
    if isinstance(n,ast.Compare):
        left=ev(n.left,env)
        for op,c in zip(n.ops,n.comparators):
            right=ev(c,env)
            if type(op) not in CMP or not CMP[type(op)](left,right): return False
            left=right
        return True
    if isinstance(n,ast.BoolOp):
        vals=[ev(v,env) for v in n.values]
        if isinstance(n.op,ast.And): return all(vals)
        if isinstance(n.op,ast.Or): return any(vals)
    raise ValueError(f'语法不允许: {type(n).__name__}')

def safe_eval(expr,env): return ev(ast.parse(expr,mode='eval'),env)

def coerce(v):
    if v is None or v=='': return None
    if isinstance(v,(int,float)) and not isinstance(v,bool): return float(v)
    if isinstance(v,str):
        s=v.strip().replace(',','')
        if not s: return None
        if s.endswith('%'):
            try:return float(s[:-1])/100
            except ValueError:return v
        try:return float(s)
        except ValueError:return v
    return v

CROSS_REQ=['当前售价_RUB','汇率_RUB_RMB','产品成本_RMB','CEL物流_RMB','其他固定成本_RMB','佣金率','广告率','促销率','支付率','税费率','目标利润率','促销底线利润率']
LOCAL_REQ=['当前售价_RUB','汇率_RUB_RMB','采购成本_RMB','国内运费_RMB','头程物流_RMB','佣金率','广告率','促销率','支付率','平台税费率','海外仓仓储_RUB','海外仓送官方仓_RUB','官方仓仓储_RUB','商品体积_L','尾程单价_RUB_L','合规回款费率','附加税费率','目标利润率','促销底线利润率']
CROSS_MAP={'SKU':'SKU','产品名称':'产品名称','当前售价 RUB':'当前售价_RUB','产品成本 RMB':'产品成本_RMB','CEL物流 RMB':'CEL物流_RMB','其他固定成本 RMB':'其他固定成本_RMB','汇率 RUB/RMB':'汇率_RUB_RMB','目标利润率':'目标利润率','促销底线利润率':'促销底线利润率','广告率':'广告率','促销/积分率':'促销率','支付/提现率':'支付率','税费率':'税费率','最终采用佣金率':'佣金率','模型净利润 RMB':'表内_净利润','模型利润率':'表内_利润率','模型 ROI':'表内_ROI','保本售价 RUB':'表内_保本售价','目标售价 RUB':'表内_目标售价','建议售价 RUB':'表内_建议售价','最低促销价 RUB':'表内_最低促销价','判断':'表内_判断'}
LOCAL_MAP={'SKU':'SKU','产品名称':'产品名称','当前售价 RUB':'当前售价_RUB','采购成本 RMB':'采购成本_RMB','国内运费分摊 RMB':'国内运费_RMB','头程物流 RMB':'头程物流_RMB','汇率 RUB/RMB':'汇率_RUB_RMB','目标利润率':'目标利润率','促销底线利润率':'促销底线利润率','佣金率':'佣金率','广告率':'广告率','促销/积分率':'促销率','支付/提现率':'支付率','平台税费率':'平台税费率','海外仓仓储 RUB':'海外仓仓储_RUB','海外仓送官方仓 RUB':'海外仓送官方仓_RUB','官方仓仓储 RUB':'官方仓仓储_RUB','商品体积 L':'商品体积_L','尾程单价 RUB/L':'尾程单价_RUB_L','合规回款费率':'合规回款费率','附加税费率':'附加税费率','净利润 RUB':'表内_净利润','利润率':'表内_利润率','ROI':'表内_ROI','保本售价 RUB':'表内_保本售价','目标售价 RUB':'表内_目标售价','建议售价 RUB':'表内_建议售价','最低促销价 RUB':'表内_最低促销价','判断':'表内_判断'}

def calc(rec,mode,rules,required):
    env={k:coerce(v) for k,v in rec.items()}
    miss=[f for f in required if env.get(f) is None]
    if miss:return env,'待补充',miss,[]
    errs=[]
    for r in rules:
        if r.mode!=mode:continue
        try:env[r.output]=safe_eval(r.expr,env)
        except Exception as e:env[r.output]=None;errs.append(f'{r.output}: {e}');break
    return env,'公式错误' if errs else '完整',[],errs

def num(v):
    x=coerce(v); return x if isinstance(x,(int,float)) else None

def compare(a,b,tol=.01):
    a=num(a); b=num(b)
    if a is None or b is None:return ''
    return '一致' if abs(a-b)<=tol else f'差异 {a-b:+.4f}'

def records(ws,header_row):
    vals=ws.get_all_values(); headers=vals[header_row-1] if len(vals)>=header_row else []
    out=[]
    for row in vals[header_row:]:
        if not any(str(x).strip() for x in row):continue
        out.append({h:(row[i] if i<len(row) else '') for i,h in enumerate(headers) if h})
    return out

def run():
    import gspread
    from google.oauth2.service_account import Credentials
    raw=os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not raw: raise RuntimeError('缺少 GOOGLE_SERVICE_ACCOUNT_JSON')
    creds=Credentials.from_service_account_info(json.loads(raw),scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive.file'])
    book=gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    rules=rules_from_rows(records(book.worksheet('10_Python设置'),5))
    if not rules: raise RuntimeError('10_Python设置 未读取到启用公式')
    out=[['运行时间','模式','SKU','产品名称','状态','缺失项','Python净利润','表内净利润','净利润校验','Python利润率','表内利润率','利润率校验','Python ROI','表内 ROI','ROI校验','Python保本售价','表内保本售价','保本校验','Python目标售价','表内目标售价','目标校验','Python建议售价','表内建议售价','建议价校验','Python最低促销价','表内最低促销价','促销价校验','Python判断','表内判断','错误']]
    now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for mode,name,mapping,req in [('跨境','06_跨境SKU核价',CROSS_MAP,CROSS_REQ),('本土','07_本土SKU核价',LOCAL_MAP,LOCAL_REQ)]:
        for rawrow in records(book.worksheet(name),5):
            rec={dst:rawrow.get(src,'') for src,dst in mapping.items()}
            if not str(rec.get('SKU','')).strip() or rec.get('SKU')=='__APP_TEMPLATE__':continue
            v,status,missing,errs=calc(rec,mode,rules,req)
            if mode=='跨境': p,m,r='模型净利润_RMB','模型利润率','模型_ROI'
            else: p,m,r='净利润_RUB','利润率','ROI'
            out.append([now,mode,v.get('SKU',''),v.get('产品名称',''),status,'、'.join(missing),v.get(p),v.get('表内_净利润'),compare(v.get(p),v.get('表内_净利润')),v.get(m),v.get('表内_利润率'),compare(v.get(m),v.get('表内_利润率'),.0001),v.get(r),v.get('表内_ROI'),compare(v.get(r),v.get('表内_ROI'),.0001),v.get('保本售价_RUB'),v.get('表内_保本售价'),compare(v.get('保本售价_RUB'),v.get('表内_保本售价'),.02),v.get('目标售价_RUB'),v.get('表内_目标售价'),compare(v.get('目标售价_RUB'),v.get('表内_目标售价'),.02),v.get('建议售价_RUB'),v.get('表内_建议售价'),compare(v.get('建议售价_RUB'),v.get('表内_建议售价'),.02),v.get('最低促销价_RUB'),v.get('表内_最低促销价'),compare(v.get('最低促销价_RUB'),v.get('表内_最低促销价'),.02),v.get('判断'),v.get('表内_判断'),'；'.join(errs)])
    try: ws=book.worksheet('PY_利润校验'); ws.clear()
    except Exception: ws=book.add_worksheet(title='PY_利润校验',rows=max(100,len(out)+20),cols=30)
    ws.update(out,'A1')
    print(f'完成：写入 {len(out)-1} 条校验记录')

def self_test():
    rs=[Rule('跨境',10,'销售收入_RMB','当前售价_RUB / 汇率_RUB_RMB'),Rule('跨境',20,'固定成本_RMB','产品成本_RMB + CEL物流_RMB + 其他固定成本_RMB'),Rule('跨境',30,'比例费率合计','佣金率 + 广告率 + 促销率 + 支付率 + 税费率'),Rule('跨境',40,'比例费用_RMB','销售收入_RMB * 比例费率合计'),Rule('跨境',50,'模型净利润_RMB','销售收入_RMB - 固定成本_RMB - 比例费用_RMB'),Rule('跨境',60,'模型利润率','模型净利润_RMB / 销售收入_RMB'),Rule('跨境',70,'模型_ROI','模型净利润_RMB / 固定成本_RMB'),Rule('跨境',80,'保本售价_RUB','固定成本_RMB / (1 - 比例费率合计) * 汇率_RUB_RMB'),Rule('跨境',90,'目标售价_RUB','固定成本_RMB / (1 - 比例费率合计 - 目标利润率) * 汇率_RUB_RMB'),Rule('跨境',100,'建议售价_RUB','round_up_10(目标售价_RUB)'),Rule('跨境',110,'最低促销价_RUB','固定成本_RMB / (1 - 比例费率合计 - 促销底线利润率) * 汇率_RUB_RMB'),Rule('跨境',120,'判断',"'可销售' if 模型利润率 >= 目标利润率 else ('观察' if 模型利润率 >= 促销底线利润率 else '不建议')")]
    rec={'当前售价_RUB':640,'汇率_RUB_RMB':12.31981,'产品成本_RMB':13.74,'CEL物流_RMB':11.66,'其他固定成本_RMB':2,'佣金率':.12,'广告率':0,'促销率':0,'支付率':.015,'税费率':0,'目标利润率':.15,'促销底线利润率':.05}
    v,s,_,e=calc(rec,'跨境',rs,CROSS_REQ)
    assert s=='完整' and not e
    assert abs(v['模型净利润_RMB']-17.535757937825338)<1e-6
    assert v['建议售价_RUB']==480 and v['判断']=='可销售'
    rec['产品成本_RMB']=''
    _,s,miss,_=calc(rec,'跨境',rs,CROSS_REQ)
    assert s=='待补充' and '产品成本_RMB' in miss
    print('SELF-TEST OK')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--self-test',action='store_true'); ap.add_argument('--google',action='store_true')
    a=ap.parse_args()
    if a.self_test:self_test()
    if a.google:run()
    if not a.self_test and not a.google:ap.print_help()
if __name__=='__main__':main()
