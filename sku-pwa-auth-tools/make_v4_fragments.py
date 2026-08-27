from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

OLD_PARTS=(
    'full-envelope.part01','full-envelope.part02','full-envelope.part03',
    'full-envelope.part04a','full-envelope.part04b',
)
NEW_PARTS=tuple(f'sku-data.part{i:02d}' for i in range(1,10))


def split_even(text:str, count:int)->list[str]:
    base,extra=divmod(len(text),count)
    out=[];offset=0
    for i in range(count):
        size=base+(1 if i<extra else 0)
        out.append(text[offset:offset+size]);offset+=size
    if ''.join(out)!=text:
        raise SystemExit('fragment reassembly mismatch')
    return out


def build(root:Path)->dict:
    src=root/'sku-pwa-auth-src';out=root/'sku-pwa-auth-data'
    text=''.join((src/p).read_text(encoding='utf-8') for p in OLD_PARTS)
    env=json.loads(text)
    if env.get('kind')!='SKU-PWA-HYBRID-ENVELOPE':
        raise SystemExit('source envelope is not hybrid')
    records=env.get('records')
    if not isinstance(records,int) or records<1:
        raise SystemExit('invalid record count')
    out.mkdir(parents=True,exist_ok=True)
    pieces=split_even(text,len(NEW_PARTS))
    for name,piece in zip(NEW_PARTS,pieces):
        (out/name).write_text(piece,encoding='utf-8')
    reassembled=''.join((out/p).read_text(encoding='utf-8') for p in NEW_PARTS)
    if reassembled!=text:
        raise SystemExit('written fragment reassembly mismatch')
    sha=hashlib.sha256(text.encode('utf-8')).hexdigest()
    version={
        'schema':'SKU-PWA-EXTERNAL-DATA-V1',
        'version':sha[:16],
        'records':records,
        'envelopeSha256':sha,
        'payloadSchema':env.get('payloadSchema'),
        'fragmentCount':len(NEW_PARTS),
    }
    (out/'pwa-data-version.json').write_text(json.dumps(version,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'records':records,'version':version['version'],'envelopeSha256':sha,'fragmentCount':len(NEW_PARTS),'fragmentBytes':[len(x.encode('utf-8')) for x in pieces]}


def main()->None:
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent.parent)
    a=p.parse_args()
    print(json.dumps(build(a.root),separators=(',',':')))

if __name__=='__main__':
    main()
