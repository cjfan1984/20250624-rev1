from __future__ import annotations

import argparse, hashlib, importlib.util, json, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from advanced_modules import data_quality_audit, next_task, purchase_reverse, route_decision
from build_dynamic_pwa_data import main as _unused_main  # ensures module imports stay validated
import build_dynamic_pwa_data as builder


def load_module(path:Path,name:str):
    spec=importlib.util.spec_from_file_location(name,path);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def sha256_file(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def enrich_advanced(records:list[dict],params:dict)->dict:
    audits=[]
    for r in records:
        audit=data_quality_audit(r);r['qualityAudit']=audit
        r['routeDecision']=route_decision(r)
        r['purchaseReverse']=purchase_reverse(r.get('price'),r.get('weight'),params)
        r['nextTask']=next_task(r)
        if audit['issueCount']:audits.append({'skuKey':r.get('skuKey'),'sku':r.get('sku'),'audit':audit})
    return {'audited':len(records),'issueSkus':len(audits),'highRiskSkus':sum(x['audit']['highRiskCount']>0 for x in audits),'issues':audits}


def build_records(xlsx:Path)->tuple[list[dict],dict,dict]:
    rows=builder.base.load_from_xlsx(xlsx,builder.base.DEFAULT_WORKSHEET)
    master=builder.base.load_master_names_from_xlsx(xlsx,builder.base.DEFAULT_MASTER_WORKSHEET)
    params=builder.load_params_xlsx(xlsx)
    builder.base.validate_master_coverage(master,rows)
    records=builder.base.build_dataset(rows)
    for record in records:
        auto=builder.enrich_automation(record.get('source') or {},params)
        record['automation']=auto
        record['gapCount']=auto['gaps']['gapCount'];record['completion']=auto['gaps']['completion'];record['primaryBlocker']=auto['gaps']['primaryBlocker'];record['queueLevel']=auto['queue']['level'];record['queueScore']=auto['queue']['score'];record['structuralStop']=auto['profitGate'].get('structuralStop');record['supplierCount']=auto['sourcing']['supplierCount']
        builder.legacy_compat(record)
    audit=enrich_advanced(records,params)
    for record in records:
        record['rowHash']=hashlib.sha256(builder.canonical({'source':record.get('source'),'automation':record.get('automation'),'audit':record.get('qualityAudit'),'route':record.get('routeDecision'),'reverse':record.get('purchaseReverse'),'next':record.get('nextTask'),'params':params}).encode()).hexdigest()
    return records,params,audit


def previous_hashes(path:Path|None)->dict[str,str]:
    if not path or not path.exists():return {}
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except:return {}
    return {r['skuKey']:r['rowHash'] for r in data if isinstance(r,dict) and r.get('skuKey') and r.get('rowHash')}


def main():
    ap=argparse.ArgumentParser(description='Build, audit and public-key encrypt the dynamic SKU dataset without rebuilding the PWA shell.')
    ap.add_argument('--xlsx',type=Path,required=True)
    ap.add_argument('--keyring',type=Path,required=True)
    ap.add_argument('--encrypt-tool',type=Path,default=HERE/'encrypt_pwa_public.py')
    ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--previous-json',type=Path)
    ap.add_argument('--fail-high-risk',action='store_true')
    a=ap.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True)
    records,params,audit=build_records(a.xlsx)
    prev=previous_hashes(a.previous_json);cur={r['skuKey']:r['rowHash'] for r in records};added=sorted(set(cur)-set(prev));removed=sorted(set(prev)-set(cur));changed=sorted(k for k in cur.keys()&prev.keys() if cur[k]!=prev[k])
    stable=[{k:v for k,v in r.items() if k!='rowHash'} for r in records];dataset_sha=hashlib.sha256(builder.canonical(stable).encode()).hexdigest()
    plain=out/'new-pwa-data.json';plain.write_text(json.dumps(records,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    if a.fail_high_risk and audit['highRiskSkus']:
        (out/'quality-audit.private.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        raise SystemExit(f"high-risk data quality issues: {audit['highRiskSkus']}")
    encmod=load_module(a.encrypt_tool,'sku_encrypt_tool')
    # invoke existing encryptor through its CLI-compatible implementation without touching password/private key
    import subprocess
    envelope=out/'sku-data.enc.json'
    proc=subprocess.run([sys.executable,str(a.encrypt_tool),'--input',str(plain),'--keyring',str(a.keyring),'--output',str(envelope)],text=True,capture_output=True)
    if proc.returncode!=0:raise SystemExit(proc.stderr or proc.stdout)
    env=json.loads(envelope.read_text(encoding='utf-8'))
    if env.get('records')!=len(records):raise SystemExit('encrypted envelope record mismatch')
    envelope_sha=sha256_file(envelope)
    manifest={
      'schema':'SKU-PWA-EXTERNAL-DATA-V2','version':dataset_sha[:16],'records':len(records),'datasetSha256':dataset_sha,'envelopeSha256':envelope_sha,'delta':{'added':len(added),'changed':len(changed),'removed':len(removed)},
      'stats':{'stop':sum(r.get('stage')=='STOP' for r in records),'profitKnown':sum(bool(r.get('profitKnown')) for r in records),'orPass':sum(bool(r.get('decisionOrPass')) for r in records),'modelRankEligible':sum(bool(r.get('profitRankEligible')) for r in records),'p1':sum(r.get('queueLevel')=='P1' for r in records),'structuralStop':sum(r.get('structuralStop') is True for r in records),'qualityIssueSkus':audit['issueSkus'],'qualityHighRiskSkus':audit['highRiskSkus']},
      'params':params,
    }
    (out/'pwa-data-version.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'quality-audit.private.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'delta.private.json').write_text(json.dumps({'added':added,'changed':changed,'removed':removed},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'records':len(records),'version':manifest['version'],'datasetSha256':dataset_sha,'envelopeSha256':envelope_sha,'delta':manifest['delta'],'stats':manifest['stats']},ensure_ascii=False,separators=(',',':')))
if __name__=='__main__':main()
