from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

LOADER = r'''let ENCRYPTED_PAYLOAD=null;
let PWA_DATA_VERSION=null;
let PWA_DATA_READY=null;
async function loadExternalEncryptedPayload(){
  const loginBtn=document.getElementById('loginBtn');
  const authError=document.getElementById('authError');
  if(loginBtn){loginBtn.disabled=true;loginBtn.textContent='加载数据…';}
  try{
    const versionUrl=new URL('./pwa-data-version.json',window.location.href);
    versionUrl.searchParams.set('_ts',Date.now().toString());
    const vr=await fetch(versionUrl.toString(),{cache:'no-store'});
    if(!vr.ok)throw new Error(`version HTTP ${vr.status}`);
    const meta=await vr.json();
    if(!meta||!Number.isInteger(meta.records)||meta.records<1)throw new Error('version records invalid');
    const dataUrl=new URL('./sku-data.enc.json',window.location.href);
    dataUrl.searchParams.set('v',String(meta.version||Date.now()));
    const dr=await fetch(dataUrl.toString(),{cache:'no-store'});
    if(!dr.ok)throw new Error(`data HTTP ${dr.status}`);
    const env=await dr.json();
    if(!env||env.kind!=='SKU-PWA-HYBRID-ENVELOPE')throw new Error('encrypted data kind invalid');
    if(env.records!==meta.records)throw new Error(`record mismatch ${env.records}/${meta.records}`);
    ENCRYPTED_PAYLOAD=env;
    PWA_DATA_VERSION=meta;
    window.PWA_DATA_VERSION=meta;
    if(loginBtn){loginBtn.disabled=false;loginBtn.textContent='登录';}
    if(authError)authError.textContent='';
    return env;
  }catch(err){
    if(loginBtn){loginBtn.disabled=true;loginBtn.textContent='数据加载失败';}
    if(authError)authError.textContent='加密数据包加载失败；联网后点人工刷新，离线时会尝试使用上次缓存。';
    console.error('PWA external data load failed',err);
    throw err;
  }
}
const authFormForData=document.getElementById('authForm');
if(authFormForData){authFormForData.addEventListener('submit',event=>{if(!ENCRYPTED_PAYLOAD){event.preventDefault();event.stopImmediatePropagation();}},true);}
PWA_DATA_READY=loadExternalEncryptedPayload();
window.PWA_DATA_READY=PWA_DATA_READY;'''


def externalize(index: Path, envelope: Path, data_out: Path, version_out: Path) -> dict:
    html=index.read_text(encoding='utf-8')
    env=json.loads(envelope.read_text(encoding='utf-8'))
    if env.get('kind')!='SKU-PWA-HYBRID-ENVELOPE':
        raise SystemExit('only hybrid envelope can be externalized')
    if not isinstance(env.get('records'),int) or env['records']<1:
        raise SystemExit('envelope record count invalid')
    compact=json.dumps(env,ensure_ascii=False,separators=(',',':'))
    sha=hashlib.sha256(compact.encode('utf-8')).hexdigest()
    version={
        'schema':'SKU-PWA-EXTERNAL-DATA-V1',
        'version':sha[:16],
        'records':env['records'],
        'envelopeSha256':sha,
        'payloadSchema':env.get('payloadSchema'),
    }
    pattern=r'const ENCRYPTED_PAYLOAD=\{.*?\};\s*let data='
    replacement=LOADER+'\nlet data='
    out,n=re.subn(pattern,replacement,html,count=1,flags=re.S)
    if n!=1:
        raise SystemExit('embedded ENCRYPTED_PAYLOAD marker not found exactly once')
    if compact in out or '"kind":"SKU-PWA-HYBRID-ENVELOPE"' in out:
        raise SystemExit('encrypted payload still embedded in HTML')
    data_out.parent.mkdir(parents=True,exist_ok=True)
    version_out.parent.mkdir(parents=True,exist_ok=True)
    data_out.write_text(compact,encoding='utf-8')
    version_out.write_text(json.dumps(version,ensure_ascii=False,indent=2),encoding='utf-8')
    index.write_text(out,encoding='utf-8')
    return {'records':env['records'],'version':version['version'],'envelopeSha256':sha}


def main() -> None:
    p=argparse.ArgumentParser(description='Externalize encrypted PWA dataset from HTML without changing crypto/login logic.')
    p.add_argument('--index',type=Path,required=True)
    p.add_argument('--envelope',type=Path,required=True)
    p.add_argument('--data-out',type=Path,required=True)
    p.add_argument('--version-out',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(externalize(args.index,args.envelope,args.data_out,args.version_out),separators=(',',':')))

if __name__=='__main__':
    main()
