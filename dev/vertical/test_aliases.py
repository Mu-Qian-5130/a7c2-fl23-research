from pathlib import Path
import sys,struct,json
ROOT=Path(__file__).resolve().parents[2]
ASSETS=ROOT/'src/vertical/assets'
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_INTR
from unicorn.arm64_const import *
BASE=0x7f00000000;FMT='<8sIIIIqqqIIII3II3Q'
SRC=[f'/usr/share/app/image_{i:02d}_32_IPSX.uxc' for i in range(3)]
DST=[f'/usr/share/app/image_{i:02d}_23_IPSX.uxc' for i in range(3)]
TARGET=[Path(s).name for s in SRC]
def run(mode=1,existing='none',fail_create=-1,fail_unlink=-1,fail_sync=False,fail_rw=False,fail_ro=False,alias_inode_wrong=False,wrong_header=False,model=16):
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x10000000,0x400000)
 with (ASSETS/'aliases.so').open('rb') as f:
  e=ELFFile(f)
  for s in e.iter_segments():
   if s['p_type']=='PT_LOAD':u.mem_write(0x10000000+s['p_vaddr'],s.data())
  reloc=e.get_section_by_name('.rela.dyn')
  if reloc:
   for r in reloc.iter_relocations():
    assert r['r_info_type']==1027
    u.mem_write(0x10000000+r['r_offset'],struct.pack('<Q',0x10000000+r['r_addend']))
  init=next(t.entry.d_val for t in e.get_section_by_name('.dynamic').iter_tags() if t.entry.d_tag=='DT_INIT')
 u.mem_map(0x60000000,0x100000);u.mem_map(0x70000000,0x1000);u.reg_write(UC_ARM64_REG_SP,0x600f0000);u.reg_write(UC_ARM64_REG_X30,0x70000000);u.reg_write(UC_ARM64_REG_CPACR_EL1,0x300000)
 maps=(f'{BASE:x}-{BASE+0x51a7000:x} r-xp 00000000 00:01 12 /usr/lib/appFw.so\n'+f'{BASE+0x51b7000:x}-{BASE+0x9900000:x} rw-p 051a7000 00:01 12 /usr/lib/appFw.so\n').encode()
 files={'/proc/self/maps':maps,'/proc/self/cmdline':b'/usr/bin/app\0','/tmp/jiritsu/libJit.so':b'own','/tmp/jiritsu/a7c2.names.request':struct.pack('<8sII',b'A7VRS001',mode,0)}
 for i,n in enumerate([7844,7880,3709]):files[SRC[i]]=struct.pack('<8sHHI',b'uxd\x07\0\0\0\0' if not wrong_header else b'invalid!',8,i,n|(((n+1)&~1)<<12))
 links={} if existing=='none' else {p:TARGET[i] if existing=='own' else 'foreign.uxc' for i,p in enumerate(DST)}
 if existing=='regular':links={};files[DST[0]]=b'foreign-data'
 initial_links=dict(links);initial_sources={p:files[p] for p in SRC};handles={};audit=[];state={'ro':True,'sync_failed':False}
 def text(p):
  b=bytearray()
  while True:
   c=bytes(u.mem_read(p+len(b),1))
   if c==b'\0':return b.decode()
   b+=c
 def stat(path,alias=False):
  i=SRC.index(path);ino=100+i+(999 if alias and alias_inode_wrong else 0)
  return struct.pack('<QQIIIIQQqIIQ7Q',99,ino,0o100644,1,0,0,0,0,1000000+i,4096,0,2048,*([0]*7))
 def syscall(cpu,num,user):
  no=cpu.reg_read(UC_ARM64_REG_X8);a=[cpu.reg_read(x) for x in [UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_X4]];r=0
  if no in (172,175):r=47 if no==172 else 0
  elif no==56:
   path=text(a[1]);flags=a[2];canonical=path;alias=False
   audit.append(('open',path,flags))
   if flags==0x241:
    assert path in ['/tmp/jiritsu/a7c2.probe.result','/tmp/jiritsu/a7c2.names.result'];files[path]=bytearray()
   elif path in SRC:assert flags==0x20000
   elif path in DST:
    assert flags==0;alias=True
    if path in links:canonical='/usr/share/app/'+links[path]
    elif path not in files:r=-2
   elif path=='/usr/share/app':assert flags==0x10000
   else:assert flags==0 and path in ['/proc/self/mem','/proc/self/maps','/proc/mounts','/proc/self/cmdline','/tmp/jiritsu/a7c2.names.request']
   if not r:r=10+len(handles);handles[r]=[path,canonical,0,alias]
  elif no==35:
   path=text(a[1]);audit.append(('unlink',path))
   if path=='/tmp/jiritsu/libJit.so':del files[path]
   else:
    assert path in DST and not state['ro']
    if DST.index(path)==fail_unlink:r=-5
    elif path in links:del links[path]
    else:r=-2
  elif no==36:
   target=text(a[0]);path=text(a[2]);assert path in DST and target==TARGET[DST.index(path)] and not state['ro'];audit.append(('symlink',path,target))
   if DST.index(path)==fail_create:r=-28
   elif path in links or path in files:r=-17
   else:links[path]=target
  elif no==78:
   path=text(a[1]);assert path in DST
   if path in links:data=links[path].encode();cpu.mem_write(a[2],data);r=len(data)
   else:r=-22 if path in files else -2
  elif no==40:
   assert a[0]==0 and text(a[1])=='/usr' and a[2]==0 and a[3] in (0xc30,0xc31);ro=bool(a[3]&1);audit.append(('mount',ro))
   if (ro and fail_ro) or (not ro and fail_rw):r=-5
   else:state['ro']=ro
  elif no==63:
   h=handles[a[0]]
   content=('/dev/nflasha15 /usr ext2 '+('ro' if state['ro'] else 'rw')+',nosuid,nodev,noatime 0 0\n').encode() if h[1]=='/proc/mounts' else files[h[1]]
   data=bytes(content[h[2]:h[2]+a[2]]);cpu.mem_write(a[1],data);h[2]+=len(data);r=len(data)
  elif no==67:
   h=handles[a[0]]
   if h[1]=='/proc/self/mem':assert a[3]==BASE+0x5bc35b0 and a[2]==4;data=struct.pack('<I',model)
   else:data=bytes(files[h[1]][a[3]:a[3]+a[2]])
   cpu.mem_write(a[1],data);r=len(data)
  elif no==80:
   h=handles[a[0]];assert h[1] in SRC;cpu.mem_write(a[1],stat(h[1],h[3]))
  elif no==64:
   h=handles[a[0]];assert h[0] in ['/tmp/jiritsu/a7c2.probe.result','/tmp/jiritsu/a7c2.names.result'];files[h[0]].extend(cpu.mem_read(a[1],a[2]));r=a[2]
  elif no==82:
   h=handles[a[0]]
   if h[0]=='/usr/share/app' and fail_sync and not state['sync_failed']:state['sync_failed']=True;r=-5
   else:assert h[0] in ['/usr/share/app','/tmp/jiritsu/a7c2.probe.result','/tmp/jiritsu/a7c2.names.result']
  elif no==57:pass
  else:raise AssertionError('Unexpected syscall '+str(no))
  cpu.reg_write(UC_ARM64_REG_X0,r&((1<<64)-1))
 u.hook_add(UC_HOOK_INTR,syscall);u.emu_start(0x10000000+init,0x70000000,count=5000000);assert u.reg_read(UC_ARM64_REG_PC)==0x70000000
 result=struct.unpack(FMT,files['/tmp/jiritsu/a7c2.names.result']);assert result[0]==b'A7VRS001' and result[1]==1 and result[4]==3
 status=result[5];assert all(files[p]==v for p,v in initial_sources.items())
 if model!=16:assert status==-22 and not any(a[0] in ['symlink','mount'] for a in audit)
 elif wrong_header:assert status==-22 and not any(a[0] in ['symlink','mount'] for a in audit)
 elif existing in ['foreign','regular'] or (existing=='own' and mode==1):assert status==-17 and links==initial_links
 elif fail_ro:assert status and result[7] and not state['ro']
 elif fail_rw:assert status and state['ro'] and links==initial_links
 elif fail_unlink>=0:assert status and state['ro']
 elif fail_create>=0 or alias_inode_wrong or fail_sync:assert status and result[6]==0 and not links and state['ro']
 elif mode==0:assert status==0 and links==initial_links and state['ro'] and not any(a[0]=='mount' for a in audit)
 elif mode==1:assert status==0 and result[3]==5 and links=={p:TARGET[i] for i,p in enumerate(DST)} and state['ro']
 elif mode==2:assert status==0 and not links and state['ro']
 return {'mode':mode,'existing':existing,'faults':dict(fail_create=fail_create,fail_unlink=fail_unlink,fail_sync=fail_sync,fail_rw=fail_rw,fail_ro=fail_ro,alias_inode_wrong=alias_inode_wrong,wrong_header=wrong_header,model=model),'status':status,'rollback':result[6],'readonly':result[7],'created':result[10],'removed':result[11],'remaining_links':len(links)}
cases=[dict(mode=0),{},dict(mode=2,existing='own'),dict(mode=2),dict(existing='own'),dict(existing='foreign'),dict(existing='regular'),dict(mode=0,existing='foreign'),dict(mode=2,existing='foreign'),dict(wrong_header=True),dict(model=15),dict(fail_rw=True),dict(fail_ro=True),dict(fail_sync=True),dict(alias_inode_wrong=True)]
cases += [dict(fail_create=i) for i in range(3)]
cases += [dict(mode=2,existing='own',fail_unlink=i) for i in range(3)]
cases += [dict(fail_create=2,fail_unlink=0)]
cases += [dict(mode=0,existing='own')]

import unittest
class NativeCases(unittest.TestCase):
 def test_native_cases(self):
  for case in cases:
   with self.subTest(case=case):run(**case)

if __name__=='__main__':unittest.main()
