"""Run bounded production instruction paths against explicit native fixtures."""
from pathlib import Path
import argparse,json,struct,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/looks'))
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED
from unicorn.arm64_const import *
from native_ap_fixture import load
from looktool.fixedlookscode import code,PREDICATE,CLASSIFY,NORMALIZE
image=None
BASE=0x400000000
STACK=0x500100000
STOP=0x500200000
DATA=0x500300000
X=[UC_ARM64_REG_X0+i for i in range(29)]+[UC_ARM64_REG_X29,UC_ARM64_REG_X30]
REL_PAGES={}
def configure(source):
    global image,REL_PAGES
    image=load(source);REL_PAGES={}
    for dest,add in image.rel.items():REL_PAGES.setdefault(dest&~4095,[]).append((dest,add))
    return image
class Native:
    def __init__(self,mask=None):
        self.u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);self.pages=set();self.hooks={};self.calls=[]
        self.windows={} if mask is None else code(mask)
        self.u.hook_add(UC_HOOK_MEM_UNMAPPED,self.missing)
        self.u.hook_add(UC_HOOK_CODE,self.step)
        self.put(STACK,bytes(0x10000));self.put(STOP,bytes(4096));self.put(DATA,bytes(0x10000))
    def missing(self,u,access,at,size,value,_):
        page=at&~4095;va=page-BASE
        try:off=image.offset(va)
        except ValueError:return False
        b=bytearray(image.raw[off:off+4096].ljust(4096,b'\0'))
        for start,patch in self.windows.items():
            lo,hi=max(start,va),min(start+len(patch),va+4096)
            if lo<hi:b[lo-va:hi-va]=patch[lo-start:hi-start]
        self.put(page,bytes(b))
        for dest,add in REL_PAGES.get(va,[]):self.u.mem_write(BASE+dest,struct.pack('<Q',BASE+add))
        return True
    def put(self,at,b):
        for page in range(at&~4095,(at+len(b)+4095)&~4095,4096):
            if page not in self.pages:self.u.mem_map(page,4096);self.pages.add(page)
        self.u.mem_write(at,b)
    def read(self,at,n):return bytes(self.u.mem_read(at,n))
    def word(self,at):return struct.unpack('<I',self.read(at,4))[0]
    def ret(self,value=None):
        if value is not None:self.u.reg_write(UC_ARM64_REG_X0,value)
        self.u.reg_write(UC_ARM64_REG_PC,self.u.reg_read(UC_ARM64_REG_LR))
    def step(self,u,at,size,_):
        off=at-BASE
        if off in self.hooks:
            args=[u.reg_read(r) for r in X[:9]];self.calls.append((off,args))
            self.hooks[off](self,args)
    def run(self,at,*args,limit=10000):
        saved={r:0xa10000+i*0x101 for i,r in enumerate(X[19:30])}
        for r,v in saved.items():self.u.reg_write(r,v)
        for r,v in zip(X,args):self.u.reg_write(r,v&0xffffffffffffffff)
        self.u.reg_write(UC_ARM64_REG_SP,STACK+0xf000);self.u.reg_write(UC_ARM64_REG_LR,STOP)
        self.u.emu_start(BASE+at,STOP,count=limit)
        assert self.u.reg_read(UC_ARM64_REG_PC)==STOP,hex(self.u.reg_read(UC_ARM64_REG_PC))
        assert self.u.reg_read(UC_ARM64_REG_SP)==STACK+0xf000
        assert all(self.u.reg_read(r)==v for r,v in saved.items()),'callee ABI'
        return self.u.reg_read(UC_ARM64_REG_X0)&0xffffffff
