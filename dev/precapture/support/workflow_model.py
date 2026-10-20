"""Explicit virtual sensor/storage actors for the new lifecycle component.

No original firmware is loaded or stubbed. Pixel arrays, files and ownership
are real test objects; exposures and terminal fences belong to this virtual
device only. It is not an A7C II hardware emulator or live native adapter.
"""
import hashlib
import os
from pathlib import Path
import struct

from unicorn import arm_const as A, arm64_const as X
from .elf import image_loader
from .memory import MEM, STACK, STOP

STATE, ACTION, COMPLETION, OFFER, NATIVE = MEM+0x100, MEM+0x600, MEM+0x700, MEM+0x800, 0x60000000
FIELDS = ('magic generation phase ticket duration_ms capacity original_policy original_limit '
          'parameter_epoch issued pending_slot triggered cancelled count saved released '
          'rejected last_lease ingress_serial terminal_serial result last_phase saved_mask original_flag').split()
ACTION_FIELDS = 'kind generation ticket lease handle value auxiliary serial trigger'.split()
COMPLETION_FIELDS = 'kind generation ticket outcome lease value auxiliary serial'.split()
NAMES = {1:'configure',2:'refresh-on',3:'start',4:'stop',5:'terminal-fence',
         6:'save',7:'release',8:'restore-policy',9:'refresh-baseline'}


