"""Execute the original target's node-pool/queue initializer, including its
native ARM memory-clear routine. No OS-lock stub, frame allocation or USB.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--cp',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
cp=args.cp.read_bytes()
assert hashlib.sha256(cp).hexdigest()=='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
for at,size in [(0xa09000,4096),(0x516000,8192),(0x1a44000,0x3000),(0x20000000,4096),(0x40000000,0x4000)]:u.mem_map(at,size)
u.mem_write(0xa09000,cp[0xa09000:0xa0a000]);u.mem_write(0x516000,cp[0x516000:0x518000])
u.mem_write(0x1a44000,bytes([0xa5])*0x3000)
u.reg_write(UC_ARM_REG_SP,0x40003000);u.reg_write(UC_ARM_REG_LR,0x20000001)
visited=[];u.hook_add(UC_HOOK_CODE,lambda cpu,at,size,user:visited.append(at))
u.emu_start(0xa09ccf,0x20000000,count=10000)
assert u.reg_read(UC_ARM_REG_PC)==0x20000000
read=lambda at:struct.unpack('<I',bytes(u.mem_read(at,4)))[0]
pool=0x1a444f4;queue=0x1a45c70
assert [read(pool+i) for i in [0,4,8]]==[pool+12,500,500]
nodes=[];ptr=read(pool)
while ptr:
    assert pool+12<=ptr<queue and (ptr-(pool+12))%12==0 and ptr not in nodes
    nodes.append(ptr);ptr=read(ptr)
assert len(nodes)==500
assert [read(queue+i) for i in [0,4,8,12,16]]==[0xe75730,queue+4,queue+4,0,pool]
assert bytes(u.mem_read(queue+0x14,0x1a))==bytes(0x1a) and read(queue+0x30)==0
assert 0x516d00 in visited and 0x516d0c in visited
assert bytes(u.mem_read(0x1a44000,pool-0x1a44000))==bytes([0xa5])*(pool-0x1a44000)
assert bytes(u.mem_read(queue+0x34,0x1a47000-queue-0x34))==bytes([0xa5])*(0x1a47000-queue-0x34)
matrix=[]
for event in range(5):
    row=[]
    for state in range(3):
        next_state,callback=struct.unpack_from('<2I',cp,0xd6d740+event*24+state*8)
        assert next_state<3 and callback&1
        row.append({'from_state':state,'to_state':next_state,'callback_VA':hex(callback),'callback_file':hex((callback&~1)-0x108000)})
    matrix.append({'event':event,'transitions':row})
result={'target_CP_sha256':hashlib.sha256(cp).hexdigest(),'original_initializer_file':'0xa09cce',
    'original_ARM_clear_file':'0x516d00','instructions_executed':len(visited),'node_pool_VA':hex(pool),'queue_VA':hex(queue),
    'nodes_verified':500,'node_bytes':12,'pool_bytes_including_header':12+500*12,'queue_bytes':0x34,
    'native_empty_idle_state_verified':True,'guard_bytes_unchanged':True,'state_table_file':'0xd6d740','state_matrix':matrix,
    'not_image_buffer_capacity':'500 is a linked-list node count, not 500 allocated full-resolution image buffers',
    'unresolved':['node allocation/free requires original OS locks','image ownership is outside this metadata pool','preS2 sensor readout not demonstrated'],
    'camera_IO':False,'firmware_modified':False}
args.output.mkdir(parents=True,exist_ok=True)
(args.output/'queue-storage-verification.private.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='state_matrix'},indent=2))
