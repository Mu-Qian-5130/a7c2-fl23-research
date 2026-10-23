"""Original stock CP diagnostic default response; no patch, send or native call.

Unsupported byte modes execute original instructions. Supported modes stop
BEFORE their first branch body. This does not qualify dispatch or teardown.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn import UC_PROT_READ,UC_PROT_EXEC
from unicorn import UC_MEM_WRITE
from unicorn import arm_const as R
from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
from support.reference import SPECS,CP_LOAD_BASE,file_span

SOURCE=SPECS['a7c2-2.01']['sha256']
BASE=CP_LOAD_BASE
ENTRY,SUPPORTED,END=(BASE+offset for offset in (0x45e6d8,0x45e6f6,0x45e7c0))
REG_ENTRY,REG_CALL=(BASE+offset for offset in (0x45e680,0x45e69e))
MESSAGE,STACK,STOP=0x30000100,0x40000000,0x50000000
PRESERVED=tuple(getattr(R,'UC_ARM_REG_R'+str(index)) for index in range(4,12))


def audit(raw):
    if hashlib.sha256(raw).hexdigest()!=SOURCE:
        raise ValueError('Exact original stock CP2.01 required')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    u.mem_map(BASE,(len(raw)+4095)&~4095,UC_PROT_READ|UC_PROT_EXEC);u.mem_write(BASE,raw)
    u.mem_map(MESSAGE&~4095,4096);u.mem_map(STACK,65536);u.mem_map(STOP,4096,UC_PROT_READ|UC_PROT_EXEC)
    seen=[];writes=[];reads=[];registration=False
    native_sites={BASE+offset for offset in (0x45e73c,0x45e748,0x45e75c,0x45e7a4)}
    def code(cpu,at,size,_):
        if registration:
            if at==REG_CALL:seen.append(at);cpu.emu_stop();return
            if not REG_ENTRY<=at<REG_CALL:raise AssertionError('Unexpected registration-prefix boundary')
            return
        if at in (SUPPORTED,STOP):seen.append(at);cpu.emu_stop();return
        if not ENTRY<=at<END:raise AssertionError('Unexpected callback/native-service boundary')
        # Source contains BL/BLX in supported bodies. None is executed here.
        if at in native_sites:
            raise AssertionError('Native service must remain unexecuted')
    def access(cpu,kind,address,size,value,_):
        if kind==UC_MEM_WRITE:
            if MESSAGE<=address and address+size<=MESSAGE+24:writes.append((address-MESSAGE,size,value))
            elif not STACK+0x7f00<=address<address+size<=STACK+0x8000:
                raise AssertionError('Write outside message/private stack')
        else:
            reads.append((address,size))
            if not (MESSAGE<=address<address+size<=MESSAGE+24 or
                    STACK+0x7f00<=address<address+size<=STACK+0x8000):
                raise AssertionError('Unexpected global, peripheral or service input')
    u.hook_add(UC_HOOK_CODE,code)
    u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,access)
    cases=[]
    for mode in range(256):
        for fill in (0,0xa5,0xff):
            page=bytearray([0x6b]*4096)
            message=bytearray([fill]*24);message[0]=mode
            # Nonzero tail verifies the native default does not forge an echo.
            struct.pack_into('<I',message,20,0x84a17e01)
            page[0x100:0x118]=message
            u.mem_write(MESSAGE&~4095,bytes(page));u.mem_write(STACK+0x7f00,b'\xa7'*256)
            u.reg_write(R.UC_ARM_REG_CPSR,0x1f3)
            for index,register in enumerate(PRESERVED):u.reg_write(register,0xc1000000+index)
            u.reg_write(R.UC_ARM_REG_R0,MESSAGE);u.reg_write(R.UC_ARM_REG_SP,STACK+0x8000)
            u.reg_write(R.UC_ARM_REG_LR,STOP|1)
            seen.clear();writes.clear();reads.clear()
            u.emu_start(ENTRY|1,0xffffffff,count=200)
            supported=1<=mode<=4
            assert seen==[SUPPORTED if supported else STOP],(mode,seen)
            actual=bytes(u.mem_read(MESSAGE,24))
            if supported:
                assert not writes and actual==bytes(message)
            else:
                expected=bytearray(message);expected[1]=0x80;expected[8:20]=bytes(12)
                assert actual==bytes(expected)
                assert sorted((offset,size) for offset,size,value in writes)==[(1,1),(8,4),(12,4),(16,4)]
                assert u.reg_read(R.UC_ARM_REG_R0)==0
                assert u.reg_read(R.UC_ARM_REG_SP)==STACK+0x8000
                assert all(u.reg_read(register)==0xc1000000+index for index,register in enumerate(PRESERVED))
                actual_page=bytes(u.mem_read(MESSAGE&~4095,4096));page[0x100:0x118]=expected
                assert actual_page==bytes(page)
            cases.append(dict(mode=mode,initial_fill=fill,supported_body_stopped=supported,
                              original_default_returned=not supported,native_calls=0,
                              peripheral_or_global_data_reads=0))
    # This pointer is constructed by MOVW/MOVT, not stored as a literal word.
    # Independently decode BL at FILE coordinates, then execute the prefix
    # only up to that call. Registration itself is never called or stubbed.
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    call=next(decoder.disasm(file_span(raw,REG_CALL-BASE,4),REG_CALL-BASE,count=1))
    assert call.mnemonic=='bl' and call.op_str=='#0x45c8f8'
    registration=True;seen.clear();writes.clear();reads.clear()
    u.reg_write(R.UC_ARM_REG_CPSR,0x1f3);u.reg_write(R.UC_ARM_REG_SP,STACK+0x8000)
    u.reg_write(R.UC_ARM_REG_LR,STOP|1)
    u.emu_start(REG_ENTRY|1,0xffffffff,count=40)
    assert seen==[REG_CALL] and not reads and not writes
    arguments=[u.reg_read(register) for register in (R.UC_ARM_REG_R0,R.UC_ARM_REG_R1,R.UC_ARM_REG_R2,R.UC_ARM_REG_R3)]
    assert arguments==[0x908f084b,0x1a7e96c,ENTRY|1,0]
    pointer=struct.pack('<I',ENTRY|1)
    references=[];at=raw.find(pointer)
    while at>=0:
        references.append(at);at=raw.find(pointer,at+1)
    return dict(schema='OFFLINE_ORIGINAL_CP_RPC_DEFAULT/1',camera_io=False,source_sha256=SOURCE,
                callback_file_offset=ENTRY-BASE,callback_extent=END-ENTRY,
                callback_sha256=hashlib.sha256(raw[ENTRY-BASE:END-BASE]).hexdigest(),
                embedded_callback_pointer_references=references,cases=cases,
                registration_prefix=dict(constructor_file_offset=REG_ENTRY-BASE,call_file_offset=REG_CALL-BASE,
                    callee_file_offset=0x45c8f8,argument_values=arguments,
                    registration_called=False,live_registration_proven=False),
                unsupported_mode_count=252,supported_mode_count=4,
                response=dict(status_offset=1,status=0x80,zeroed_offsets=[8,12,16],tail_nonce_untouched=True),
                limits=['All byte modes are explicit synthetic message inputs, not camera settings',
                        'Supported modes stop before their body; no service return is fabricated',
                        'Callback bytes do not qualify live registration, kernel transport or CP receipt',
                        'No native timing, RPC completion, remote quiescence or safe-send admission',
                        'No patch or firmware image is generated; physical pre-capture remains unfinished'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=audit(args.cp.read_bytes())
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2);stream.write('\n')
    print('756 original default returns;12 supported-mode boundaries; original registration args stop before call')


if __name__=='__main__':main()
