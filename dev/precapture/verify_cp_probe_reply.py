"""Original CP callback and current-look comparisons; emulator RAM ONLY.

No IPC delivery, boot, ROM/RAM installation or native service succeeds by
mocking. Original cache/backup helpers are stop boundaries. Private status5a
is NOT the status1/address-length result accepted by the old DMA log client.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import UC_HOOK_CODE
from unicorn import arm_const as reg
from cp_probe_reply import build, BASE, ENTRY, LEGACY, NONCE, FINAL, MODE, STATUS
from audit_dormant_diagnostic import emulator, look_cases, preview_cases
from audit_bootstrap_memory import audit as bootstrap_audit
from verify_extension_layout import layout

MEM, STACK, STOP = 0x30000000, 0x40000000, 0x20000000
REQUEST, BLOG = MEM+0x1000, MEM+0x9000
ROOT = 0x1a7e988
CALLBACK = BASE+0x45e6d8
BOUNDARIES = {BASE+0x4fe52c, BASE+0x45fcd8, BASE+0x4fdd70}
PRESERVED = tuple(getattr(reg,f'UC_ARM_REG_R{i}') for i in range(4,12))


class Runner:
    def __init__(self,cp,patches=()):
        self.u=u=emulator(cp,patches)
        u.mem_map(ROOT&~4095,4096)
        self.seen,self.status_at_leaf=[],[]
        def trace(cpu,at,size,_):
            self.seen.append(at)
            if at==ENTRY+4:self.status_at_leaf.append(cpu.reg_read(reg.UC_ARM_REG_CPSR)&~0x20)
            if at in BOUNDARIES or at==STOP:cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE,trace)
    def run(self,mode,nonce=0xa17e1234,opaque=0x76543210,cpu_mode=0x13,root=True):
        u=self.u
        u.reg_write(reg.UC_ARM_REG_CPSR,0xa8000020|cpu_mode)
        for r,value in zip(PRESERVED,range(0x10101010,0x10101018)):u.reg_write(r,value)
        packet=bytearray(b'\xa5'*24);packet[0]=mode;packet[1]=0
        struct.pack_into('<I',packet,20,nonce)
        u.mem_write(REQUEST,bytes(packet));u.mem_write(ROOT,struct.pack('<I',BLOG if root else 0))
        u.mem_write(BLOG,bytes(64));u.mem_write(BLOG+56,struct.pack('<I',0x1000))
        u.reg_write(reg.UC_ARM_REG_R0,REQUEST)
        u.reg_write(reg.UC_ARM_REG_R1,0xabcdef01)
        u.reg_write(reg.UC_ARM_REG_R2,opaque)
        u.reg_write(reg.UC_ARM_REG_R3,0xfedcba98)
        u.reg_write(reg.UC_ARM_REG_SP,STACK+0x8000)
        u.reg_write(reg.UC_ARM_REG_LR,STOP|1)
        self.seen.clear();self.status_at_leaf.clear()
        u.emu_start(CALLBACK|1,0xffffffff,count=3000)
        pc=u.reg_read(reg.UC_ARM_REG_PC)
        assert pc in BOUNDARIES|{STOP}
        return dict(pc=pc,packet=bytes(u.mem_read(REQUEST,24)),
            r0=u.reg_read(reg.UC_ARM_REG_R0),
            args=[u.reg_read(r) for r in (reg.UC_ARM_REG_R0,reg.UC_ARM_REG_R1,reg.UC_ARM_REG_R2,reg.UC_ARM_REG_R3)],
            preserved=[u.reg_read(r) for r in PRESERVED],sp=u.reg_read(reg.UC_ARM_REG_SP),
            reached_helper=any(ENTRY<=p<ENTRY+12 for p in self.seen),leaf_status=list(self.status_at_leaf))


def callback_cases(cp,patches):
    before,after=Runner(cp),Runner(cp,patches)
    rows=[]
    for mode in range(256):
        a,b=before.run(mode),after.run(mode)
        if mode==MODE:
            assert a['pc']==STOP and a['packet'][1]==0x80
            assert b['pc']==STOP and b['packet'][1]==STATUS and b['reached_helper']
            echo,opaque,status=struct.unpack_from('<3I',b['packet'],8)
            assert (echo,opaque)==(0xa17e1234,0x76543210)
            assert b['leaf_status']==[status]
        else:
            assert (a['pc'],a['packet'],a['r0'],a['preserved'],a['sp'])==(b['pc'],b['packet'],b['r0'],b['preserved'],b['sp'])
            if mode in (1,2,3,4):
                assert not b['reached_helper'] and a['args']==b['args']
            else:
                assert b['pc']==STOP and b['packet'][1]==0x80
        if b['pc']==STOP:assert b['sp']==STACK+0x8000 and b['preserved']==list(range(0x10101010,0x10101018))
        rows.append(dict(mode=mode,private=mode==MODE,native_boundary=hex(b['pc']),
            ordinary_packet_and_callee_saved_unchanged=mode!=MODE,real_service_executed=False))
    private=[]
    for cpu_mode,nonce,opaque,root in itertools.product((0x10,0x13,0x1f),
            (1,0xa17e1234,0xffffffff),(0,0x12345678),(False,True)):
        got=after.run(MODE,nonce,opaque,cpu_mode,root)
        assert got['pc']==STOP and got['packet'][1]==STATUS
        echo,scratch,status=struct.unpack_from('<3I',got['packet'],8)
        assert echo==nonce and scratch==opaque and status==got['leaf_status'][0]
        assert status&31==cpu_mode
        assert got['sp']==STACK+0x8000
        assert got['preserved']==list(range(0x10101010,0x10101018))
        assert got['packet'][0]==MODE and got['packet'][2:8]==b'\xa5'*6
        assert struct.unpack_from('<I',got['packet'],20)[0]==nonce
        private.append(dict(cpu_mode=hex(cpu_mode),nonce=hex(nonce),logger_root_present=root,
            nonce_echo_matches=True,ignored_scratch_matches=True,CPSR_mode_matches=True,
            no_logger_or_native_service_access=True))
    return rows,private


def mapping_cases(cp,patches):
    samples={}
    for i,(at,raw) in enumerate(patches):
        samples[f'private-rpc-{i}-first']=at;samples[f'private-rpc-{i}-last']=at+len(raw)-1
    native=layout(cp);rows=[]
    for alternate in (0,1):
        got=bootstrap_audit(cp,alternate,False,extra_samples=samples)
        for label,at in samples.items():
            mapping=got['samples'][label]
            physical=at+(0xd0220000-native['text']['virtual'] if alternate else 0)
            assert mapping['physical']==physical and not mapping['xn']
        rows.append(dict(synthetic_alternate_text_source=alternate,endpoints=len(samples),
            already_declared_text=True,native_mapper_activated=False,actual_source_or_boot_verified=False))
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();cp=a.cp.read_bytes();target,patches,review=build(cp)
    callbacks,private=callback_cases(cp,patches)
    looks=look_cases(cp,patches);previews=preview_cases(cp,patches);mappings=mapping_cases(cp,patches)
    report=dict(schema='OFFLINE_CP_PRIVATE_RPC_OBSERVER_VERIFIED/1',camera_io=False,
        source_sha256=review['source_sha256'],target_sha256=hashlib.sha256(target).hexdigest(),
        callback_modes=callbacks,private_reply_cases=private,look_helper_comparisons=looks,
        preview_and_ordinary_handler_comparisons=previews,mapping_cases=mappings,
        touched_envelope_bytes=32,inverse_exact=review['inverse_exact'],
        limits=['All callback/global/message/CPU-state inputs are synthetic; no IPC delivery or live source verified',
            'Native cache and backup APIs stop before execution; no successful service mock is supplied',
            'Unsupported legacy condition flags may differ as permitted by the call ABI; outputs/callee-saved/SP match',
            'Response word12 is opaque caller scratch, not a defined identity or address',
            'Request nonce20 remains in the reply tail and is copied to8; a future stock baseline must verify full24-byte roundtrip',
            'Header/table equality and a mapped interval do not prove boot or executable storage ownership generally',
            'No bounded RPC client, native flash/reload/recovery workflow or camera approval is provided',
            'This is not installed or working pre-capture'])
    with a.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print(f'Private RPC observer:256 original modes /{len(private)} private replies /{len(looks)} helper /{len(previews)} preview-handler comparisons /2 native mapping paths. No camera operation.')
if __name__=='__main__':main()
