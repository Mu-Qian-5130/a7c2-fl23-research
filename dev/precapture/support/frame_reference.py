"""Pinned original frame-reference instructions; no successful OS stubs.

Only explicit synthetic object/count inputs and separate post-lock slices
are supported. This does not acquire a real frame, hold a real mutex or
qualify an installed image. All native services stop before execution.
"""
import hashlib
import struct

from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,
    UC_ARM_REG_R3,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_R6,
    UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC)
from .reference import SPECS

BASE,FRAME,HOLDER,STACK,STOP = 0x108000,0x30004000,0x30000100,0x40000000,0x20000000
VTABLE,DEBUG,POOL,CALLBACK = 0xe75694,0x1a533a4,0x1a31f40,0x22000000
ADDREF,DROPREF = 0x36bd50,0x36bdf4
QUERY,LOCK,LOCK_ALT,UNLOCK,UNLOCK_ALT = 0x4ea67c,0x4e65a0,0x4e6450,0x4e6988,0x4e68a8


def words(*values):return struct.pack('<'+'I'*len(values),*values)


class FrameReferenceOracle:
    def __init__(self,raw):
        if hashlib.sha256(raw).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
            raise ValueError('Unsupported complete target CP for frame-reference audit')
        self.raw=raw;self.u=u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        u.mem_map(BASE,(len(raw)+4095)&~4095);u.mem_write(BASE,raw)
        for at,size in ((0x30000000,0x10000),(STACK,0x10000),(STOP,4096),
                        (DEBUG&~4095,4096),(POOL&~4095,4096),(CALLBACK,4096)):
            u.mem_map(at,size)
        self.stops=set();self.seen=[]
        self.external={BASE+x for x in (QUERY,LOCK,LOCK_ALT,UNLOCK,UNLOCK_ALT,
            0xa3c57a,0xa07356,0xa13a60)}|{CALLBACK}
        def trace(cpu,at,size,user):
            if at in self.stops or at in self.external:
                self.seen.append(dict(at=at,args=[cpu.reg_read(r) for r in
                    (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)],executed=False))
                cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE,trace)
        self.vtable=struct.unpack_from('<4I',raw,VTABLE-BASE)
        if self.vtable[2:]!=(BASE+ADDREF+1,BASE+DROPREF+1):
            raise ValueError('Original frame vtable does not match reference methods')

    def reset(self,count,callback=False):
        frame=bytearray([0xa5])*0x6800
        frame[:0x18]=words(VTABLE,count,CALLBACK|1 if callback else 0,0,int(callback),0)
        self.u.mem_write(FRAME,bytes(frame));self.u.mem_write(HOLDER,words(FRAME)+bytes(64))
        self.u.mem_write(DEBUG,bytes(0x100))
        self.u.reg_write(UC_ARM_REG_SP,STACK+0x8000)
        self.u.reg_write(UC_ARM_REG_LR,STOP|1)
        return bytes(frame)

    def run(self,start,stops,inputs=(),*,count=2000):
        self.stops=set(stops)|{STOP};self.seen.clear()
        for reg,value in inputs:self.u.reg_write(reg,value)
        self.u.emu_start(BASE+start|1,0xffffffff,count=count)
        assert len(self.seen)==1 and self.u.reg_read(UC_ARM_REG_PC)==self.seen[0]['at'], 'Original slice did not reach a declared boundary'
        assert self.seen[0]['at'] in self.stops,'Unexpected native service boundary'
        return self.seen[0]

    def frame(self):return bytes(self.u.mem_read(FRAME,0x6800))

    def count(self):return struct.unpack('<I',self.u.mem_read(FRAME+4,4))[0]
