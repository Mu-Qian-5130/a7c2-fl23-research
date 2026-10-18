"""Optional native query/controller/uploader tests; no USB, real scheduling or hardware.

Local firmware is supplied through the private fixture index. All memory and
MMIO are synthetic. Memcpy and interrupt barriers are modeled.
"""
import json,os,random,struct,unittest
from pathlib import Path
if not os.environ.get('A7C2_RESEARCH_FIXTURES'):
    raise unittest.SkipTest('Private firmware fixture index not supplied')
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import *
from looktool.six import TABLE_FILE,AP_SHA,CP_SHA,CP_SWITCH_SHA
from looktool.firmware import sha
BASE=0x108000
CONTEXT,ROOTPARAM,ENV=0x30000000,0x30001000,0x30002000
OUTPUT,DEBUG,STATE,WORK,METADATA,CACHE,BANKS=0x30003000,0x30003800,0x30004000,0x30005000,0x30007000,0x3000b000,0x30009000
DEV,CONTROL=0x30010000,0x30012000
MMIOS=[0xf3830000,0xf3930000,0xf3a30000,0xf3c30000]
CHUNKS=[(0xd000,0x12c),(0xd200,0xf0),(0xd300,0xf0),(0xd400,0xc0),(0xd500,0xc8),(0xd600,0xa0),(0xd700,0xa0),(0xd800,0x80)]

def signed(v, bits):
    return (int(v)+(1 << (bits-1))) % (1 << bits) - (1 << (bits-1))

def permutation(image):
    order = struct.unpack_from('<405H', image, 0xec7c20-BASE)
    if sorted(order) != list(range(405)):
        raise ValueError('Unexpected native hardware address permutation')
    return order

def pack_model(image, raw, level=8):
    if len(raw) != 1215 or not 0 <= level <= 255:
        raise ValueError('Expected three 405-byte signed correction planes')
    order = permutation(image)
    out = bytearray(1620)
    for y in range(5):
        for c1 in range(9):
            for c2 in range(9):
                i = y*81+c1*9+c2
                dy, dc1, dc2 = [signed(raw[j*405+i], 8) for j in range(3)]
                if 1 <= level <= 7:
                    dy, dc1, dc2 = [v*level >> 3 for v in (dy, dc1, dc2)]
                # With root+0x36=0 and transform=2 the native builder packs
                # all three values modulo 7 bits. Edge clipping belongs to
                # a separate adjustment/conversion branch, not this branch.
                word = ((dy & 127) << 22) | ((dc1 & 127) << 12) | ((dc2 & 127) << 2)
                struct.pack_into('<I', out, order[i]*4, word)
    return bytes(out)

def cpu_for(image):
 u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(BASE,(len(image)+4095)&~4095);u.mem_write(BASE,image)
 u.mem_map(0x1790000,0x10000);u.mem_map(0x1ac0000,0x10000)
 u.mem_map(0x30000000,0x20000);u.mem_map(0x31000000,4096)
 return u

def create(image,flag=0,direct=0,domain=0,root3=0,invalid=False,effect_off=False,bank=True):
 u=cpu_for(image)
 for mmio in MMIOS:u.mem_map(mmio,0x10000)
 u.mem_write(CONTEXT,struct.pack('<II',ROOTPARAM,ENV));u.mem_write(ROOTPARAM+1,bytes([flag]));u.mem_write(ROOTPARAM+3,bytes([root3]));u.mem_write(ROOTPARAM+0x2f,b'\x08')
 if effect_off:u.mem_write(ROOTPARAM+0x2cc,b'\x01')
 u.mem_write(ROOTPARAM+0x1f4,struct.pack('<I',DEV));u.mem_write(ROOTPARAM+0x1fc,struct.pack('<I',DEV))
 u.mem_write(ENV+3,b'\x01');u.mem_write(ENV+6,bytes([direct]));u.mem_write(ENV+0xc,bytes([domain]))
 u.mem_write(OUTPUT+4,struct.pack('<5I',DEBUG,STATE,WORK,METADATA,CACHE));u.mem_write(STATE+4,b'\xff')
 u.mem_write(WORK+0x6b0,struct.pack('<I',BANKS if bank else 0))
 if invalid:u.mem_write(0x110000,bytes(7322))
 counters={'builds':0,'uploads':0,'bytes':0,'queries':0}
 def hook(cpu,at,size,_):
  if at==0x42cf44:counters['queries']+=1
  elif at==0x23dc2c:counters['builds']+=1
  elif at==0x78aa20:counters['uploads']+=1
  elif at==0x61e60c:
   dst,src,n=[cpu.reg_read(r) for r in [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2]]
   assert n<=1620
   cpu.mem_write(dst,bytes(cpu.mem_read(src,n)));counters['bytes']+=n
   cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
  elif at in [0x607264,0x6073c4,0xb4457a]:
   cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
 u.hook_add(UC_HOOK_CODE,hook)
 return u,counters

