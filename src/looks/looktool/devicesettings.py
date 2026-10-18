"""Derive selected-slot writes from fresh descriptors; preserve unrelated data."""
import struct
from . import firmware,six

PROTECTED=(0x02a40000,0x02a40001,0x02a40002,0x02a4000d)

def plan(ap,ram,saved,slots):
    from .device_layout import identify_ap
    identify_ap(ap)
    if not slots or any(type(s) is not int or s not in range(1,7) for s in slots):raise ValueError('Select slots 1..6')
    def descriptor(attribute):
        at=0x57c6710+(attribute-0x14ea)*32
        row=struct.unpack_from('<8I',ap,at)
        if row[6]!=attribute or row[1]>>16!=0x02cf:raise ValueError('Descriptor identity/group mismatch')
        return row
    fields=[]
    for slot in sorted(set(slots)):
        selector=slot+9;row=descriptor(0x14ea+selector);key=row[1]
        if row[0]!=3 or row[2]!=0x10000 or len(ram[0][key].data)!=1 or len(saved[0][key].data)!=1:raise ValueError('Invalid base-look descriptor/value')
        fields.append({'slot':slot,'key':key,'before_ram':ram[0][key].data.hex(),'before_saved':saved[0][key].data.hex(),'after':'00'})
        for i in range(8):
            row=descriptor(0x1520+i*18+selector);base=descriptor(0x1520+i*18);key=row[1]
            value=ram[0][base[1]].data
            if row[0]!=0 or row[2]!=0x40000 or len(value)!=4 or len(ram[0][key].data)!=4 or len(saved[0][key].data)!=4:raise ValueError('Invalid adjustment descriptor/value')
            fields.append({'slot':slot,'key':key,'before_ram':ram[0][key].data.hex(),'before_saved':saved[0][key].data.hex(),'after':value.hex()})
    if len({f['key'] for f in fields})!=len(fields):raise ValueError('Duplicate selected settings')
    if any(f['before_ram']!=f['before_saved'] for f in fields):raise ValueError('Save selected camera recipes before importing; RAM/storage differ')
    return fields

def require_save_preserves_unsaved(ram,saved,selected):
    # The stored-only field is known to have a separate live representation;
    # it is still compared before/after and is never written by this module.
    for key,value in ram[0].items():
        if key>>16==0x02cf and key not in selected and key!=0x02cf0b6e:
            other=saved[0].get(key)
            if other is None or (value.data,value.attr)!=(other.data,other.attr):
                raise ValueError('Unselected unsaved AP settings would be persisted; save them first')

def controls(samples,core):
    """Three read-only controls; never infer permission from the write itself."""
    if len(samples)!=3:raise ValueError('Three independent settings controls required')
    proof={'saved_values':[],'ram_counter_observed':False}
    key=0x02cf0b6e;counter=0x02770015
    for ram,saved in samples:
        if key in saved[0]:
            v=saved[0][key]
            if v.attr!=64 or len(v.data)!=4:raise ValueError('Stored telemetry layout differs')
            proof['saved_values'].append(v.data.hex())
    proof['saved_values']=sorted(set(proof['saved_values']))
    for (ram1,saved1),(ram2,saved2) in zip(samples,samples[1:]):
        extra={}
        if counter in ram1[0] and counter in ram2[0]:
            a,b=ram1[0][counter],ram2[0][counter]
            delta=int.from_bytes(b.data,'little')-int.from_bytes(a.data,'little')
            if a.data!=b.data and len(a.data)==len(b.data)==4 and a.attr==b.attr and 0<delta<=120:
                extra[(0,counter)]=b.data;proof['ram_counter_observed']=True
        core.verify_preservation(ram1,ram2,extra)
        extra={(0,key):saved2[0][key].data} if key in saved1[0] else {}
        core.verify_preservation(saved1,saved2,extra)
    return proof

def compare(before,after,expected,core,proof=None,memory=True):
    allowed={(0,int(k)):bytes.fromhex(v) for k,v in expected.items()}
    proof=proof or {}
    key=0x02770015 if memory else 0x02cf0b6e
    if key in before[0] and key in after[0]:
        a,b=before[0][key],after[0][key]
        if len(a.data)==len(b.data)==4 and a.attr==b.attr:
            if memory and proof.get('ram_counter_observed'):
                if 0<=int.from_bytes(b.data,'little')-int.from_bytes(a.data,'little')<=600:allowed[(0,key)]=b.data
            elif not memory and a.attr==64:
                if a.data.hex() in proof.get('saved_values',[]) and b.data.hex() in proof.get('saved_values',[]):allowed[(0,key)]=b.data
    return core.verify_preservation(before,after,allowed)

def protected_equal(before,after):
    for key in PROTECTED:
        if (before[1][key].data,before[1][key].attr)!=(after[1][key].data,after[1][key].attr):raise ValueError('Protected CP unit changed')