def stub_lock(n,a):n.ret()
def main(report):
    counts={};masks=range(64)
    for mask in masks:
        n=Native(mask)
        for item in [0,*range(0x7e0,0x820),0xffff,0xffffffff]:
            want=int(0<=item-0x7f8<6 and not(mask>>(item-0x7f8)&1))
            assert n.run(PREDICATE,0,item)==want,(mask,item)
            counts['native_predicate']=counts.get('native_predicate',0)+1
        # Original lock-backed menu classifier, with property reader/locks as
        # explicit inputs. The predicate itself and shared tail are executed.
        n.hooks.update({0x2e06cc0:stub_lock,0x2e068cc:stub_lock,0x21ab658:lambda n,a:n.ret(DATA)})
        for item in range(0x7ec,0x7ff):
            n.put(DATA,struct.pack('<I',item))
            assert n.run(CLASSIFY,DATA)==int(0<=item-0x7f8<6 and not(mask>>(item-0x7f8)&1))
            counts['native_menu_classifier']=counts.get('native_menu_classifier',0)+1
        # Simulate every base being loaded from a saved setting/MR. Execute
        # actual accessor and normalization, checking all adjacent values.
        for base_value in range(12):
            vals=[(i+base_value)%12 for i in range(18)]
            n.put(BASE+0x7eac508,struct.pack('<18I',*vals))
            before=n.read(BASE+0x7eac500,0x60) if BASE+0x7eac500 in n.pages else None
            result=n.run(0x287ee10)
            assert result==((BASE+0x7eac508)&0xffffffff)
            want=[0 if 10<=i<=15 and mask>>(i-10)&1 else v for i,v in enumerate(vals)]
            assert n.read(BASE+0x7eac508,72)==struct.pack('<18I',*want)
            counts['saved_and_recall_array']=counts.get('saved_and_recall_array',0)+1
    # Run original full right/left page callbacks. Their state operations are
    # hooked only to capture the same native update record used by stock.
    page_records=[]
    for mask in (None,0,1,2,21,42,63):
        for item in range(0x7ec,0x7fe):
            for handler in (0x21ac46c,0x21ac530,0x21ac7dc,0x21ac9f4):
                for page in (0,1):
                    n=Native(mask);obj=DATA+0x1000;record=[]
                    n.put(DATA,struct.pack('<I',item));n.put(obj+0x190,struct.pack('<I',page))
                    n.hooks.update({0x2e06cc0:stub_lock,0x2e068cc:stub_lock,
                        0x21ab658:lambda n,a:n.ret(DATA),
                        0x21ab830:lambda n,a:(n.put(a[0]+8,struct.pack('<Q',DATA+0x3000)),n.ret()),
                        0x21ab854:lambda n,a:n.ret(),
                        0x21ab670:lambda n,a:n.ret(),
                        0x21ac268:lambda n,a:(record.append(n.word(a[1])),n.ret()),
                        0x21aba7c:lambda n,a:n.ret(),0x21ab6c0:lambda n,a:n.ret(),
                        0x21ac678:lambda n,a:n.ret()})
                    n.run(handler,obj)
                    page_records.append((mask,item,handler,page,record))
    stock={(i,h,p):r for m,i,h,p,r in page_records if m is None}
    for mask,item,handler,page,record in page_records:
        fixed=mask is not None and 0<=item-0x7f8<6 and mask>>(item-0x7f8)&1
        want=stock[(0x7ec if fixed else item,handler,page)]
        assert record==want,(mask,hex(item),hex(handler),page,record,want)
    counts['original_navigation_callbacks']=len(page_records)
    for mask in masks:
        n=Native(mask);current_index=[0];logs=[]
        selectors={n.run(0x2d508c0,value):value for value in range(19)}
        assert all(i in selectors for i in range(18))
        values_at=BASE+0x7eac508;info_at=BASE+0x7eac550
        n.put(values_at,bytes(72));n.put(info_at,bytes(720))
        def context(n,a):n.put(a[0],struct.pack('<QQ',0,0x12345678));n.ret()
        def logger(n,a):logs.append((a[0],a[1],a[2],n.word(a[3]),a[4]));n.ret()
        n.hooks.update({0x178f950:context,0x178f974:stub_lock,
            0x2e06cc0:stub_lock,0x2e068cc:stub_lock,
            0x286964c:lambda n,a:n.ret(DATA),
            0x36830a8:logger,0x2506ff0:stub_lock,0x2506218:stub_lock})
        for linked in (False,True):
            for index in range(18):
                current_index[0]=index
                for value in range(12):
                    initial=[0 if 10<=i<=15 and mask>>(i-10)&1 else (i+3)%12 for i in range(18)]
                    n.put(values_at,struct.pack('<18I',*initial));n.put(DATA,struct.pack('<I',selectors[index]))
                    n.put(info_at+index*40+8,struct.pack('<Q',DATA+0x8000 if linked else 0))
                    n.put(DATA+0x8000,struct.pack('<I',initial[index]));logs.clear();n.calls.clear()
                    n.run(0x2614bcc,DATA+0x4000,value)
                    expected=0 if 10<=index<=15 and mask>>(index-10)&1 else value
                    want=initial[:];want[index]=expected
                    assert n.read(values_at,72)==struct.pack('<18I',*want),(mask,index,value,linked)
                    assert n.word(DATA+0x8000)==(expected if linked else initial[index])
                    assert logs==[(0x12345678,0x14e9+index,DATA+0x8000 if linked else values_at+index*4,expected,4)]
                    assert [c[0] for c in n.calls]==[0x178f950,0x2e06cc0,0x286964c,0x36830a8,0x2506ff0,0x2e068cc,0x178f974,0x2506218]
                    counts['actual_native_setter']=counts.get('actual_native_setter',0)+1
        # Cached BW is deliberately inconsistent with the selected fixed look.
        # Execute all eight original parameter reads through the patched branch.
        obj=DATA+0x1000;param=[1]
        n.hooks.update({0x21b0d10:lambda n,a:n.ret(param[0])})
        offsets=[0x2848,0x2a40,0x2c38,0x2e30,0x3028,0x3220,0x3418,0x3610]
        for p,off in enumerate(offsets):
            for index in range(18):n.put(obj+off+index*24,struct.pack('<I',10000+p*100+index))
        for index in range(18):n.put(obj+0x3968+index*4,struct.pack('<I',8))
        for item in range(0x7ec,0x7fe):
            n.put(obj+0x3950,struct.pack('<I',item))
            row_va=0x5998e48+(item-0x7ec)*0xb8
            native_enum=struct.unpack_from('<I',image.raw,image.offset(row_va)+0x60)[0]
            selector=n.run(0x2d508c0,native_enum)
            n.hooks[0x1b6eb2c]=lambda n,a,native_enum=native_enum:n.ret(native_enum)
            for p in range(8):
                param[0]=p+1
                fixed=0x7f8<=item<=0x7fd and mask>>(item-0x7f8)&1
                expected=10000+p*100+(selector if fixed or item<0x7f8 else 8)
                assert n.run(0x21b113c,obj)==expected,(mask,hex(item),p,expected)
                counts['eight_parameter_reads']=counts.get('eight_parameter_reads',0)+1
        # Layout uses real native instructions; only widget resolution is an
        # explicit fixture. Every non-visibility widget byte stays unchanged.
        root=DATA+0x6000;n.put(obj+0x90,struct.pack('<Q',root));n.put(obj+8,bytes(4))
        def widget(n,a):n.ret(struct.unpack('<Q',n.read(a[0],8))[0])
        n.hooks.update({0x1ac45ec:widget,0x2120bdc:widget})
        for item in range(0x7ec,0x7fe):
            n.put(obj+0x3950,struct.pack('<I',item))
            for off in (0x80,0x90,0xf0,0x280):n.put(root+off,bytes([0xa5])*0x50)
            n.run(0x21b1434,obj)
            custom=int(0x7f8<=item<=0x7fd and not(mask>>(item-0x7f8)&1))
            for off,want in zip((0x80,0x90,0xf0,0x280),(custom,1-custom,custom,custom)):
                assert n.read(root+off+0x2c,1)==bytes([want]),(mask,hex(item),off)
            counts['native_widget_layout']=counts.get('native_widget_layout',0)+1
        # These eight native setters are unchanged by the recipe. Execute them
        # against the fixed selection model, rather than assuming adjustments
        # still work just because their source bytes were preserved.
        n.hooks.pop(0x1b6eb2c,None)
        def adjustment_log(n,a):
            logs.append((a[0],a[1],a[2],n.word(a[3])));n.ret()
        n.hooks[0x250bb00]=adjustment_log
        for parameter in range(8):
            entry=0x2614e34+parameter*0x260
            assert image.raw[image.offset(entry):image.offset(entry)+4]==bytes.fromhex('fd7bb7a9')
            values_getter=0x287ee88+parameter*0x28
            n.run(values_getter);values_ptr=n.u.reg_read(UC_ARM64_REG_X0)
            n.run(values_getter+20);info_ptr=n.u.reg_read(UC_ARM64_REG_X0)
            n.put(values_ptr,bytes(72));n.put(info_ptr,bytes(432))
            for index in range(18):
                for linked in (False,True):
                    n.put(info_ptr+index*24+8,struct.pack('<Q',DATA+0x8000 if linked else 0))
                    for value in (-9,0,1,3,9):
                        initial=[100+i for i in range(18)];n.put(values_ptr,struct.pack('<18I',*initial))
                        n.put(DATA,struct.pack('<I',selectors[index]));n.put(DATA+0x8000,struct.pack('<I',initial[index]))
                        logs.clear();n.calls.clear();n.run(entry,obj,value)
                        expected=value&0xffffffff;want=initial[:];want[index]=expected
                        assert n.read(values_ptr,72)==struct.pack('<18I',*want),(mask,parameter,index,value,
                            list(struct.unpack('<18I',n.read(values_ptr,72))),logs)
                        assert n.word(DATA+0x8000)==(expected if linked else initial[index])
                        assert logs==[(0x12345678,0x151f+parameter*18+index,
                            DATA+0x8000 if linked else values_ptr+index*4,expected)]
                        counts['eight_parameter_writes']=counts.get('eight_parameter_writes',0)+1
    result=dict(status='PASS',counts=counts,camera_io=False,
        sources=dict(AP=str(image.SOURCE)),
        limitations=['Native external property/lock/widget operations are explicit fixtures.',
            'This is neither a camera boot nor visible screen acceptance.'])
    report.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result,indent=2))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-ap',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();configure(args.source_ap);main(args.report)
