from __future__ import annotations

import argparse, base64, hashlib, json, re, shutil, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))
from automation_modules import MODULE_REGISTRY, CORE_BUNDLES
from externalize_pwa_payload import externalize

INDEX_PARTS=[f'index.part{i:02d}' for i in range(1,10)]
ENV_PARTS=['full-envelope.part01','full-envelope.part02','full-envelope.part03','full-envelope.part04a','full-envelope.part04b']
DYNAMIC_DATA_PARTS=[f'sku-data.part{i:02d}' for i in range(1,10)]

def build(root:Path,out:Path)->dict:
    src=root/'sku-pwa-auth-src'; icon_src=root/'sku-pwa-src'; data_src=root/'sku-pwa-auth-data'
    out.mkdir(parents=True,exist_ok=True);(out/'icons').mkdir(exist_ok=True)
    html=''.join((src/p).read_text(encoding='utf-8') for p in INDEX_PARTS)
    env_text=''.join((src/p).read_text(encoding='utf-8') for p in ENV_PARTS)
    env=json.loads(env_text);keyring=json.loads((src/'hybrid-keyring.json').read_text(encoding='utf-8'))
    if env.get('kind')!='SKU-PWA-HYBRID-ENVELOPE':raise SystemExit('production envelope must be hybrid')
    if keyring.get('kind')!='SKU-PWA-HYBRID-KEYRING':raise SystemExit('hybrid keyring invalid')
    fp=keyring.get('publicKey',{}).get('fingerprintSha256')
    if env.get('keyWrapping',{}).get('publicKeyFingerprintSha256')!=fp:raise SystemExit('keyring/envelope fingerprint mismatch')
    marker='const HYBRID_KEYRING=__HYBRID_KEYRING__;'
    if html.count(marker)!=1:raise SystemExit('hybrid keyring marker missing')
    html=html.replace(marker,'const HYBRID_KEYRING='+json.dumps(keyring,separators=(',',':'))+';',1)
    literal=json.dumps(env,separators=(',',':'))
    html,n=re.subn(r'const ENCRYPTED_PAYLOAD=\{.*?\};\s*let data=', 'const ENCRYPTED_PAYLOAD='+literal+';\nlet data=',html,count=1,flags=re.S)
    if n!=1:raise SystemExit('production envelope overlay failed')
    html=html.replace('<title>31 SKU 选品决策卡</title>','<title>动态SKU 选品决策卡</title>')
    html=html.replace('31个SKU数据已加密存储。关闭或重新加载页面后需要重新输入密码。','动态SKU数据已加密存储。关闭或重新加载页面后需要重新输入密码。')
    html=html.replace('<h1>31 SKU 选品决策驾驶舱</h1>','<h1>动态SKU 选品决策驾驶舱</h1>')
    index=out/'index.html';index.write_text(html,encoding='utf-8')
    env_tmp=out/'.build-envelope.json';env_tmp.write_text(literal,encoding='utf-8')
    meta=externalize(index,env_tmp,out/'sku-data.enc.json',out/'pwa-data-version.json')
    env_tmp.unlink(missing_ok=True)

    # After the migration shell has been externalized, prefer the new data-only fragments.
    # This keeps HTML/UI stable while daily SKU changes touch only encrypted data + version metadata.
    if data_src.exists() and all((data_src/p).exists() for p in DYNAMIC_DATA_PARTS):
        dynamic_text=''.join((data_src/p).read_text(encoding='utf-8') for p in DYNAMIC_DATA_PARTS)
        dynamic=json.loads(dynamic_text)
        if dynamic.get('kind')!='SKU-PWA-HYBRID-ENVELOPE':raise SystemExit('dynamic data envelope invalid')
        if dynamic.get('keyWrapping',{}).get('publicKeyFingerprintSha256')!=fp:raise SystemExit('dynamic data key fingerprint mismatch')
        version_path=data_src/'pwa-data-version.json'
        if not version_path.exists():raise SystemExit('dynamic pwa-data-version.json missing')
        version=json.loads(version_path.read_text(encoding='utf-8'))
        if dynamic.get('records')!=version.get('records'):raise SystemExit('dynamic data/version record mismatch')
        dynamic_sha=hashlib.sha256(dynamic_text.encode('utf-8')).hexdigest()
        if version.get('envelopeSha256')!=dynamic_sha:raise SystemExit('dynamic envelope SHA mismatch')
        (out/'sku-data.enc.json').write_text(dynamic_text,encoding='utf-8')
        (out/'pwa-data-version.json').write_text(json.dumps(version,ensure_ascii=False,indent=2),encoding='utf-8')
        meta={'records':dynamic['records'],'version':version['version'],'envelopeSha256':dynamic_sha,'dataMode':'dynamic-fragments'}
    else:
        meta={**meta,'dataMode':'legacy-envelope-migration'}

    shutil.copy2(src/'manifest.webmanifest',out/'manifest.webmanifest')
    sw=(src/'sw.external.js').read_text(encoding='utf-8')
    old="const obs=new MutationObserver(()=>{ensureAutomationCenter();ensureChatGptBridge();renderAutomationCenter();});"
    new="const obs=new MutationObserver(()=>{ensureAutomationCenter();ensureChatGptBridge();});"
    if old not in sw:raise SystemExit('automation observer marker drifted')
    sw=sw.replace(old,new,1)
    (out/'sw.js').write_text(sw,encoding='utf-8')
    for size in (180,192,512):
        raw=base64.b64decode((icon_src/f'icon-{size}.b64').read_text(encoding='utf-8'))
        (out/'icons'/f'icon-{size}.png').write_bytes(raw)
    (out/'.nojekyll').write_text('',encoding='utf-8')
    (out/'automation-modules.json').write_text(json.dumps({'schema':'SKU-AUTOMATION-ROADMAP-V1','coreBundles':CORE_BUNDLES,'modules':MODULE_REGISTRY},ensure_ascii=False,indent=2),encoding='utf-8')
    html_after=index.read_text(encoding='utf-8')
    if '"kind":"SKU-PWA-HYBRID-ENVELOPE"' in html_after:raise SystemExit('externalized HTML still contains encrypted dataset')
    if 'sku-data.enc.json' not in html_after or 'pwa-data-version.json' not in html_after:raise SystemExit('external data loader missing')
    if 'renderAutomationCenter();});obs.observe' in sw:raise SystemExit('self-triggering automation observer remains')
    return meta

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.root,a.output),separators=(',',':')))
if __name__=='__main__':main()
