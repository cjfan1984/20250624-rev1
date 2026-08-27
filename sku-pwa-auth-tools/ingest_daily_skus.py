from __future__ import annotations
import argparse,json,os,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from automation_modules import ingest_plan,text

MASTER='三级SKU主库'; DAILY='每日新品_决策卡数据层'

def load_xlsx(path:Path):
    from openpyxl import load_workbook
    wb=load_workbook(path,read_only=True,data_only=True)
    m=wb[MASTER]; mh=[str(x).strip() if x is not None else '' for x in next(m.iter_rows(values_only=True))]
    mi=mh.index('三级SKU'); master=[text(r[mi]) for r in m.iter_rows(min_row=2,values_only=True) if len(r)>mi and text(r[mi])]
    d=wb[DAILY]; rows=list(d.iter_rows(values_only=True)); header_idx=next(i for i,r in enumerate(rows) if r and '产品/型号/规格' in r)
    headers=[str(x).strip() if x is not None else '' for x in rows[header_idx]]; ci=headers.index('产品/型号/规格')
    candidates=[text(r[ci]) for r in rows[header_idx+1:] if len(r)>ci and text(r[ci])]
    return master,candidates

def google_creds(write=False):
    from google.oauth2.service_account import Credentials
    raw=os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON'); fn=os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
    scopes=['https://www.googleapis.com/auth/spreadsheets' if write else 'https://www.googleapis.com/auth/spreadsheets.readonly','https://www.googleapis.com/auth/drive.readonly']
    if raw:return Credentials.from_service_account_info(json.loads(raw),scopes=scopes)
    if fn:return Credentials.from_service_account_file(fn,scopes=scopes)
    raise SystemExit('Google credentials missing')

def load_google(spreadsheet_id:str):
    import gspread
    gc=gspread.authorize(google_creds(False)); sh=gc.open_by_key(spreadsheet_id)
    master=[text(v) for v in sh.worksheet(MASTER).col_values(3)[1:] if text(v)]
    rows=sh.worksheet(DAILY).get_all_values(); hi=next(i for i,r in enumerate(rows) if '产品/型号/规格' in r); ci=rows[hi].index('产品/型号/规格')
    cand=[text(r[ci]) for r in rows[hi+1:] if len(r)>ci and text(r[ci])]
    return master,cand

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--xlsx',type=Path);ap.add_argument('--spreadsheet-id',default='108o5gtxkUsWEZI8xfZFE89Kq83IfStQGNm6dvjIlAkk');ap.add_argument('--output',type=Path,default=Path('ingest-plan.json'))
    a=ap.parse_args();master,candidates=load_xlsx(a.xlsx) if a.xlsx else load_google(a.spreadsheet_id)
    plan=ingest_plan(candidates,master);plan['masterCount']=len(master);plan['candidateCount']=len(candidates);plan['policy']='>=0.985自动合并；0.80–0.985进入重复复核；<0.80允许创建新SKU'
    a.output.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(plan['counts'],ensure_ascii=False))
if __name__=='__main__':main()