def call(u,at,r0,r1,r2=0,r3=0):
 for reg,val in [(UC_ARM_REG_R0,r0),(UC_ARM_REG_R1,r1),(UC_ARM_REG_R2,r2),(UC_ARM_REG_R3,r3),(UC_ARM_REG_SP,0x3001f000),(UC_ARM_REG_LR,0x31000001)]:u.reg_write(reg,val)
 u.emu_start(at|1,0x31000000,count=900000)
 assert u.reg_read(UC_ARM_REG_PC)==0x31000000 and u.reg_read(UC_ARM_REG_SP)==0x3001f000

def schedule(image,rows,**kwargs):
 u,c=create(image,**kwargs);states=[]
 for marker,consumer,submit in rows:
  mmio=MMIOS[consumer];u.mem_write(DEV+0x184,struct.pack('<I',mmio));u.mem_write(ROOTPARAM+0x2e,bytes([marker]))
  call(u,0x23d380,CONTEXT,OUTPUT)
  enabled=u.mem_read(STATE+0x18,1)[0];dirty=u.mem_read(STATE+0x24,1)[0];pointer=struct.unpack('<I',u.mem_read(STATE+0x20,4))[0]
  assert not(enabled and dirty and not pointer)
  before=c['uploads']
  if submit:
   # Native r3 points to state+0x0c. Its +0x14 is table pointer and
   # +0x18 is the controller's state+0x24 upload flag.
   u.mem_write(0x3001f000,b'\0'*8)
   call(u,0x42cd28,DEV,DEV,CONTROL,STATE+0xc)
  actual=b''.join(bytes(u.mem_read(mmio+offset,n)) for offset,n in CHUNKS)
  expected=pack_model(image,image[TABLE_FILE+32+(marker-249)*1215:TABLE_FILE+32+(marker-248)*1215]) if 249<=marker<=254 else None
  states.append({'marker':marker,'consumer':consumer,'submitted':submit,'enabled':enabled,'dirty':dirty,'pointer':pointer,'uploaded':c['uploads']>before,'hardware_bytes_match':actual==expected if expected and enabled else None})
 return states,c

class NativePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        index=Path(os.environ['A7C2_RESEARCH_FIXTURES']);paths=json.loads(index.read_text())
        cls.old=(index.parent/paths['switch_cp']).read_bytes();cls.new=(index.parent/paths['v4_cp']).read_bytes()
        if sha(cls.old)!=CP_SWITCH_SHA or sha(cls.new)!=CP_SHA:raise ValueError('Exact private CP fixtures required')
    def test_dropped_submissions_recover_without_rebuilding(self):
        for marker in range(249,255):
            for consumer in range(4):
                for root3 in [0,1]:
                    rows=[(marker,consumer,False),(marker,consumer,True),(marker,consumer,True)]
                    a,ca=schedule(self.old,rows,root3=root3);b,cb=schedule(self.new,rows,root3=root3)
                    self.assertFalse(a[1]['hardware_bytes_match']);self.assertFalse(a[2]['hardware_bytes_match'])
                    self.assertTrue(b[1]['hardware_bytes_match']);self.assertTrue(b[2]['hardware_bytes_match'])
                    self.assertEqual(ca['builds'],1);self.assertEqual(cb['builds'],1)
    def test_random_consumer_switching_and_repeated_upload_cost(self):
        for seed in range(4):
            rng=random.Random(seed);rows=[]
            for _ in range(60):
                marker,consumer=rng.randrange(249,255),rng.randrange(4)
                rows.extend([(marker,consumer,False),(marker,consumer,True)])
            states,_=schedule(self.new,rows)
            self.assertTrue(all(s['hardware_bytes_match'] for s in states if s['submitted']))
        _,old=schedule(self.old,[(249,0,True)]*10);_,new=schedule(self.new,[(249,0,True)]*10)
        self.assertEqual((old['uploads'],new['uploads']),(1,10))
        self.assertEqual((old['builds'],new['builds']),(1,1))
    def test_snapshot_native_direct_and_negative_paths(self):
        seq=[(m,0,True) for m in [0,249,249,250,251,252,253,254,254,0,15,19,20]]
        for direct in [0,1]:
            for domain in [0,8,11]:
                for root3 in [0,1]:
                    self.assertEqual(schedule(self.old,seq,flag=1,direct=direct,domain=domain,root3=root3),schedule(self.new,seq,flag=1,direct=direct,domain=domain,root3=root3))
        for domain in [0,8,11]:
            for root3 in [0,1]:self.assertEqual(schedule(self.old,seq,direct=1,domain=domain,root3=root3),schedule(self.new,seq,direct=1,domain=domain,root3=root3))
        for marker in [0,1,2,3,5,13,15,16,17,18,19,20,255]:
            for root3 in [0,1]:self.assertEqual(schedule(self.old,[(marker,0,True)]*3,root3=root3),schedule(self.new,[(marker,0,True)]*3,root3=root3))
        for negative in [{'invalid':True},{'effect_off':True},{'bank':False}]:
            states,_=schedule(self.new,seq,**negative)
            self.assertFalse(any(s['enabled'] for s in states if 249<=s['marker']<=254))

if __name__=='__main__':unittest.main()
