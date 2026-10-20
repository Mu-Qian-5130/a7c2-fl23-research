"""Compare reconstructed queue policy with actual A7C II pruning instructions.

Stops BEFORE the target dequeuer. It does not mock a successful allocation,
dequeue, release, recording or capture operation. Metadata is synthetic.
"""
import argparse,hashlib,json,struct
from pathlib import Path
from support.build import compile_shared
from support.elf import image_loader
from support.memory import MEM, STOP, STACK
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC

ORIGINAL_CP='f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428'
def words(*v):return struct.pack('<'+'I'*len(v),*v)

class TargetOracle:
    def __init__(self,cp):
        self.u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u=self.u
        for at,n in [(0x372000,0x1000),(0xa09000,0x1000),(0x1a53000,0x1000),(MEM,0x40000),(STOP,0x1000),(STACK,0x4000)]:u.mem_map(at,n)
        u.mem_write(0x372000,cp[0x372000:0x373000]);u.mem_write(0xa09000,cp[0xa09000:0xa0a000]);self.outcome=None
        def trace(cpu,address,size,user):
            if address==0x372418:
                self.outcome=bool(cpu.reg_read(UC_ARM_REG_R1));cpu.emu_stop()
            elif address==STOP:
                self.outcome=False;cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE,trace)
    def check(self,v):
        policy,limit,reference,oldest,count=v;u=self.u
        q=MEM;head=MEM+0x1000;tail=MEM+0x1020;old_ref=MEM+0x2000;new_ref=MEM+0x2020;old_frame=MEM+0x10000;new_frame=MEM+0x20000
        u.mem_write(q,words(0,head,tail,count,0,policy,limit,0)+bytes(32))
        u.mem_write(head,words(0,0,old_ref));u.mem_write(tail,words(0,0,new_ref))
        u.mem_write(old_ref,words(old_frame));u.mem_write(new_ref,words(new_frame))
        u.mem_write(old_frame+0xb98,words(oldest));u.mem_write(new_frame+0x66f4,words(reference))
        before=bytes(u.mem_read(q,64));self.outcome=None
        u.reg_write(UC_ARM_REG_R0,q);u.reg_write(UC_ARM_REG_SP,STACK+0x3000);u.reg_write(UC_ARM_REG_LR,STOP|1)
        u.emu_start(0x3722fd,0xffffffff,count=200)
        assert self.outcome is not None,'Unresolved call or instruction limit is not success'
        assert bytes(u.mem_read(q,64))==before
        return self.outcome
    def check_flush(self,v):
        policy,limit,reference,oldest,marker=v;u=self.u
        q=MEM;head=MEM+0x1000;holder=MEM+0x2000;frame=MEM+0x10000
        u.mem_write(q,words(0,head,0,1,0,policy,limit,2,reference)+bytes(28))
        u.mem_write(head,words(0,0,holder));u.mem_write(holder,words(frame))
        u.mem_write(frame+0xb98,words(oldest));u.mem_write(frame+0x66ec,words(marker))
        before=bytes(u.mem_read(q,64));self.outcome=None
        u.reg_write(UC_ARM_REG_R0,q);u.reg_write(UC_ARM_REG_SP,STACK+0x3000);u.reg_write(UC_ARM_REG_LR,STOP|1)
        u.emu_start(0xa09f4b,0xffffffff,count=200)
        assert self.outcome is not None and bytes(u.mem_read(q,64))==before
        return self.outcome
    def latch(self,initial,sequence,timestamp):
        u=self.u;u.mem_write(MEM,initial)
        u.reg_write(UC_ARM_REG_R0,MEM);u.reg_write(UC_ARM_REG_R2,sequence);u.reg_write(UC_ARM_REG_R3,timestamp)
        u.reg_write(UC_ARM_REG_SP,STACK+0x3000);u.reg_write(UC_ARM_REG_LR,STOP|1)
        u.emu_start(0xa09e11,STOP,count=100)
        assert u.reg_read(UC_ARM_REG_PC)==STOP
        return bytes(u.mem_read(MEM,64))

