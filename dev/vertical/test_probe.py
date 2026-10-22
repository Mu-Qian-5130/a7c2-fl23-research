from pathlib import Path
import sys,struct,json
ROOT=Path(__file__).resolve().parents[2]
ASSETS=ROOT/'src/vertical/assets'
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_INTR
from unicorn.arm64_const import *
BASE=0x7f00000000;HEADER='<8sIIqQII24s'
expected=bytes.fromhex('20af0290006013910088409100803791c0035fd620af0290006013910088409100a03791c0035fd6')
def run(value=1,model=16,wrong_code=False,short_read=False,missing_maps=False):
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x10000000,0x400000)
 with (ASSETS/'vertical_probe.so').open('rb') as f:
  e=ELFFile(f)
  for s in e.iter_segments():
   if s['p_type']=='PT_LOAD':u.mem_write(0x10000000+s['p_vaddr'],s.data())
  init=next(t.entry.d_val for t in e.get_section_by_name('.dynamic').iter_tags() if t.entry.d_tag=='DT_INIT')
 u.mem_map(0x60000000,0x100000);u.mem_map(0x70000000,0x1000);u.reg_write(UC_ARM64_REG_SP,0x600f0000);u.reg_write(UC_ARM64_REG_X30,0x70000000);u.reg_write(UC_ARM64_REG_CPACR_EL1,0x300000)
 files={'/proc/self/maps':bytearray() if missing_maps else bytearray((f'{BASE:x}-{BASE+0x51a7000:x} r-xp 00000000 00:01 12 /usr/lib/appFw.so\n'+f'{BASE+0x51b7000:x}-{BASE+0x9900000:x} rw-p 051a7000 00:01 12 /usr/lib/appFw.so\n').encode()),'/proc/mounts':bytearray(b'/dev/root / ext4 ro 0 0\n'),'/proc/self/cmdline':bytearray(b'/usr/bin/app\0'),'/tmp/jiritsu/libJit.so':bytearray(b'own')};handles={};writes=[]
 def string(p):
  b=bytearray()
  while True:
   c=bytes(u.mem_read(p+len(b),1))
   if c==b'\0':return b.decode()
   b+=c
 def syscall(cpu,no,_):
  n=cpu.reg_read(UC_ARM64_REG_X8);a=[cpu.reg_read(x) for x in [UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3]];r=0
  if n in (172,175):r=47 if n==172 else 0
  elif n==56:
   path=string(a[1]);flags=a[2]
   if flags:
    assert path in ['/tmp/jiritsu/a7c2.probe.result','/tmp/jiritsu/a7c2.runtime.result'] and flags==0x241
    files[path]=bytearray();writes.append(path)
   else:assert path in files or path=='/proc/self/mem'
   r=10+len(handles);handles[r]=[path,0]
  elif n==35:assert string(a[1])=='/tmp/jiritsu/libJit.so';del files[string(a[1])]
  elif n==63:
   h=handles[a[0]];data=bytes(files[h[0]][h[1]:h[1]+a[2]]);h[1]+=len(data);cpu.mem_write(a[1],data);r=len(data)
  elif n==67:
   assert handles[a[0]][0]=='/proc/self/mem'
   at=a[3]-BASE
   if at==0x5bc35b0:data=struct.pack('<I',model)
   elif at==0x286caa0:data=bytes(40) if wrong_code else expected;data=data[:20] if short_read else data
   elif at==0x7e732b8:data=struct.pack('<I',value)
   elif at==0x7e732c0:data=bytes(24)
   else:raise AssertionError(hex(at))
   assert len(data)<=a[2];cpu.mem_write(a[1],data);r=len(data)
  elif n==64:
   h=handles[a[0]];assert h[0] in writes;files[h[0]].extend(cpu.mem_read(a[1],a[2]));r=a[2]
  elif n in (57,82):pass
  else:raise AssertionError('Unexpected syscall '+str(n))
  cpu.reg_write(UC_ARM64_REG_X0,r&((1<<64)-1))
 u.hook_add(UC_HOOK_INTR,syscall);u.emu_start(0x10000000+init,0x70000000,count=5000000);assert u.reg_read(UC_ARM64_REG_PC)==0x70000000
 result=struct.unpack(HEADER,files['/tmp/jiritsu/a7c2.runtime.result']);assert result[:3]==(b'A7VUI001',1,model if not missing_maps else 0xffffffff)
 status=-2 if missing_maps else -22 if model!=16 else -84 if wrong_code else -5 if short_read else -22 if value>1 else 0
 assert result[3]==status
 return {'input':dict(value=value,model=model,wrong_code=wrong_code,short_read=short_read,missing_maps=missing_maps),'status':status,'only_temporary_result_writes':True}
cases=[{},dict(value=0),dict(value=2),dict(model=15),dict(wrong_code=True),dict(short_read=True),dict(missing_maps=True)]

import unittest
class NativeCases(unittest.TestCase):
 def test_native_cases(self):
  for case in cases:
   with self.subTest(case=case):run(**case)

if __name__=='__main__':unittest.main()
