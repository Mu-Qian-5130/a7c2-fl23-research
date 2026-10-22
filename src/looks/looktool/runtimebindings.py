"""Keep saved Creative Look bases and the live AP property model in sync."""
from pathlib import Path
import struct
from .nativebuild import ROOT,compile_worker
from .devicesession import invoke

BASE_KEYS={0x02cf0cd0+2*i:10+i for i in range(6)}
BASE_KEYS.update({0x02cf1287:16,0x02cf1289:17})


def setting_array_changes(before,after,values):
    """Allow a selected setting's native per-setting copies to take its value.

    BK4 attr 0x80 denotes a Backup_read_setting_attr array, not another recipe.
    In C2 2.01 each base is followed by its 13 one-byte setting copies. Native
    setters can update those copies too. Never write them or allow arbitrary
    changes: only changed elements equal to the selected target are accepted.
    """
    changes={}
    for key,target in values.items():
        if key not in BASE_KEYS:continue
        companion=key+1
        old,new=before[0].get(companion),after[0].get(companion)
        if old is None and new is None:continue
        if old is None or new is None:raise ValueError('Look setting-array property missing: '+hex(companion))
        if (old.data,old.attr)==(new.data,new.attr):continue
        if old.attr!=0xc0 or new.attr!=old.attr or len(old.data)!=13 or len(new.data)!=13:
            raise ValueError('Look setting-array layout differs: '+hex(companion))
        if any(a!=b and b!=target for a,b in zip(old.data,new.data)):
            raise ValueError('Look setting-array changed outside the selected value: '+hex(companion))
        changes[companion]=new.data
    return changes

# Reviewed 2.01 function boundaries. This is a native menu operation, not the
# withdrawn ff2f04 notification or a patch to any display/preview instructions.
SIGNATURES={
    0x178f950:'fd7bbea9fd030091f30b00f9f30300aad8dc59947f0600f9f30b40f9fd7bc2a8c0035fd6',
    0x178f974:'fd7bbea9fd030091f30b00f9f30300aa000440f9400000b4a7c27b94e00313aaf30b40f9fd7bc2a8ccdb5914',
    0x2e06cc0:'fd7bb9a981d102d021e01791fd030091f55b02a9b6830191',
    0x2e068cc:'fd7bb9a981d102d021e01791fd030091f76303a9b7830191',
    0x287ee10:'80ae02d0006013910070419100c00091c0035fd680ae02d0006013910070419100e00191c0035fd6',
    0x286964c:'20af02f0006013910080409100000391c0035fd6',
    0x36830a8:'fd7bbca9fd030091f35301a9f30300aaa0030191f51300f9f40302aaf50303aa',
    0x2506ff0:'fd7bbca9fd030091f51300f9b5030191f35301a9a0ce1fb800b501d0e10315aa',
    0x2506218:'210080528effff17',
    0x2614bcc:'fd7bb7a9fd030091f76303a9b7830191e00317aaf35301a9f55b02a9b8630191f603012a',
    0x2614ca0:'b53740f95ba80994f40300aa5ea8099404058052637e4093219d8252bf1302396102010b7302249b040580d2820a038b',
    0x2614d10:'20008052a0170239a03b40f9160000b920008052a0130239a0c301919bffff97e00318aae6c61f94e00317aa0eebc597209d825235c5fb97f35341a9f55b42a9f76343a9f96b44a9fd7bc9a8',
}

def targets(ap,fields):
    # Descriptor attributes are one greater than the native model attributes.
    result=[]
    known=BASE_KEYS
    for key,value in sorted(fields.items()):
        if key not in known:continue
        index=known[key];attribute=0x14ea+index
        row=struct.unpack_from('<8I',ap,0x57c6710+index*32)
        if row[:3]!=(3,key,0x10000) or row[6]!=attribute or len(value)!=1 or value[0]>11:
            raise ValueError('Creative Look runtime binding descriptor differs')
        result.append(dict(key=key,index=index,value=value[0]))
    return sorted(result,key=lambda row:row['index'])

