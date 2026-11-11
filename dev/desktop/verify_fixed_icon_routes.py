"""Execute original C2 live icon consumers and complete playback enum domains."""
import argparse,json,struct
from pathlib import Path
import verify_fixed_looks_native as native

def verify(source):
    native.configure(source)
    Native,DATA,BASE=native.Native,native.DATA,native.BASE
    model,obj,photo=DATA+0x1000,DATA+0x6000,DATA+0x8000
    param=obj+0x1d8;gold={};counts={}
    def setup(n):
        n.put(model,bytes(0x4500));n.put(obj,bytes(0x1000))
        n.hooks.update({0x17e9b98:lambda n,a:n.ret(),0x17eb1a4:lambda n,a:n.ret()})
        return {n.run(0x2d508c0,v):v for v in range(19)}
    def draw(n,enums,selector,palette,selected):
        values=list(range(10))+[8]*6+[10,11]
        n.put(BASE+0x7eac508,struct.pack('<18I',*values));n.run(0x287ee10)
        n.put(model+0x30,n.read(BASE+0x7eac508,72))
        n.put(model,struct.pack('<I',enums[selector]));n.put(model+0x348,bytes([selected]))
        n.put(param+0x38,struct.pack('<I',palette))
        n.run(0x23d4830,0,param,0,model);n.run(0x17da44c,obj)
        return n.word(obj+0x3f8+0x3c)
    original=Native(None);enums=setup(original)
    for selector in range(18):
        for palette in (0,1):
            for selected in (0,1):gold[selector,palette,selected]=draw(original,enums,selector,palette,selected)
    for mask in range(64):
        n=Native(mask);enums=setup(n)
        for selector in range(18):
            for palette in (0,1):
                for selected in (0,1):
                    result=draw(n,enums,selector,palette,selected)
                    if 10<=selector<=15 and mask>>(selector-10)&1:
                        slot=selector-10
                        want=((0x0200181a+13*slot if selected else 0x020033a3+slot) if palette else
                            (0x020008ef+13*slot if selected else 0x020006c5+slot))
                    else:want=gold[selector,palette,selected]
                    assert result==want,(mask,selector,palette,selected,hex(result),hex(want))
                    counts['base_to_original_translator_and_renderer']=counts.get('base_to_original_translator_and_renderer',0)+1
    # Full original view-model bytes are the control, not a second copy of the
    # new algorithm. Both original source modes and absent validity are covered.
    domain=[*range(256),0x10000,0xffffffff]
    for mode in (0,1):
        for valid in (0,1):
            original=Native(None);original.put(model,bytes(0x4500))
            original.put(model+0x4360,struct.pack('<I',mode))
            flag,field=(0xd60,0xd64) if mode==0 else (0x2f10,0x2f14)
            original.put(model+flag,bytes([valid]));control={}
            for value in domain:
                original.put(model+field,struct.pack('<I',value));original.put(photo,bytes([0xa5])*128)
                original.run(0x23d1cec,0,photo,0,model);control[value]=original.read(photo,128)
            for mask in range(64):
                n=Native(mask);n.put(model,bytes(0x4500));n.put(model+0x4360,struct.pack('<I',mode));n.put(model+flag,bytes([valid]))
                for value in domain:
                    n.put(model+field,struct.pack('<I',value));n.put(photo,bytes([0xa5])*128)
                    n.run(0x23d1cec,0,photo,0,model);actual=n.read(photo,128)
                    if valid and 249<=value<=254 and mask>>(value-249)&1:
                        expected=bytearray(control[0]);struct.pack_into('<I',expected,0x3c,0x020006c5+value-249)
                        assert actual==bytes(expected),(mode,valid,mask,value)
                    else:assert actual==control[value],(mode,valid,mask,value)
                    counts['playback_full_enum_and_validity']=counts.get('playback_full_enum_and_validity',0)+1
    return dict(passed=True,camera_io=False,counts=counts,
        complete_original_view_models_compared=True,
        original_graphics_functions_are_fixture_endpoints=True,
        playback_input_is_explicit_native_file_metadata_fixture=True,
        physical_viewfinder_or_photo_playback_verified=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-ap',type=Path,required=True);p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();result=verify(args.source_ap)
    args.report.write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result,indent=2))
