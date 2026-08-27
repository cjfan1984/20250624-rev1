from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from advanced_modules import data_quality_audit, next_task, purchase_reverse, route_decision
import build_dynamic_pwa_data as builder

PAYLOAD_SCHEMA='SKU-DYNAMIC-AUTOMATION-V4'


def sha256_file(path:Path)->str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def enrich_advanced(records:list[dict],params:dict)->dict:
    audits=[]
    for r in records:
        audit=data_quality_audit(r);r['qualityAudit']=audit
        r['routeDecision']=route_decision(r)
        r['purchaseReverse']=purchase_reverse(r.get('price'),r.get('weight'),params)
        r['nextTask']=next_task(r)
        if audit['issueCount']:
            audits.append({'skuKey':r.get('skuKey'),'sku':r.get('sku'),'audit':audit})
    return {
        'audited':len(records),
        'issueSkus':len(audits),
        'highRiskSkus':sum(x['audit']['highRiskCount']>0 for x in audits),
        'issues':audits,
    }


def _finish_records(rows:list[dict],master:list[str],params:dict)->tuple[list[dict],dict,dict]:
    builder.base.validate_master_coverage(master,rows)
    records=builder.base.build_dataset(rows)
    for record in records:
        auto=builder.enrich_automation(record.get('source') or {},params)
        record['automation']=auto
        record['gapCount']=auto['gaps']['gapCount']
        record['completion']=auto['gaps']['completion']
        record['primaryBlocker']=auto['gaps']['primaryBlocker']
        record['queueLevel']=auto['queue']['level']
        record['queueScore']=auto['queue']['score']
        record['structuralStop']=auto['profitGate'].get('structuralStop')
        record['supplierCount']=auto['sourcing']['supplierCount']
        builder.legacy_compat(record)
    audit=enrich_advanced(records,params)
    for record in records:
        record['rowHash']=hashlib.sha256(builder.canonical({
            'source':record.get('source'),
            'automation':record.get('automation'),
            'audit':record.get('qualityAudit'),
            'route':record.get('routeDecision'),
            'reverse':record.get('purchaseReverse'),
            'next':record.get('nextTask'),
            'params':params,
        }).encode()).hexdigest()
    return records,params,audit


def build_records_xlsx(xlsx:Path)->tuple[list[dict],dict,dict]:
    rows=builder.base.load_from_xlsx(xlsx,builder.base.DEFAULT_WORKSHEET)
    master=builder.base.load_master_names_from_xlsx(xlsx,builder.base.DEFAULT_MASTER_WORKSHEET)
    params=builder.load_params_xlsx(xlsx)
    return _finish_records(rows,master,params)


def build_records_google(spreadsheet_id:str)->tuple[list[dict],dict,dict]:
    rows=builder.base.load_from_google(spreadsheet_id,builder.base.DEFAULT_WORKSHEET)
    master=builder.base.load_master_names_from_google(spreadsheet_id,builder.base.DEFAULT_MASTER_WORKSHEET)
    params=builder.load_params_google(spreadsheet_id)
    return _finish_records(rows,master,params)


def previous_hashes(path:Path|None)->dict[str,str]:
    if not path or not path.exists():return {}
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except Exception:return {}
    return {r['skuKey']:r['rowHash'] for r in data if isinstance(r,dict) and r.get('skuKey') and r.get('rowHash')}


def main():
    ap=argparse.ArgumentParser(description='Build, audit and public-key encrypt the dynamic SKU V4 dataset without rebuilding the PWA shell.')
    source=ap.add_mutually_exclusive_group(required=True)
    source.add_argument('--xlsx',type=Path)
    source.add_argument('--spreadsheet-id')
    ap.add_argument('--keyring',type=Path,required=True)
    ap.add_argument('--encrypt-tool',type=Path,default=HERE/'encrypt_pwa_public.py')
    ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--previous-json',type=Path)
    ap.add_argument('--fail-high-risk',action='store_true')
    a=ap.parse_args();out=a.output_dir;out.mkdir(parents=True,exist_ok=True)

    if a.xlsx:
        records,params,audit=build_records_xlsx(a.xlsx)
    else:
        records,params,audit=build_records_google(a.spreadsheet_id)

    prev=previous_hashes(a.previous_json)
    cur={r['skuKey']:r['rowHash'] for r in records}
    added=sorted(set(cur)-set(prev));removed=sorted(set(prev)-set(cur));changed=sorted(k for k in cur.keys()&prev.keys() if cur[k]!=prev[k])
    stable=[{k:v for k,v in r.items() if k!='rowHash'} for r in records]
    dataset_sha=hashlib.sha256(builder.canonical(stable).encode()).hexdigest()

    plain=out/'new-pwa-data.json'
    plain.write_text(json.dumps(records,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    if a.fail_high_risk and audit['highRiskSkus']:
        (out/'quality-audit.private.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
        raise SystemExit(f"high-risk data quality issues: {audit['highRiskSkus']}")

    envelope=out/'sku-data.enc.json'
    proc=subprocess.run([
        sys.executable,str(a.encrypt_tool),'--input',str(plain),'--keyring',str(a.keyring),'--output',str(envelope)
    ],text=True,capture_output=True)
    if proc.returncode!=0:raise SystemExit(proc.stderr or proc.stdout)
    env=json.loads(envelope.read_text(encoding='utf-8'))
    if env.get('records')!=len(records):raise SystemExit('encrypted envelope record mismatch')
    env['payloadSchema']=PAYLOAD_SCHEMA
    envelope.write_text(json.dumps(env,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    envelope_sha=sha256_file(envelope)

    manifest={
      'schema':'SKU-PWA-EXTERNAL-DATA-V4',
      'payloadSchema':PAYLOAD_SCHEMA,
      'version':dataset_sha[:16],
      'records':len(records),
      'datasetSha256':dataset_sha,
      'envelopeSha256':envelope_sha,
      'delta':{'added':len(added),'changed':len(changed),'removed':len(removed)},
      'stats':{
          'stop':sum(r.get('stage')=='STOP' for r in records),
          'profitKnown':sum(bool(r.get('profitKnown')) for r in records),
          'orPass':sum(bool(r.get('decisionOrPass')) for r in records),
          'modelRankEligible':sum(bool(r.get('profitRankEligible')) for r in records),
          'p1':sum(r.get('queueLevel')=='P1' for r in records),
          'structuralStop':sum(r.get('structuralStop') is True for r in records),
          'qualityIssueSkus':audit['issueSkus'],
          'qualityHighRiskSkus':audit['highRiskSkus'],
      },
      'params':params,
    }
    (out/'pwa-data-version.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'quality-audit.private.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'delta.private.json').write_text(json.dumps({'added':added,'changed':changed,'removed':removed},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'records':len(records),'version':manifest['version'],'payloadSchema':PAYLOAD_SCHEMA,'datasetSha256':dataset_sha,'envelopeSha256':envelope_sha,'delta':manifest['delta'],'stats':manifest['stats']},ensure_ascii=False,separators=(',',':')))

if __name__=='__main__':main()
