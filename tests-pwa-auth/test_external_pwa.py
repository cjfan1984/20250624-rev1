import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'sku-pwa-auth-tools'))
from build_external_site import build


def test_external_site_build(tmp_path):
    root=Path(__file__).parents[1]
    out=tmp_path/'site'
    meta=build(root,out)
    assert meta['records']>0
    assert (out/'index.html').exists()
    assert (out/'sku-data.enc.json').exists()
    assert (out/'pwa-data-version.json').exists()
    index=(out/'index.html').read_text(encoding='utf-8')
    assert 'sku-data.enc.json' in index
    assert 'pwa-data-version.json' in index
    assert '"kind":"SKU-PWA-HYBRID-ENVELOPE"' not in index
    env=json.loads((out/'sku-data.enc.json').read_text(encoding='utf-8'))
    version=json.loads((out/'pwa-data-version.json').read_text(encoding='utf-8'))
    assert env['records']==version['records']==meta['records']
    assert env['kind']=='SKU-PWA-HYBRID-ENVELOPE'
    sw=(out/'sw.js').read_text(encoding='utf-8')
    assert 'networkFirst' in sw
    assert 'sku-data.enc.json' in sw
    assert 'pwa-data-version.json' in sw
    assert 'SKU自动化中心' in sw
    roadmap=json.loads((out/'automation-modules.json').read_text(encoding='utf-8'))
    assert len(roadmap['modules'])==25
    assert len(roadmap['coreBundles'])==6
