from __future__ import annotations

import argparse, base64, json, re, shutil, sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(HERE))
from automation_modules import MODULE_REGISTRY, CORE_BUNDLES
from externalize_pwa_payload import externalize

INDEX_PARTS=[f'index.part{i:02d}' for i in range(1,10)]
ENV_PARTS=['full-envelope.part01','full-envelope.part02','full-envelope.part03','full-envelope.part04a','full-envelope.part04b']

def build(root:Path,out:Path)->dict:
    src=root/'sku-pwa-auth-src'; icon_src=root/'sku-pwa-src'
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
    # Remove historical fixed-count UI before publishing the dynamic shell.
    html=html.replace('<title>31 SKU 选品决策卡</title>','<title>动态SKU 选品决策卡</title>')
    html=html.replace('31个SKU数据已加密存储。关闭或重新加载页面后需要重新输入密码。','动态SKU数据已加密存储。关闭或重新加载页面后需要重新输入密码。')
    html=html.replace('<h1>31 SKU 选品决策驾驶舱</h1>','<h1>动态SKU 选品决策驾驶舱</h1>')
    index=out/'index.html';index.write_text(html,encoding='utf-8')
    env_tmp=out/'.build-envelope.json';env_tmp.write_text(literal,encoding='utf-8')
    meta=externalize(index,env_tmp,out/'sku-data.enc.json',out/'pwa-data-version.json')
    env_tmp.unlink(missing_ok=True)
    shutil.copy2(src/'manifest.webmanifest',out/'manifest.webmanifest')
    shutil.copy2(src/'sw.external.js',out/'sw.js')
    for size in (180,192,512):
        raw=base64.b64decode((icon_src/f'icon-{size}.b64').read_text(encoding='utf-8'))
        (out/'icons'/f'icon-{size}.png').write_bytes(raw)
    (out/'.nojekyll').write_text('',encoding='utf-8')
    (out/'automation-modules.json').write_text(json.dumps({'schema':'SKU-AUTOMATION-ROADMAP-V1','coreBundles':CORE_BUNDLES,'modules':MODULE_REGISTRY},ensure_ascii=False,indent=2),encoding='utf-8')
    html_after=index.read_text(encoding='utf-8')
    if '"kind":"SKU-PWA-HYBRID-ENVELOPE"' in html_after:raise SystemExit('externalized HTML still contains encrypted dataset')
    if 'sku-data.enc.json' not in html_after or 'pwa-data-version.json' not in html_after:raise SystemExit('external data loader missing')
    return meta

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--output',type=Path,required=True);a=p.parse_args();print(json.dumps(build(a.root,a.output),separators=(',',':')))
if __name__=='__main__':main()
