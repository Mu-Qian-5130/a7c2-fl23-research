"""Original CP RPC registration/callback slices on explicit synthetic objects.

Stops BEFORE allocation, lookup, locks, free and indirect callbacks. Independent
post-service inputs are not successful native calls or physical admission.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import UC_PROT_READ,UC_PROT_EXEC,UC_MEM_WRITE
from unicorn import arm_const as R
from support.reference import SPECS,CP_LOAD_BASE,file_span

BASE=CP_LOAD_BASE
MEM,STACK,STOP=0x30000000,0x40000000,0x50000000
HANDLE,RECORD,QUEUE,MESSAGE=MEM+0x100,MEM+0x200,MEM+0x300,MEM+0x400
COUNTER,DEBUG=0x1b20b88,0x1b20bc0
SPANS=((0x45c8f8,0x10a),(0xae3c34,0x2c))
ARGS=tuple(getattr(R,'UC_ARM_REG_R'+str(i)) for i in range(4))
SAVED=tuple(getattr(R,'UC_ARM_REG_R'+str(i)) for i in range(4,12))


class Source:
    def __init__(self,raw):
        if hashlib.sha256(raw).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
            raise ValueError('Exact original stock CP required')
        self.u=u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        extent=(len(raw)+4095)&~4095
        u.mem_map(BASE,extent,UC_PROT_READ|UC_PROT_EXEC);u.mem_write(BASE,raw)
        for address,size in ((MEM,4096),(STACK,65536),(STOP,4096),(COUNTER&~4095,4096)):
            u.mem_map(address,size)
        self.decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
        self.stops=set();self.seen=[];self.reads=[];self.writes=[];self.ranges=[]
        u.hook_add(UC_HOOK_CODE,self.code)
        u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,self.access)

    def access(self,cpu,kind,address,size,value,_):
        allowed=((MEM,4096),(STACK,65536),(COUNTER&~4095,4096))
        assert any(start<=address and address+size<=start+length for start,length in allowed), 'Unexpected data access'
        if kind==UC_MEM_WRITE:self.writes.append((address,size,value))
        else:self.reads.append((address,size))

    def code(self,cpu,address,size,_):
        if address in self.stops:
            self.seen.append(address);cpu.emu_stop();return
        assert any(start<=address<start+length for start,length in self.ranges),'Unexpected code boundary'
        instruction=next(self.decoder.disasm(bytes(cpu.mem_read(address,size)),address,count=1))
        assert instruction.mnemonic not in ('bl','blx'),'Native service/callback must remain unexecuted'

    def reset(self):
        self.u.mem_write(MEM,b'\xa5'*4096);self.u.mem_write(STACK,bytes(65536))
        self.u.mem_write(COUNTER&~4095,bytes(4096))
        self.u.reg_write(R.UC_ARM_REG_CPSR,0x1f3)
        for index,register in enumerate(SAVED):self.u.reg_write(register,0xc1000000+index)
        self.u.reg_write(R.UC_ARM_REG_SP,STACK+0x8000);self.u.reg_write(R.UC_ARM_REG_LR,STOP|1)

    def run(self,offset,stops,registers=(),span=SPANS[0]):
        self.stops={STOP,*[BASE+at for at in stops]}
        self.ranges=[(BASE+span[0],span[1])]
        self.seen.clear();self.reads.clear();self.writes.clear()
        for register,value in registers:self.u.reg_write(register,value&0xffffffff)
        self.u.emu_start((BASE+offset)|1,0xffffffff,count=512)
        assert len(self.seen)==1 and self.u.reg_read(R.UC_ARM_REG_PC)==self.seen[0],'Missing exact boundary'
        return self.seen[0]

    def begin(self,route,handle=HANDLE,callback=None,context=0):
        self.reset()
        if callback is None:callback=BASE+0x45e6d9
        return self.run(0x45c8f8,(0x45c92e,0x45c9d4),zip(ARGS,(route,handle,callback,context)))


def audit(raw,current=None):
    source=Source(raw);u=source.u
    get=lambda at:struct.unpack('<I',bytes(u.mem_read(at,4)))[0]
    put=lambda at,value:u.mem_write(at,struct.pack('<I',value))
    cases=[]
    # Independently decode every external-call boundary and native thunk.
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    calls={0x45c92e:0x45c4f0,0x45c980:0xae399a,0x45c98a:0xae37dc,
           0x45c9a8:0xae3838,0x45c9f4:0x45c64c,
           0xae3c44:0xae3838,0xae3c54:0xae37dc}
    for at,target in calls.items():
        insn=next(decoder.disasm(file_span(raw,at,4),at,count=1))
        assert insn.mnemonic=='bl' and insn.op_str==f'#{target:#x}'
    assert next(decoder.disasm(file_span(raw,0xae3c50,2),0xae3c50,count=1)).mnemonic=='blx'
    for route in (0x908f084b,0x908f8001,0x908f0000):
        for handle,callback in ((0,BASE+0x45e6d9),(HANDLE,0),(0,0)):
            assert source.begin(route,handle,callback)==STOP
            assert u.reg_read(R.UC_ARM_REG_R0)==0xfffffc00
            assert not any(address<STACK or address>=STACK+65536 for address,size,value in source.writes)
            cases.append(dict(case='null-handle-or-callback',route=route,handle=bool(handle),callback=bool(callback),status=-1024))
    assert source.begin(0x908f8001)==STOP
    assert u.reg_read(R.UC_ARM_REG_R0)==0xfffffc00
    cases.append(dict(case='route-bit15-rejected',status=-1024))
    # Low15==0 uses an explicit synthetic diagnostic-state pointer/flag.
    source.reset();put(DEBUG,MEM+0x500);u.mem_write(MEM+0x517,b'\0')
    assert source.run(0x45c8f8,(0x45c92e,0x45c9d4),zip(ARGS,(0x908f0000,HANDLE,BASE+0x45e6d9,0)))==STOP
    assert u.reg_read(R.UC_ARM_REG_R0)==0xfffffc00
    cases.append(dict(case='zero-low15-route-debug-disabled',status=-1024,debug_state_synthetic=True))
    for route in (0x908f084b,0x908f0001,0x908f7fff):
        assert source.begin(route)==BASE+0x45c92e
        assert [u.reg_read(register) for register in ARGS[:2]]==[0,0]
        cases.append(dict(case='accepted-prefix-stops-before-allocator',route=route,allocator_called=False))
    # Independent post-allocator rejection, not a fabricated allocation return.
    assert source.begin(0x908f084b)==BASE+0x45c92e
    assert source.run(0x45c932,(),((R.UC_ARM_REG_R0,0),))==STOP
    assert u.reg_read(R.UC_ARM_REG_R0)==0xfffffc01 and get(HANDLE)==0xa5a5a5a5
    cases.append(dict(case='independent-post-allocation-null',status=-1023,handle_untouched=True))
    for initial in (0,7):
        for context in (0,0x84a17e01):
            assert source.begin(0x908f084b,context=context)==BASE+0x45c92e
            put(COUNTER,initial)
            assert source.run(0x45c932,(0x45c980,),((R.UC_ARM_REG_R0,RECORD),))==BASE+0x45c980
            expected=bytearray(32)
            struct.pack_into('<I',expected,8,BASE+0xae3c35)
            struct.pack_into('<2I',expected,0x14,BASE+0x45e6d9,context)
            assert bytes(u.mem_read(RECORD,32))==bytes(expected)
            assert get(COUNTER)==initial+1 and get(HANDLE)==RECORD
            assert u.reg_read(R.UC_ARM_REG_R0)==0x84b
            cases.append(dict(case='independent-post-allocation-publication',initial_counter=initial,
                context=context,record_bytes=32,handle_published_before_lookup_and_lock=True,lookup_called=False))
            # Null lookup -> counter decrement then BEFORE record free.
            assert source.run(0x45c984,(0x45c98a,0x45c9f4),((R.UC_ARM_REG_R0,0),))==BASE+0x45c9f4
            assert get(COUNTER)==initial and get(HANDLE)==RECORD and u.reg_read(R.UC_ARM_REG_R0)==RECORD
            cases.append(dict(case='independent-null-lookup-cleanup-boundary',context=context,
                counter_restored=True,published_handle_not_cleared_before_free=True,free_called=False))
    for existing in (0,MEM+0x600):
        assert source.begin(0x908f084b)==BASE+0x45c92e
        assert source.run(0x45c932,(0x45c980,),((R.UC_ARM_REG_R0,RECORD),))==BASE+0x45c980
        put(QUEUE+0x14,existing);put(QUEUE+0x1c,MEM+0x700)
        assert source.run(0x45c984,(0x45c98a,),((R.UC_ARM_REG_R0,QUEUE),))==BASE+0x45c98a
        assert u.reg_read(R.UC_ARM_REG_R0)==MEM+0x700
        cases.append(dict(case='independent-queue-lock-boundary',occupied=bool(existing),lock_called=False))
        assert source.run(0x45c98e,(0x45c9a8,))==BASE+0x45c9a8
        assert get(QUEUE+0x14)==(existing or RECORD)
        assert u.mem_read(RECORD+0xd,1)==(b'\0' if existing else b'\1')
        status=u.reg_read(R.UC_ARM_REG_R9)
        assert status==(0xfffffc00 if existing else 0)
        cases.append(dict(case='independent-post-lock-attachment',occupied=bool(existing),
            existing_preserved=bool(existing),status_before_unlock=-1024 if existing else 0,unlock_called=False))
        at=source.run(0x45c9ac,(0x45c9f4,))
        assert at==(BASE+0x45c9f4 if existing else STOP)
        assert get(HANDLE)==RECORD
        if not existing:
            assert u.reg_read(R.UC_ARM_REG_R0)==0 and get(COUNTER)==1
            assert u.reg_read(R.UC_ARM_REG_SP)==STACK+0x8000
            assert all(u.reg_read(register)==0xc1000000+i for i,register in enumerate(SAVED))
        else:assert get(COUNTER)==0 and u.reg_read(R.UC_ARM_REG_R0)==RECORD
        cases.append(dict(case='independent-post-unlock-tail',occupied=bool(existing),
            returned_success=not existing,stopped_before_free=bool(existing),published_handle_unchanged=True))
    # Exact registered thunk releases the owner lock before invoking callback.
    for callback in (BASE+0x45e6d9,BASE+0x45e725):
        for context in (0,0x84a17e01):
            source.reset();put(QUEUE+0x1c,MEM+0x700)
            put(RECORD+0x14,callback);put(RECORD+0x18,context)
            at=source.run(0xae3c34,(0xae3c44,),zip(ARGS,(MESSAGE,RECORD,QUEUE)),span=SPANS[1])
            assert at==BASE+0xae3c44 and u.reg_read(R.UC_ARM_REG_R0)==MEM+0x700
            assert source.run(0xae3c48,(0xae3c50,),span=SPANS[1])==BASE+0xae3c50
            assert [u.reg_read(register) for register in ARGS[:3]]==[MESSAGE+0x18,context,callback]
            cases.append(dict(case='independent-post-unlock-callback-boundary',callback=callback,context=context,
                payload_offset=24,callback_called=False))
            assert source.run(0xae3c52,(0xae3c54,),span=SPANS[1])==BASE+0xae3c54
            assert u.reg_read(R.UC_ARM_REG_R0)==MEM+0x700
            assert source.run(0xae3c58,(),span=SPANS[1])==STOP
            assert u.reg_read(R.UC_ARM_REG_R0)==0 and u.reg_read(R.UC_ARM_REG_SP)==STACK+0x8000
            assert all(u.reg_read(register)==0xc1000000+i for i,register in enumerate(SAVED))
            cases.append(dict(case='independent-post-callback-relock-return',callback_called=False,relock_called=False))
    spans=[dict(file_offset=at,bytes=size,sha256=hashlib.sha256(file_span(raw,at,size)).hexdigest()) for at,size in SPANS]
    result=dict(schema='OFFLINE_CP_RPC_REGISTRATION_BOUNDARIES/1',camera_io=False,
        source_sha256=hashlib.sha256(raw).hexdigest(),source_FILE_spans=spans,cases=cases,
        findings=['Registration publishes the handle before lookup, lock and callback attachment',
                  'Failure paths reach record free while the published handle still holds that pointer',
                  'The native callback thunk unlocks before calling payload+24 with the saved context',
                  'Independent post-callback instructions reacquire the owner lock then return zero'],
        limits=['All objects/counters/debug flags and post-service inputs are synthetic',
                'No allocator, lookup, lock, free, indirect callback or peripheral service executes',
                'These failure slices do not demonstrate a reachable physical defect',
                'FILE span equality does not prove loaded text, live registration or remote quiescence',
                'No RAM/ROM candidate, CP request, recovery or physical pre-capture is produced'])
    if current is not None:
        if len(current)!=len(raw):raise ValueError('Current CP extent differs')
        for at,size in SPANS:
            if file_span(current,at,size)!=file_span(raw,at,size):raise ValueError('Current diagnostic span differs')
        result['current_FILE_comparison']=dict(sha256=hashlib.sha256(current).hexdigest(),
            named_spans_equal=True,loaded_source_or_native_admission=False)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--current-cp',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(args.cp.read_bytes(),args.current_cp.read_bytes() if args.current_cp else None)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print(f"{len(result['cases'])} original registration/callback slices; no CP request or camera operation")


if __name__=='__main__':main()
