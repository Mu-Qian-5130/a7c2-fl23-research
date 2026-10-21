"""Bind an exact factory BK4 image using original CP instructions, offline.

This establishes a staged input/layout contract, not live-body identity,
complete boot, peer readiness or a safe camera deployment candidate.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn import arm_const as R
from support.reference import SPECS
from support.backup import factory_segments

CP_BASE,FACTORY_BASE=0x108000,0x04000000
STACK,STOP=0x30000000,0x31000000


def audit(cp,factory):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    name,segments=factory_segments(factory,())
    first,second=segments
    aligned=(first['size']+4095)&~4095
    assert aligned==second['offset']==0xed000
    assert len(factory)==second['offset']+second['size']
    assert struct.unpack_from('<I',factory,0)[0]==FACTORY_BASE
    assert struct.unpack_from('<I',factory,second['offset'])[0]==FACTORY_BASE
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for page in (0x55d000,0x55e000,0xbe9000):
        u.mem_map(page,4096);u.mem_write(page,cp[page-CP_BASE:page-CP_BASE+4096])
    for page in (STACK,STOP,0x1a7e000):u.mem_map(page,4096)
    u.mem_map(FACTORY_BASE,(len(factory)+4095)&~4095);u.mem_write(FACTORY_BASE,factory)
    seen=[]
    def boundary(cpu,address,size,user):
        if address==STOP:seen.append(address);cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE,boundary)
    def run(entry,inputs):
        seen.clear();u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1)
        for reg,value in inputs:u.reg_write(reg,value)
        u.emu_start(entry|1,0xffffffff,count=500)
        assert seen==[STOP] and u.reg_read(R.UC_ARM_REG_PC)==STOP,'Missing original return'
        assert bytes(u.mem_read(FACTORY_BASE,len(factory)))==factory,'Factory source changed'
        return u.reg_read(R.UC_ARM_REG_R0)
    primary=run(0x55df9c,((R.UC_ARM_REG_R0,FACTORY_BASE),))
    assert primary==0
    assert struct.unpack('<I',u.mem_read(0x1a7e85c,4))[0]==FACTORY_BASE
    optional_size=run(0xbe9bd4,((R.UC_ARM_REG_R0,FACTORY_BASE),(R.UC_ARM_REG_R1,0)))
    assert optional_size==second['size']
    provider=run(0xbe9c64,((R.UC_ARM_REG_R0,FACTORY_BASE),))
    assert provider==FACTORY_BASE+aligned
    secondary=run(0x55e014,((R.UC_ARM_REG_R0,provider),))
    assert secondary==0
    pointers=struct.unpack('<6I',u.mem_read(0x1a7e85c,24))
    assert pointers[0]==FACTORY_BASE and pointers[3]==provider
    return dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),factory_name=name,
        factory_sha256=hashlib.sha256(factory).hexdigest(),factory_bytes=len(factory),
        declared_base=hex(FACTORY_BASE),primary_size=first['size'],secondary_offset=hex(aligned),
        secondary_size=second['size'],original_primary_result=primary,original_secondary_result=secondary,
        original_provider=hex(provider),pointers=[hex(v) for v in pointers],
        original_factory_bytes_preserved=True,
        limits=['The known factory image is not the current physical body backup',
                'The loader/data layout is staged, not a full original boot process',
                'No native peer, exposure, retained pixels, save/cancel or camera recovery is tested'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--factory',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();report=audit(args.cp.read_bytes(),args.factory.read_bytes())
    with args.output.open('x',encoding='utf-8') as f:json.dump(report,f,indent=2);f.write('\n')
    print('Exact factory headers/checksums and original primary/provider/secondary binding passed; no camera access')


if __name__=='__main__':main()
