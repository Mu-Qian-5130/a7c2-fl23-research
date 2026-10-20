"""Original PCIe/UIPC registration contracts, not a CP-ready test.

Native registration stores run on synthetic module state. Thread, IRQ, GPIO,
wait, logging and transport services remain stop boundaries.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from support.kernel import Module,UIPC_SHA,PCIE_SHA
from support.boundaries import BoundaryRunner
from support.memory import MEM,STACK,STOP


def audit(kernel,pcie):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    k=Module(u,kernel,UIPC_SHA,0x10000000);p=Module(u,pcie,PCIE_SHA,0x18000000)
    for at,size in ((MEM,0x20000),(STACK,0x10000),(STOP,4096)):u.mem_map(at,size)
    run=BoundaryRunner(u,(k,p),stop=STOP,stack=STACK)
    K=lambda at:k.at('.text',at)
    P=lambda at:p.at('.text',at)
    q=lambda at,value:u.mem_write(at,struct.pack('<Q',value))
    get=lambda at:struct.unpack('<Q',bytes(u.mem_read(at,8)))[0]
    root=get(K(0x3bd8));slot=root+0x458
    table=p.at('.data',0xb8)
    assert get(P(0x3ca8))==table
    assert (get(table),get(table+8))==(P(0x3c70),P(0x3c58))
    cases=[]
    got=run.call(P(0x3c88),())
    assert got['call']=='osal_reg_public' and got['args'][0]==table
    cases.append(dict(case='pcie-wrapper-table-argument',native_registration_executed=False))
    # Separate post-registration return: source overwrites x0, not a mock ACK.
    returned=run.run(P(0x3c98))
    assert returned['at']==STOP and returned['args'][0]==0
    cases.append(dict(case='pcie-wrapper-zero-after-omitted-registration',
                      registration_result_not_proven=True))
    for name,existing,requested,expected in (
        ('null-input',0,0,-1024),('empty-slot',0,table,0),
        ('occupied-slot',MEM+0x1000,table,-1018)):
        q(slot,existing);before=bytes(u.mem_read(root,0x460))
        got=run.call(K(0x3ba8),(requested,))
        status=got['args'][0]&0xffffffff
        assert got['at']==STOP and status==expected&0xffffffff
        after=bytearray(before)
        if expected==0:struct.pack_into('<Q',after,0x458,requested)
        assert bytes(u.mem_read(root,0x460))==bytes(after)
        cases.append(dict(case='uipc-registration-'+name,return_value=expected,
                          callback_slot_changed=expected==0))
    # It accepts any nonzero table pointer without validating its function0.
    q(slot,0);q(MEM+0x1000,0)
    got=run.call(K(0x3ba8),(MEM+0x1000,))
    assert got['args'][0]==0 and get(slot)==MEM+0x1000
    cases.append(dict(case='uipc-accepts-table-with-null-function',
                      registration_zero_is_not_send_readiness=True))
    before=bytes(u.mem_read(root,0x460))
    got=run.call(K(0x3be0),())
    expected=bytearray(before);struct.pack_into('<Q',expected,0x458,0)
    assert got['args'][0]==0 and bytes(u.mem_read(root,0x460))==bytes(expected)
    cases.append(dict(case='unregister-clears-only-slot',drain_or_peer_termination_executed=False))
    for entry,mode in ((0x3c70,0),(0x3c58,1)):
        got=run.call(P(entry),(0x90030001,MEM+0x2000),targets=(P(0x34c0),))
        assert got['at']==P(0x34c0) and got['args'][:3]==[0x90030001,MEM+0x2000,mode]
        cases.append(dict(case='registered-send-wrapper',mode=mode,
                          packet_sender_executed=False))
    sender=get(P(0x2db8));flag=sender+0x250
    for initial in (0,1):
        u.mem_write(flag,struct.pack('<I',initial))
        got=run.call(P(0x2d70),())
        if initial==0:
            assert got['call']=='pcieif_wait_done'
            assert struct.unpack('<I',u.mem_read(flag,4))[0]==1
        else:assert got['at']==STOP
        cases.append(dict(case='init-done-signal',before=initial,
                          wait_or_hardware_executed=False,
                          signal_set_before_first_wait=initial==0))
    return dict(cases=cases,UIPC_callback_slot_section='.bss',UIPC_callback_slot_offset='0x3018',
        PCIe_table_section='.data',PCIe_table_offset='0xb8',
        PCIe_async_wrapper_file='0x3c70',PCIe_sync_wrapper_file='0x3c58',
        PCIe_sender_flag_section='.bss',PCIe_sender_flag_offset=hex(flag-p.at('.bss',0)),
        findings=['PCIe wrapper discards the registration return and always returns0',
            'UIPC rejects an occupied slot but accepts any nonzero table without checking function0',
            'The native sender flag is set before wait notifications, not proof of CP firmware execution',
            'Unregister clears the pointer without draining peer work'],
        limits=['All original module storage is synthetic; this is not a current live readiness sample',
            'No native thread, IRQ/GPIO, wait, log, packet send or CP execution is performed',
            'Table/flag presence cannot establish working PCIe DMA or a matching CP reply'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uipc-kernel',type=Path,required=True)
    parser.add_argument('--pcie',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args();kernel=a.uipc_kernel.read_bytes();pcie=a.pcie.read_bytes()
    sources=[Path(__file__),Path(__file__).with_name('support')/'kernel.py',Path(__file__).with_name('support')/'boundaries.py']
    report=dict(schema='OFFLINE_ORIGINAL_TRANSPORT_REGISTRATION/1',camera_io=False,
        UIPC_sha256=hashlib.sha256(kernel).hexdigest(),PCIe_sha256=hashlib.sha256(pcie).hexdigest(),
        sources={str(s.relative_to(Path(__file__).parent)):hashlib.sha256(s.read_bytes()).hexdigest() for s in sources},
        **audit(kernel,pcie))
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original registration/signal contracts; no CP readiness established.")


if __name__=='__main__':main()