class WorkflowVM:
    def __init__(self, elf, arch, folder, *, duration=500, capacity=8, generation=7,
                 original_policy=1, original_limit=9, epoch=20, original_flag=0,
                 save_consumes=False):
        self.arch=arch
        self.cpu,self.symbols=image_loader(elf,arch,tuple('precapture_workflow_'+n for n in
            ('begin','next','complete','frame','trigger','cancel','rearm')))
        self.cpu.mem_map(NATIVE,0x7000)
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=False)
        self.generation=generation;self.epoch=epoch;self.original_flag=original_flag
        self.policy=(original_policy,original_limit);self.baseline=self.policy
        self.parameters=(epoch,original_flag);self.active=False;self.stopped=True
        self.ledger={};self.saved={};self.pending_frames=[];self.applied=set();self.journal=[]
        self.serial=0;self.offers=[]
        self.save_consumes=save_consumes;self.consumed=[]
        assert self.call('begin',STATE,generation,duration,capacity,original_policy,
                         original_limit,epoch,original_flag)==1

    def call(self,name,*args):
        u=self.cpu
        if self.arch=='aarch64':
            registers=[getattr(X,f'UC_ARM64_REG_X{i}') for i in range(8)]
            sp,lr,pc,ret=X.UC_ARM64_REG_SP,X.UC_ARM64_REG_LR,X.UC_ARM64_REG_PC,registers[0]
        else:
            registers=[A.UC_ARM_REG_R0,A.UC_ARM_REG_R1,A.UC_ARM_REG_R2,A.UC_ARM_REG_R3]
            sp,lr,pc,ret=A.UC_ARM_REG_SP,A.UC_ARM_REG_LR,A.UC_ARM_REG_PC,registers[0]
        stack=STACK+0x3000
        u.mem_write(stack,bytes(64))
        for index,value in enumerate(args):
            if index<len(registers):u.reg_write(registers[index],value)
            else:u.mem_write(stack+(index-len(registers))*4,struct.pack('<I',value))
        u.reg_write(sp,stack);u.reg_write(lr,STOP|(self.arch=='thumb'))
        u.emu_start(self.symbols['precapture_workflow_'+name],STOP,count=20000)
        assert u.reg_read(pc)==STOP,'Instruction exhaustion is not completion'
        value=u.reg_read(ret)&0xffffffff
        return value if value<0x80000000 else value-(1<<32)

    def state(self):
        raw=bytes(self.cpu.mem_read(STATE,920))
        d=dict(zip(FIELDS,struct.unpack_from('<24I',raw)))
        d['latest'],d['trigger']=struct.unpack_from('<2Q',raw,96)
        return d

    def next(self):
        self.cpu.mem_write(ACTION,bytes([0xa5])*40)
        result=self.call('next',STATE,ACTION)
        if result!=1:
            assert bytes(self.cpu.mem_read(ACTION,40))==bytes([0xa5])*40
            return result
        a=dict(zip(ACTION_FIELDS,struct.unpack('<8IQ',bytes(self.cpu.mem_read(ACTION,40)))))
        self.journal.append(dict(event='request',**a))
        # Reading next twice must not submit/produce another request.
        frozen=bytes(self.cpu.mem_read(STATE,920))
        assert self.call('next',STATE,ACTION)==0
        assert bytes(self.cpu.mem_read(STATE,920))==frozen
        return a

    def completion(self,a,**overrides):
        c=dict(kind=a['kind'],generation=a['generation'],ticket=a['ticket'],outcome=1,
               lease=a['lease'],value=0,auxiliary=0,serial=self.serial)
        c.update(overrides)
        return c

    def deliver(self,c):
        self.cpu.mem_write(COMPLETION,struct.pack('<8I',*(c[k] for k in COMPLETION_FIELDS)))
        result=self.call('complete',STATE,COMPLETION)
        self.journal.append(dict(event='completion',return_value=result,**c))
        self.check_ownership()
        return result

    def check_ownership(self):
        state=self.state();slots=[]
        for index in range(state['capacity']):
            lease,handle,begin,end=struct.unpack('<2I2Q',bytes(self.cpu.mem_read(STATE+152+24*index,24)))
            if lease:
                assert handle in self.ledger and self.ledger[handle]['owner']=='workflow'
                assert self.ledger[handle]['lease']==lease
                slots.append(handle)
        assert len(slots)==state['count'] and len(set(slots))==len(slots)
        assert set(slots)=={h for h,f in self.ledger.items() if f['owner']=='workflow'}

    def write_pixels(self,lease,data):
        path=self.folder/f'virtual-generation-{self.generation:08x}-exposure-{lease:04d}.pgm'
        with path.open('xb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        assert path.read_bytes()==data
        return path

    def apply(self,a):
        """Execute an explicit virtual service, without returning a native stub."""
        assert a['ticket'] not in self.applied,'An ambiguous request must not be replayed'
        kind=a['kind'];c=self.completion(a)
        if kind==1:
            assert not self.active and not self.ledger
            self.policy=(0,a['value']);c.update(value=0,auxiliary=a['value'])
        elif kind==2:
            assert self.policy[0]==0
            self.parameters=(a['auxiliary']+1,1)
            c.update(value=self.parameters[0],auxiliary=1)
        elif kind==3:
            assert self.parameters==(a['auxiliary']+1,1),'Stale parameter object cannot start'
            self.active=True;self.stopped=False;c['value']=self.parameters[0]
        elif kind==4:
            self.active=False;self.stopped=True
        elif kind==5:
            # A real event queue, rather than a fabricated empty-count reply.
            # Late generated frames must finish ingress before a fence is emitted.
            assert self.stopped and not self.active
            while self.pending_frames:
                args=self.pending_frames.pop(0);self.offer(*args)
            assert not self.pending_frames
            c.update(value=self.generation,serial=self.serial)
        elif kind in (6,7):
            f=self.ledger[a['handle']]
            assert f['owner']=='workflow' and f['lease']==a['lease']
            if kind==6:
                assert self.stopped and not self.pending_frames
                self.saved[f['lease']]=self.write_pixels(f['lease'],f['data'])
                consumed=(f['lease']%2==0) if self.save_consumes=='mixed' else self.save_consumes
                if consumed:
                    c.update(value=1,_released_handle=a['handle'])
                    self.consumed.append((self.generation,f['lease']))
            else:
                # Keep this known successful actor result pending until deliver;
                # controller ownership is not surrendered on request issuance.
                c['_released_handle']=a['handle']
        elif kind==8:
            assert not self.ledger and self.stopped and not self.pending_frames
            self.policy=(a['value'],a['auxiliary'])
            c.update(value=self.policy[0],auxiliary=self.policy[1])
        elif kind==9:
            assert self.policy==self.baseline
            self.parameters=(a['auxiliary']+2,self.original_flag)
            c.update(value=self.parameters[0],auxiliary=self.original_flag)
        else:raise AssertionError('Unknown action')
        self.applied.add(a['ticket']);return c

    def finish(self,a,**overrides):
        c=self.apply(a);handle=c.pop('_released_handle',None);c.update(overrides)
        # The virtual service has completed; quarantine ownership on uncertain
        # reports just as the controller does. Never actually reuse that buffer.
        if handle is not None and c['outcome']==1:
            self.ledger.pop(handle)
        result=self.deliver(c)
        return result

    def drive(self,*,limit=300):
        for _ in range(limit):
            a=self.next()
            if not isinstance(a,dict):return a
            assert self.finish(a)==1
        raise AssertionError('Lifecycle failed to reach a wait/done boundary')

    def offer(self,lease,end,*,begin=None,marker=2,cls=4,kind=0,error=0,generation=None,serial=None):
        begin=end-100 if begin is None else begin;handle=0x1000+lease
        assert handle not in self.ledger
        pixels=b'P5\n32 16\n65535\n'+b''.join(struct.pack('>H',(lease*9001+i*257)&0xffff) for i in range(512))
        self.ledger[handle]=dict(lease=lease,begin=begin,end=end,data=pixels,owner='caller')
        self.cpu.mem_write(OFFER,struct.pack('<2I2Q',lease,handle,begin,end))
        frame=bytearray(0x6800)
        for offset,value in ((0x66e8,marker),(0xbb4,cls),(0x5c10,kind),(0x617c,error)):
            struct.pack_into('<I',frame,offset,value)
        self.cpu.mem_write(NATIVE,bytes(frame))
        event_generation=self.generation if generation is None else generation
        event_serial=self.serial+1 if serial is None else serial
        if event_generation==self.generation:self.serial=event_serial
        result=self.call('frame',STATE,event_generation,event_serial,OFFER,NATIVE)
        assert bytes(self.cpu.mem_read(NATIVE,len(frame)))==bytes(frame)
        if result==1:self.ledger[handle]['owner']='workflow'
        else:self.ledger.pop(handle)  # Caller, not the controller, releases it.
        self.offers.append(dict(lease=lease,begin=begin,end=end,return_value=result,
                                pixel_sha256=hashlib.sha256(pixels).hexdigest()))
        self.check_ownership();return result

    def trigger(self,tick):
        args=(STATE,tick) if self.arch=='aarch64' else (STATE,0,tick&0xffffffff,tick>>32)
        return self.call('trigger',*args)

    def cancel(self):return self.call('cancel',STATE)

    def rearm(self,generation):
        assert self.state()['phase']==10 and not self.ledger and self.policy==self.baseline
        assert self.call('rearm',STATE,generation)==1
        self.generation=generation;self.epoch+=2;self.serial=0;self.saved={};self.offers=[]

    def assert_closed(self,expected_result,expected_leases):
        s=self.state()
        assert (s['phase'],s['result'],s['count'],s['issued'])==(10,expected_result,0,0)
        assert not self.ledger and not self.pending_frames and not self.active
        assert self.policy==self.baseline and self.parameters==(self.epoch+2,self.original_flag)
        assert sorted(self.saved)==sorted(expected_leases)
        for lease,path in self.saved.items():
            expected=next(f['pixel_sha256'] for f in self.offers if f['lease']==lease)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==expected
        return dict(result=s['result'],saved=sorted(self.saved),released=s['released'],
                    rejected=s['rejected'],restored=True,pixel_bytes_verified=True)
