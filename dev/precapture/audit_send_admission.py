"""Original remote send can return zero without a registered transport.

Stop before logging or a registered callback. The post-log return is an
independent instruction slice; no successful native call is fabricated.
"""
import argparse,json,struct,hashlib
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn import arm64_const as R
from support.kernel import Module,UIPC_SHA
from support.boundaries import BoundaryRunner
from support.memory import MEM,STACK,STOP


def audit(raw):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);m=Module(u,raw,UIPC_SHA,0x10000000)
    for at,size in ((MEM,0x20000),(STACK,0x10000),(STOP,4096)):
        u.mem_map(at,size)
    A=lambda n:m.at('.text',n)
    root=struct.unpack('<Q',bytes(u.mem_read(A(0x3e08),8)))[0]
    packet,transport=MEM+0x8000,MEM+0x1000
    callback=MEM+0x18000
    class Extra: calls={callback:'registered_transport_callback'}
    run=BoundaryRunner(u,(m,Extra()),stop=STOP,stack=STACK)
    q=lambda address,value:u.mem_write(address,struct.pack('<Q',value))
    before=bytes((i*13+7)&255 for i in range(128));cases=[]
    for name,pointer,function in (('no-transport-object',0,0),
        ('transport-object-without-function',transport,0),
        ('registered-callback-stop',transport,callback)):
        q(root+0x458,pointer);q(transport,function);u.mem_write(packet-64,before)
        got=run.call(A(0x3bf8),(0x90030001,packet))
        assert bytes(u.mem_read(packet-64,128))==before
        if function:
            assert got['at']==callback and got['args'][:2]==[0x90030001,packet]
            cases.append(dict(case=name,callback_reached_but_not_executed=True,
                              callback_result_unmodeled=True,packet_bytes_unchanged=True))
        else:
            assert got['at']==A(0x3df4) and 'printk' in got['call']
            # Start after logging. Original MOV overwrites x0 before return,
            # so no logger result/return stub is needed or supplied.
            returned=run.run(A(0x3df8))
            assert returned['at']==STOP and returned['args'][0]==0
            assert bytes(u.mem_read(packet-64,128))==before
            cases.append(dict(case=name,native_log_executed=False,
                zero_return_after_omitted_log=True,transport_callback_executed=False,
                packet_bytes_unchanged=True))
    return dict(cases=cases,remote_route='0x90030001',
        findings=['A zero native send status is compatible with missing remote transport',
            'That return alone proves neither CP receipt nor outgoing-reference cleanup',
            'A local loopback receive does not qualify the remote CP transport'],
        limits=['All queue/transport/packet objects are independent synthetic inputs',
            'No logging, registered transport, send completion or native free executes',
            'This identifies an original source contract, not current hardware transport state'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--uipc-kernel',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();raw=a.uipc_kernel.read_bytes()
    sources=[Path(__file__),Path(__file__).with_name('support')/'kernel.py',Path(__file__).with_name('support')/'boundaries.py']
    report=dict(schema='OFFLINE_ORIGINAL_REMOTE_SEND_ADMISSION/1',camera_io=False,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        sources={str(s.relative_to(Path(__file__).parent)):hashlib.sha256(s.read_bytes()).hexdigest() for s in sources},
        **audit(raw))
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('Three original send-admission branches checked; native zero-return does not prove CP transport.')


if __name__=='__main__':main()
