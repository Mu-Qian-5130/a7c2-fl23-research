"""Original loader EXEC_MODE producer and CP consumer contracts, all offline.

Backup, GPIO configuration/load and logging stop before execution. Independent
post-operation slices take explicitly synthetic inputs; no hardware success or
boot-ready flag is supplied. Copying a generated mode word into CP test RAM
checks its encoding only; it does not establish the physical AP/CP alias.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM64, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as X, arm_const as A
from support.reference import NOR_LOADER_SHA, SPECS
from support.boundaries import BoundaryRunner

MEM, STACK, STOP = 0x30000000, 0x40000000, 0x60000000


def put(cpu, at, value, width=4):
    cpu.mem_write(at, (value & ((1 << (width*8))-1)).to_bytes(width, 'little'))


def audit_loader(loader):
    if hashlib.sha256(loader).hexdigest() != NOR_LOADER_SHA:
        raise ValueError('Unsupported original NOR loader')
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for at, size in ((0,0x20000),(MEM,0x10000),(STACK,0x10000),(STOP,4096)):
        cpu.mem_map(at,size)
    cpu.mem_write(0,loader)
    class Services:
        calls={0xde7c:'backup_read',0xb50c:'logging',0xf188:'next_boot_stage',0xaba8:'GPIO_strap_getter'}
    run=BoundaryRunner(cpu,(Services(),),stop=STOP,stack=STACK)
    cases=[];words=set()
    got=run.call(0x97b0,(MEM,))
    assert got['call']=='backup_read' and got['args'][0]==0xfa0173
    cases.append(dict(case='EXEC_MODE-output-pointer-lookup',backup_ID='0xfa0173',lookup_executed=False))
    frame=STACK+0x7000;destination=MEM+0x4000
    for status,mode in ((status,mode) for status in (0,4) for mode in range(4)):
        for flags in range(8):
            context=bytearray([0xa5])*0x300;context[0x1f5]=mode;context[0x238]=flags
            cpu.mem_write(MEM,bytes(context))
            cpu.reg_write(X.UC_ARM64_REG_SP,frame);cpu.reg_write(X.UC_ARM64_REG_X19,MEM)
            put(cpu,frame+8,destination,8)
            # Post-backup slice. Status and pointer are independent fixtures.
            got=run.run(0x97d0,inputs=((X.UC_ARM64_REG_X0,status),))
            assert got['call']=='logging'
            low=cpu.reg_read(X.UC_ARM64_REG_X20)
            assert low==int(mode==1 and not flags&4)
            cpu.mem_write(destination-4,b'\xa5'*12)
            # Original writer after the omitted diagnostic. It consumes W20,
            # context bit0 and the explicit pointer, not a diagnostic result.
            got=run.run(0x9818)  # Original MOV W0,0; no logger result is supplied.
            assert got['call']=='next_boot_stage' and got['args'][0]==MEM
            expected=low | ((flags&1)<<8)
            assert bytes(cpu.mem_read(destination-4,12))==b'\xa5'*4+struct.pack('<I',expected)+b'\xa5'*4
            after=bytearray(context);struct.pack_into('<I',after,0x1b8,0)
            assert bytes(cpu.mem_read(MEM,len(context)))==bytes(after)
            words.add(expected)
            cases.append(dict(case='post-lookup-mode-writer',lookup_status=status,mode=mode,flags=flags,word=hex(expected),
                              physical_pointer_or_alias_qualified=False))
    # The producer of context bit0 calls a configured GPIO strap getter. It
    # also records reset/configuration selection in bit2, independently.
    for reset in (0,1):
        for strap in (0,1):
            for selector in (0,1,2):
                cpu.mem_write(MEM,b'\xa5'*0x300)
                cpu.reg_write(X.UC_ARM64_REG_SP,frame);cpu.reg_write(X.UC_ARM64_REG_X19,MEM)
                put(cpu,frame+0xc,selector)
                got=run.run(0xf6ac,inputs=((X.UC_ARM64_REG_X0,reset),))
                assert got['call']=='GPIO_strap_getter'
                assert bytes(cpu.mem_read(MEM+0x238,4))==bytes(4)
                got=run.run(0xf6b8,inputs=((X.UC_ARM64_REG_X0,strap),))
                expected=strap | ((1 if selector==2 else reset)<<2)
                assert got['call']=='logging' and cpu.mem_read(MEM+0x238,1)==bytes([expected])
                cases.append(dict(case='context-mode-bit-producer',synthetic_reset=reset,
                                  synthetic_GPIO_strap=strap,synthetic_selector=selector,
                                  flags=expected,native_getters_executed=False))
    return dict(cases=cases,generated_words=sorted(words))


def audit_strap(loader):
    if hashlib.sha256(loader).hexdigest()!=NOR_LOADER_SHA:
        raise ValueError('Unsupported original NOR loader')
    cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for at,size in ((0,0x20000),(MEM,0x10000),(STACK,0x10000),(STOP,4096)):
        cpu.mem_map(at,size)
    cpu.mem_write(0,loader)
    class Services:
        calls={0xde7c:'backup_read',0xb50c:'logging'}
    run=BoundaryRunner(cpu,(Services(),),stop=STOP,stack=STACK)
    cases=[]
    got=run.call(0xaba8,())
    assert got['call']=='backup_read' and got['args'][0]==0xf909d5
    cases.append(dict(case='strap-port-lookup',backup_ID='0xf909d5',read_executed=False))
    for status,port in ((-1,17),(0,-1),(0,17),(4,17)):
        run.call(0xaba8,());sp=cpu.reg_read(X.UC_ARM64_REG_SP);put(cpu,sp+0xc,port)
        got=run.run(0xabc8,inputs=((X.UC_ARM64_REG_X0,status),))
        stopped=status<0 or port==-1
        assert got['at']==(STOP if stopped else 0xde7c)
        if stopped:assert got['args'][0]==0
        else:assert got['args'][0]==0xf909d6
        cases.append(dict(case='post-port-lookup',status=status,port=port,
                          second_lookup_ID=None if stopped else '0xf909d6',hardware_executed=False))
    for status,bit in ((-1,4),(0,-1),(0,0),(0,4),(0,31),(4,4)):
        run.call(0xaba8,());sp=cpu.reg_read(X.UC_ARM64_REG_SP)
        put(cpu,sp+0xc,17);put(cpu,sp+8,bit)
        got=run.run(0xabe8,targets=(0xac14,),inputs=((X.UC_ARM64_REG_X0,status),))
        stopped=status<0 or bit==-1
        assert got['at']==(STOP if stopped else 0xac14)
        if stopped:assert got['args'][0]==0
        else:
            assert cpu.reg_read(X.UC_ARM64_REG_W9)==0xf102e008
            assert cpu.reg_read(X.UC_ARM64_REG_W8)==1<<bit
        cases.append(dict(case='post-bit-lookup',status=status,bit=bit,
                          hardware_store_reached=not stopped,hardware_store_executed=False))
    # Pure address formation after omitted mode writes, then pure selection
    # after the omitted load. No input register is read by this audit.
    for port,bit in ((0,0),(17,4),(18,31)):
        run.call(0xaba8,());sp=cpu.reg_read(X.UC_ARM64_REG_SP)
        put(cpu,sp+8,bit);put(cpu,sp+0xc,port)
        got=run.run(0xac38,targets=(0xac44,),inputs=((X.UC_ARM64_REG_W11,0xf101d008),))
        register=0xf101d010+(port<<12)
        assert got['at']==0xac44 and cpu.reg_read(X.UC_ARM64_REG_W4)==register
        cases.append(dict(case='strap-input-address',port=port,bit=bit,address=hex(register),load_executed=False))
        for sample in (0,1<<bit):
            got=run.run(0xac48,inputs=((X.UC_ARM64_REG_W3,bit),
                         (X.UC_ARM64_REG_W10,1),(X.UC_ARM64_REG_W8,sample)))
            assert got['call']=='logging' and cpu.reg_read(X.UC_ARM64_REG_W19)==int(bool(sample))
            cases.append(dict(case='post-input-strap-selection',port=port,bit=bit,
                              synthetic_sample=hex(sample),selected=int(bool(sample)),load_executed=False))
    return dict(cases=cases,port_ID='0xf909d5',bit_ID='0xf909d6',
                IDs_are_configuration_not_qualified_live_values=True)


def audit_cp(cp,words):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target CP')
    cpu=Uc(UC_ARCH_ARM,UC_MODE_ARM)
    for at,size in ((0x108000,0x2000),(0x03e42000,4096),(MEM,4096),(STACK,4096),(STOP,4096)):
        cpu.mem_map(at,size)
    cpu.mem_write(0x108000,cp[:0x2000]);seen=[];loads=0
    def trace(u,address,size,user):
        nonlocal loads
        if address==0x10897c:
            loads+=1
            if loads==2:seen.append('repeated-poll');u.emu_stop()
        if address==STOP:seen.append('returned');u.emu_stop()
    cpu.hook_add(UC_HOOK_CODE,trace);cases=[]
    for word in words:
        # Host copies the generated encoding to an INDEPENDENT CP fixture.
        # This does not connect either real address space or prove an alias.
        put(cpu,0x03e42000,word);loads=0;seen.clear()
        cpu.reg_write(A.UC_ARM_REG_LR,STOP)
        cpu.emu_start(0x108974,0xffffffff,count=100)
        waiting=bool(word&0xff00)
        assert seen==['repeated-poll' if waiting else 'returned']
        assert cpu.reg_read(A.UC_ARM_REG_PC)==(0x10897c if waiting else STOP)
        assert bytes(cpu.mem_read(0x03e42000,4))==struct.pack('<I',word)
        cases.append(dict(case='mode-second-byte-poll',word=hex(word),waiting=waiting,
                          boundary=seen[0],poll_byte_not_changed=True,physical_alias_verified=False))
        seen.clear();put(cpu,MEM,0x128000);cpu.reg_write(A.UC_ARM_REG_R0,MEM)
        cpu.reg_write(A.UC_ARM_REG_LR,STOP);cpu.emu_start(0x1089e4,0xffffffff,count=100)
        expected=0xd0220000 if word&255 else 0x128000
        assert seen==['returned'] and int.from_bytes(cpu.mem_read(MEM,4),'little')==expected
        assert bytes(cpu.mem_read(0x03e42000,4))==struct.pack('<I',word)
        cases.append(dict(case='mode-first-byte-text-source',word=hex(word),source=hex(expected),
                          source_payload_loaded_or_verified=False))
    return dict(cases=cases,poll_address='0x03e42001',text_source_mode_address='0x03e42000',
                RTOS_or_hardware_executed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loader',type=Path,required=True)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();loader=args.loader.read_bytes();cp=args.cp.read_bytes()
    writer=audit_loader(loader);strap=audit_strap(loader);consumer=audit_cp(cp,writer['generated_words'])
    report=dict(schema='OFFLINE_CP_EXEC_MODE_PRODUCER_CONSUMER/1',camera_io=False,
        loader_sha256=NOR_LOADER_SHA,CP_sha256=hashlib.sha256(cp).hexdigest(),
        writer=writer,strap=strap,consumer=consumer,
        limits=['Backup lookup results and GPIO samples are independent synthetic inputs',
                'No backup read, GPIO configuration/read, diagnostic or next boot stage executes',
                'Host encoding copy is not an AP/CP physical address-space connection',
                'No live board strap, source-image integrity, CP bootstrap/RTOS or readiness is established'])
    paths=[Path(__file__),Path(__file__).with_name('support')/'reference.py',
           Path(__file__).with_name('support')/'boundaries.py']
    report['sources']={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(report,stream,indent=2);stream.write('\n')
    count=sum(len(report[k]['cases']) for k in ('writer','strap','consumer'))
    print(f'{count} original EXEC_MODE/strap/consumer contracts; no physical CP boot established.')


if __name__=='__main__':
    main()
