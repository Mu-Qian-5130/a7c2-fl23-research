"""Exact original command dispatchers; no camera, generated call or hardware ACK.

Only paired, returned, readback-invariant original sequences become policy
words. Other source paths remain excluded rather than stubbed as successful.
"""
import hashlib
import struct
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_READ
from unicorn import arm_const as R
from .reference import SPECS

BASE,IO,STACK,STOP=0x108000,0xf5400000,0x30000000,0x31000000
CODE_RANGES=((0x52b000,0x5000),(0xb71000,0x1000))


def derive(cp):
    if hashlib.sha256(cp).hexdigest()!=SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
    for address,size in CODE_RANGES:
        u.mem_map(address,size);u.mem_write(address,cp[address-BASE:address-BASE+size])
    for address,size in ((IO,0x10000),(STACK,4096),(STOP,4096),(0x1a76000,4096)):u.mem_map(address,size)
    seen,writes,reads=[],[],[];alias=0
    def boundary(cpu,address,size,user):
        if address==STOP:seen.append(address);cpu.emu_stop()
    def write(cpu,access,address,size,value,user):
        if IO<=address<IO+0x10000:writes.append((address,size,value))
    def read(cpu,access,address,size,value,user):
        if IO<=address<IO+0x10000:
            cpu.mem_write(address,struct.pack('<I',alias));reads.append((address,size))
    u.hook_add(UC_HOOK_CODE,boundary);u.hook_add(UC_HOOK_MEM_WRITE,write);u.hook_add(UC_HOOK_MEM_READ,read)
    rows=[];policy={};paired=[]
    for selector in range(1,0x99):
        runs=[]
        for entry in (0x52b4f8,0x52cc9c):
          for word in (0,0xffffffff,0x55555555,0xaaaaaaaa):
            alias=word;seen.clear();writes.clear();reads.clear()
            u.reg_write(R.UC_ARM_REG_SP,STACK+0xf00);u.reg_write(R.UC_ARM_REG_LR,STOP|1);u.reg_write(R.UC_ARM_REG_R0,selector)
            try:
                u.emu_start(entry|1,0xffffffff,count=1000)
                runs.append(dict(entry=hex(entry),readback_input=word,returned=seen==[STOP],result=u.reg_read(R.UC_ARM_REG_R0),writes=list(writes),reads=list(reads)))
            except Exception as error:
                runs.append(dict(entry=hex(entry),readback_input=word,error=repr(error),boundary_PC=hex(u.reg_read(R.UC_ARM_REG_PC))))
        admitted=all(r.get('returned') and r.get('result')==0 for r in runs)
        setting,clearing={},{}
        if admitted:
            admitted=all(r['writes']==runs[0]['writes'] for r in runs[:4]) and all(r['writes']==runs[4]['writes'] for r in runs[4:])
            for index,table in ((0,setting),(4,clearing)):
                for address,size,value in runs[index]['writes']:
                    expected=4 if index==0 else 0
                    offset=address-IO-expected
                    if size!=4 or not 0<=offset<0x1000 or offset&15 or not value:
                        admitted=False;break
                    table[offset]=table.get(offset,0)|value
            admitted=admitted and bool(setting) and setting==clearing
        if admitted:
            paired.append(selector)
            for offset,mask in setting.items():policy[offset]=policy.get(offset,0)|mask
        rows.append(dict(selector=selector,paired_command_policy_admitted=admitted,runs=runs))
    code=b''.join(cp[a-BASE:a-BASE+n] for a,n in CODE_RANGES)
    return dict(camera_io=False,CP_sha256=hashlib.sha256(cp).hexdigest(),code_sha256=hashlib.sha256(code).hexdigest(),
        original_executions=sum(len(r['runs']) for r in rows),paired_selectors=paired,policy=sorted(policy.items()),rows=rows,
        physical_clock_or_reset_qualified=False,readback_scope='four explicit words per original dispatcher/selector')


def encode(report):
    records=report['policy']
    if not 0<len(records)<=256:raise ValueError('Unsupported sparse policy size')
    return (b'CPREQ73\0'+report['CP_sha256'].encode('ascii')+struct.pack('<I',len(records))+
        report['code_sha256'].encode('ascii')+b''.join(struct.pack('<II',offset,mask) for offset,mask in records))
