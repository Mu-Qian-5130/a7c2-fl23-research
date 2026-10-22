"""Original register-helper slices with explicit read words, no device ACK.

This fixture contains ROM, a synthetic stack and explicitly listed IO words.
Calls to native services stop before execution. A post-service entry is an
independent slice with supplied state, never a fabricated successful return.
"""
import hashlib
from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE,
                     UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_EXEC)
from unicorn import arm_const as R
from .reference import CP_LOAD_BASE

STACK, STOP = 0x30000000, 0x31000000


class RegisterSource:
    def __init__(self, image, source_sha256, words, scratch=()):
        if hashlib.sha256(image).hexdigest() != source_sha256:
            raise ValueError('Unsupported original register-helper source')
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        extent=(len(image)+4095)&~4095
        u.mem_map(CP_LOAD_BASE,extent);u.mem_write(CP_LOAD_BASE,image)
        u.mem_protect(CP_LOAD_BASE,extent,UC_PROT_READ|UC_PROT_EXEC)
        self.words=frozenset(words);self.scratch=frozenset(scratch)
        self.io_pages={a&~4095 for a in words}
        pages=self.io_pages|{a&~4095 for a in scratch}|{STACK,STOP}
        for address in sorted(pages):u.mem_map(address,4096)
        self.reads=[];self.writes=[];self.io_events=[];self.seen=[];self.plan=[];self.stops=set()
        def code(cpu,address,size,user):
            if address in self.stops:
                self.seen.append(address);cpu.emu_stop()
        def read(cpu,access,address,size,value,user):
            if address&~4095 in self.io_pages:
                assert address in self.words and size==4 and self.plan,'Unspecified IO read'
                expected,word=self.plan.pop(0)
                assert expected==address,'Different original IO read order'
                cpu.mem_write(address,word.to_bytes(4,'little'))
                self.reads.append((address,size,word))
                self.io_events.append(('read',address,size,word))
        def write(cpu,access,address,size,value,user):
            if address&~4095 in self.io_pages or address in self.scratch:
                assert size==4 and address in self.words|self.scratch,'Unspecified IO/scratch write'
                self.writes.append((address,size,value))
                self.io_events.append(('write',address,size,value))
            else:
                assert STACK<=address and address+size<=STACK+4096,'Unexpected original store'
        u.hook_add(UC_HOOK_CODE,code)
        u.hook_add(UC_HOOK_MEM_READ,read)
        u.hook_add(UC_HOOK_MEM_WRITE,write)

    def run(self, entry, stop, registers=(), read_words=(), *, count=100):
        self.stops={stop};self.seen.clear();self.reads.clear();self.writes.clear();self.io_events.clear()
        self.plan=list(read_words)
        for register,value in registers:self.u.reg_write(register,value)
        self.u.emu_start(entry|1,0xffffffff,count=count)
        assert self.seen==[stop] and self.u.reg_read(R.UC_ARM_REG_PC)==stop,'Missing original boundary'
        assert not self.plan,'Expected IO read did not execute'