def invoke(u,symbol,arch,args):
    if arch=='aarch64':regs=[UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2];sp,lr,pc=UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
    else:regs=[UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2];sp,lr,pc=UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
    for reg,value in zip(regs,args):u.reg_write(reg,value)
    u.reg_write(sp,STACK+0x3000);u.reg_write(lr,STOP if arch=='aarch64' else STOP|1)
    u.emu_start(symbol,STOP,count=200);assert u.reg_read(pc)==STOP
    return u.reg_read(regs[0])&0xffffffff

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cp',type=Path,required=True);p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    cp=a.cp.read_bytes();assert hashlib.sha256(cp).hexdigest()==ORIGINAL_CP
    a.output.mkdir(parents=True,exist_ok=True);oracle=TargetOracle(cp);cases=[]
    source=Path(__file__).with_name('retention_policy.c')
    vectors=[]
    for policy in [0,1,2]:
        for limit in [0,1,5,10,100,500,1000]:
            for reference in [0,1000,1000000,0xfffffff0]:
                cutoff=(reference-limit*2000)&0xffffffff
                for oldest in [(cutoff-1)&0xffffffff,cutoff,(cutoff+1)&0xffffffff]:
                    for count in [0,1,limit+1]:vectors.append((policy,limit,reference,oldest,count))
    expected=[oracle.check(v) for v in vectors]
    for arch,target in [('aarch64','aarch64-linux-gnu'),('thumb','thumb-linux-gnueabi')]:
        path=a.output/(arch+'-retention.elf')
        compile_shared(a.zig, arch, path,
            [source], optimization='-O2', debug=False, symbolic=False)
        u,syms=image_loader(path,arch,('queue_should_trim','queue_should_discard','queue_configure','queue_latch_reference'))
        for vector,want in zip(vectors,expected):
            u.mem_write(MEM,words(*vector));before=bytes(u.mem_read(MEM,20))
            got=invoke(u,syms['queue_should_trim'],arch,[MEM]);assert got==int(want),(arch,vector,got,want)
            assert bytes(u.mem_read(MEM,20))==before
            cases.append({'arch':arch,'test':'native-prune-decision','input':vector,'would_dequeue':bool(got)})
        for policy in [0,1,2]:
            for limit in [0,1,5,10,100,500,1000]:
                for reference in [0,1000,1000000,0xfffffff0]:
                    cutoff=(reference-limit*2000)&0xffffffff
                    for oldest in [(cutoff-1)&0xffffffff,cutoff,(cutoff+1)&0xffffffff]:
                        for marker in [0xffffffff,0,5]:
                            vector=(policy,limit,reference,oldest,marker);want=oracle.check_flush(vector)
                            u.mem_write(MEM,words(*vector));before=bytes(u.mem_read(MEM,20))
                            got=invoke(u,syms['queue_should_discard'],arch,[MEM]);assert got==int(want)
                            assert bytes(u.mem_read(MEM,20))==before
                            cases.append({'arch':arch,'test':'native-post-trigger-decision','input':vector,'would_discard':bool(got)})
        for count in [0,1,10]:
            for state in [0,1,2]:
                for duration in [0,4,5,500,1000,1001]:
                    initial=[0x55555555]*16;initial[3]=count;initial[7]=state
                    u.mem_write(MEM,words(*initial));got=invoke(u,syms['queue_configure'],arch,[MEM,duration])
                    after=list(struct.unpack('<16I',bytes(u.mem_read(MEM,64))))
                    if not 5<=duration<=1000:assert got==0xffffffea and after==initial
                    elif count or state:assert got==0xfffffff0 and after==initial
                    else:
                        assert got==0;want=initial.copy();want[5]=0;want[6]=duration;assert after==want
                    cases.append({'arch':arch,'test':'empty-idle-config-guard','count':count,'state':state,'duration':duration})
        for flag in [0,1,255]:
            for sequence in [0,1,0xffffffff]:
                for timestamp in [0,1000,0xffffffff]:
                    initial=bytearray(bytes([0xa5])*64);initial[0x2c]=flag
                    expected_latched=oracle.latch(bytes(initial),sequence,timestamp)
                    u.mem_write(MEM,bytes(initial));invoke(u,syms['queue_latch_reference'],arch,[MEM,sequence,timestamp])
                    assert bytes(u.mem_read(MEM,64))==expected_latched
                    cases.append({'arch':arch,'test':'native-reference-latch','initial_flag':flag,'sequence':sequence,'timestamp':timestamp})
    report={'status':'OFFLINE_RETENTION_POLICY_NOT_PHYSICAL_PRECAPTURE','target_CP_sha256':ORIGINAL_CP,
        'native_target_pruning_entry_file':'0x3722fc','first_dequeue_boundary_file':'0x372418',
        'target_prune_vectors':len(vectors),'target_flush_vectors_per_arch':756,'native_and_config_cases_passed':len(cases),'cases':cases,
        'validation':'Actual target instructions decide whether to enter the dequeuer and its discard/save flag. Execution stops before it; no successful frame deletion, recording or release is invented.',
        'new_adapter':'Caller-owned empty/idle queue can be assigned time policy and duration; no real camera instance or call site is bound.',
        'unknown':['allocation and frame ownership','sensor readout beforeS2','S1/S2 delivery','post-trigger save/cancel','CP scheduler integration','timer rollover behavior beyond matching target arithmetic'],
        'camera_IO':False,'firmware_modified':False}
    (a.output/'retention-verification.private.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
if __name__=='__main__':main()