def build(ap,selected,directory,zig=None):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    lines=['struct Guard {u64 offset;u32 length;const u8 *code;};',
           'struct Target {u32 index,value;};']
    guards=[]
    for i,(offset,code) in enumerate(SIGNATURES.items()):
        raw=bytes.fromhex(code)
        if ap[offset:offset+len(raw)]!=raw:raise ValueError('Native look setter differs at '+hex(offset))
        lines.append('static const u8 code_'+str(i)+'[]={'+','.join(map(str,raw))+'};')
        guards.append('{'+hex(offset)+'UL,'+str(len(raw))+',code_'+str(i)+'}')
    lines+=['static const struct Guard guards[]={'+','.join(guards)+'};',
            'static const u32 guard_count='+str(len(guards))+';',
            'static const struct Target targets[]={'+','.join('{'+str(row['index'])+','+str(row['value'])+'}' for row in selected)+'};',
            'static const u32 target_count='+str(len(selected))+';']
    header=directory/'look-bindings.private.h';header.write_text('\n'.join(lines)+'\n',encoding='ascii')
    path=directory/'look-bindings.so'
    compile_worker(ROOT/'src/looks/native/look_bindings.c',header,path,zig,fingerprints=False)
    return dict(path=str(path),targets=selected)

def parse(raw,selected):
    if len(raw)!=192:raise ValueError('Incomplete native look-binding report')
    magic,version,count,status,model,reserved,current,after_current,changed,reserved2=struct.unpack_from('<8sIIq6I',raw)
    if (magic,version,count,status,model,reserved,reserved2)!=(b'A7LBS001',1,len(selected),0,16,0,0):
        raise ValueError('Native look-binding update incomplete: status='+str(status))
    before=list(struct.unpack_from('<18I',raw,48));after=list(struct.unpack_from('<18I',raw,120))
    expected=before[:];mask=0
    for row in selected:
        index=row['index'];expected[index]=row['value']
        if before[index]!=row['value']:mask|=1<<index
    if current!=after_current or after!=expected or changed!=mask:
        raise ValueError('Native look-binding readback or preservation differs')
    return dict(before=before,after=after,current=current,changed_mask=changed,targets=selected)

def sync(camera,owner,fields,expected=None):
    previous=getattr(owner,'_synced_look_bases',{})
    keys=BASE_KEYS
    fields={key:value for key,value in fields.items() if key in keys and previous.get(key)!=value[0]}
    if not fields:return None
    ap=getattr(owner,'_runtime_binding_ap',None)
    if ap is None:ap=camera.read('/usr/lib/appFw.so')
    selected=targets(ap,fields)
    for row in selected:
        if camera.property_read(row['key'])!=bytes([row['value']]):
            raise ValueError('Save selected look bases before native model synchronization')
    compiled=build(ap,selected,owner.root/'runtime-bindings'/str(len(owner.state['journal'])),owner.zig)
    result=invoke(camera,Path(compiled['path']).read_bytes(),stage='lut-runtime-staged.so',request=None,
        result='a7c2.runtime.result',contents=None,mode=1,decode=lambda raw:parse(raw,selected),
        record=owner.record,save_raw=lambda raw:owner.raw('look-bindings.bin',raw),extras=('a7c2.probe.result',))
    owned=dict(previous)
    owned.update({row['key']:row['value'] for row in selected})
    result['setting_array_updates']=[]
    # Native menu callbacks must preserve the saved/live backup result too.
    for i,memory in enumerate((True,False)):
        records=camera.records(camera.snapshot(memory))
        if any(records[0][row['key']].data!=bytes([row['value']]) for row in selected):
            raise ValueError('Look backup changed after native model synchronization')
        if expected is not None:
            from .devicesettings import compare
            changes=setting_array_changes(expected[i],records,owned)
            compare(expected[i],records,{key:value.hex() for key,value in changes.items()},camera.core)
            result['setting_array_updates'].append(dict(source='ram' if memory else 'saved',keys=[hex(k) for k in changes]))
    owner._synced_look_bases=owned
    owner.record('native_look_bases_synchronized',result=result)
    return result
