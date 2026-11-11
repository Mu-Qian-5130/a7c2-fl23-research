"""Check the static-only relocation against previously prepared fixed images."""
from pathlib import Path
import argparse,base64,json,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'src/looks')]
from desktopapp import fixedruntime,firmwarefeatures,cameraapi
from looktool import fixedbank,photoformat,photofull,lookfile,device_layout
from looktool.devicesession import modules

def main(a):
    out=a.output;out.mkdir(parents=True,exist_ok=False)
    records=modules()[1].backup_records((a.inputs/'settings-ram.bin').read_bytes());cases=[]
    assert firmwarefeatures.options(dict(custom_looks=True))['fixed_looks']is True
    for name,mask in [('default-six',63),('selected-1-and-6',33),('neutral-six',63)]:
        prior=a.prior/name;folder=prior/'fixed-look-runtime'
        expected=(prior/'cpapp-b.bin').read_bytes();ap=(prior/'appFw.so').read_bytes()
        source=bytearray(expected)
        for edit in reversed(json.loads((folder/'layout.json').read_text(encoding='utf-8'))['windows']):
            raw=bytes.fromhex(edit['before_hex']);source[edit['offset']:edit['offset']+len(raw)]=raw
        source[0xa000:0x20000]=(folder/'retired-prefix.bin').read_bytes()
        for edit in reversed(json.loads((folder/'consumers.json').read_text(encoding='utf-8'))['windows']):
            raw=bytes.fromhex(edit['before_hex']);source[edit['offset']:edit['offset']+len(raw)]=raw
        image=fixedbank.extract_cp(expected);parsed=fixedbank.parse(image)
        basis=photoformat.PhotoBank.unpack(parsed['basis']);selected=[]
        for i,(grid,record,kind)in enumerate(parsed['entries'],1):
            stage=photofull.decode_stage(kind,record[fixedbank.FIXED_RECORD+4:],basis)
            doc=dict(schema=lookfile.FULL_SCHEMA if kind==2 else lookfile.SCHEMA,name='ST',target=lookfile.TARGET,
                     base='ST',table_format=lookfile.FORMAT,table_base64=base64.b64encode(grid).decode('ascii'))
            if stage is not None:doc['edit_native'if kind==2 else'native_photo']=stage
            selected.append(dict(slot=i,name='ST',document=doc))
        current={'appFw.so':ap,'cpapp-b.bin':bytes(source)}
        cp,actual,meta=fixedruntime.prepare_source(current,out/name,records,selected)
        assert cp==expected and actual==image,(name,'relocated CP bytes differ')
        assert meta['ordinary_generator_default_changed']is True
        assert meta['activation_policy']=='existing static restart workflow'
        assert meta['root_fields']==['base','size']and not meta['live_reload_added']
        assert device_layout.structural(ap,cp)['mask']==mask
        config=cameraapi.configuration(dict(current,**{'cpapp-b.bin':cp}))
        assert '#define API_FIXED_BANK 1'in config and 'dynamic'not in config
        cases.append(dict(case=name,mask=mask,CP_and_image_exact=True,source_inverse_exact=True))
        print('STATIC_FIXED_SOURCE_PASSED',name,flush=True)
    r=dict(status='PASSED',cases=cases,ordinary_default_fixed=True,static_baseline=True,
           runtime_platform_added=False,live_reload_deferred=True,new_hashes=False,camera_io=False)
    (out/'report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('prior','inputs','output'):p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
