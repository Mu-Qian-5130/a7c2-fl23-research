"""Compile/verify offline native codec against exact private donor instructions.

No USB, firmware writes, patch application, or installer output is available.
Requires explicit private firmware folder and Zig path. Oracle hooks only the
identified domain dependency; this is not a complete AP/CP/ISP emulator.
"""

import argparse,hashlib,json,subprocess,struct
from pathlib import Path
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_SP,UC_ARM64_REG_LR,UC_ARM64_REG_PC
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR

from support.elf import codegen_flags, check_integer_isa, image_loader
from support.memory import MEM, STOP, STACK
EXPECTED='96b41427958c1b412b3e15c5bd9b51e34657ae1e1246344438b8368031ca4859'


def sha(b):return hashlib.sha256(b).hexdigest()
def oracle(image,kind,values):
    u=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    # Original helper bodies, switch-byte table, and their only modeled
    # external dependency. No successful hardware execution is implied.
    for address,size in [(0x31d7000,0x2000),(0x4825000,0x1000),(0x1682000,0x1000),(MEM,0x1000),(STOP,0x1000),(STACK,0x4000)]:u.mem_map(address,size)
    u.mem_write(0x31d7000,image[0x31d7000:0x31d9000]);u.mem_write(0x4825000,image[0x4825000:0x4826000])
    u.reg_write(UC_ARM64_REG_SP,STACK+0x3000);u.reg_write(UC_ARM64_REG_LR,STOP)
    u.mem_write(MEM,bytes([0xa5])*64)
    u.reg_write(UC_ARM64_REG_X0,values[0]);u.reg_write(UC_ARM64_REG_X1,values[1]);u.reg_write(UC_ARM64_REG_X2,MEM)
    def trace(cpu,address,size,user):
        if address==0x1682960:
            if kind!='setting':raise AssertionError('Unexpected dependency')
            cpu.reg_write(UC_ARM64_REG_X0,values[2]);cpu.reg_write(UC_ARM64_REG_PC,cpu.reg_read(UC_ARM64_REG_LR))
    u.hook_add(UC_HOOK_CODE,trace)
    u.emu_start(0x31d7f88 if kind=='setting' else 0x31d8248,STOP,count=500)
    # Failing to reach return is a failure, not an accepted instruction cap.
    assert u.reg_read(UC_ARM64_REG_PC)==STOP
    return bytes(u.mem_read(MEM+8,8 if kind=='setting' else 4))


def execute(u,symbols,arch,kind,values,capacity):
    u.mem_write(MEM,struct.pack('<'+'I'*len(values),*values));u.mem_write(MEM+0x100,bytes([0xa5])*64)
    regs=[UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_SP,UC_ARM64_REG_LR] if arch=='aarch64' else [UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_SP,UC_ARM_REG_LR]
    for reg,value in zip(regs,[MEM,MEM+0x100,capacity,STACK+0x3000,STOP if arch=='aarch64' else STOP|1]):u.reg_write(reg,value)
    u.emu_start(symbols['encode_'+kind],STOP,count=1000)
    from unicorn.arm_const import UC_ARM_REG_PC
    pc=UC_ARM64_REG_PC if arch=='aarch64' else UC_ARM_REG_PC
    assert u.reg_read(pc)==STOP
    status=u.reg_read(regs[0])&0xffffffff
    return status,bytes(u.mem_read(MEM+0x100,64))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--firmware-root',type=Path,required=True);p.add_argument('--zig',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    donor=(a.firmware_root/'a1ii-4.00/components/appFw.so').read_bytes();cp=(a.firmware_root/'a1ii-4.00/components/cpapp-b.bin').read_bytes()
    assert sha(cp)==EXPECTED
    # Pin AP to the input in the prior independently checked call-chain report.
    assert sha(donor)=='d04cc70b41382a147ef5c67d7e86ba706d66526aee17619767b07cbb416b77ca'
    a.output.mkdir(parents=True,exist_ok=True);cases=[]
    for arch,target in [('aarch64','aarch64-linux-gnu'),('thumb','thumb-linux-gnueabi')]:
        dest=a.output/(arch+'-codec.elf')
        command=[str(a.zig),'cc','-target',target,'-O2','-shared','-fPIC','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-ffreestanding','-fno-builtin','-nostdlib','-Wl,--no-undefined','-o',str(dest),str(Path(__file__).with_name('offline_codec.c'))]
        command[4:4]=codegen_flags(arch)
        result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        if result.returncode:raise RuntimeError(result.stderr[-3000:])
        u,symbols=image_loader(dest,arch)
        for domain in range(2):
            for trigger in range(3):
                for duration in range(20):
                    context=0x12345678;values=[duration,trigger,domain,context]
                    expected=struct.pack('<BBHI',5,0,0x4172,context)+oracle(donor,'setting',values)
                    status,actual=execute(u,symbols,arch,'setting',values,16)
                    assert status==16 and actual[:16]==expected and actual[16:]==bytes([0xa5])*48
                    cases.append({'arch':arch,'kind':'setting','domain':domain,'trigger':trigger,'duration':duration})
        for setting in range(2):
            for prohibited in range(2):
                context=0x12345678;values=[setting,prohibited,context]
                expected=struct.pack('<BBHI',5,0,0x4173,context)+oracle(donor,'shooting',values)
                status,actual=execute(u,symbols,arch,'shooting',values,12)
                assert status==12 and actual[:12]==expected and actual[12:]==bytes([0xa5])*52
                cases.append({'arch':arch,'kind':'shooting','setting':setting,'prohibited':prohibited})
        invalid=[('setting',[20,0,0,0],16),('setting',[0,3,0,0],16),('setting',[0,0,2,0],16),('setting',[0,0,0,0],15),('shooting',[2,0,0],12),('shooting',[0,2,0],12),('shooting',[0,0,0],11)]
        for kind,values,cap in invalid:
            status,raw=execute(u,symbols,arch,kind,values,cap)
            assert status==0xffffffea and raw==bytes([0xa5])*64
            cases.append({'arch':arch,'kind':'invalid-'+kind,'output_untouched':True})
    report={'status':'OFFLINE_CODEC_ONLY_NOT_A_PRECAPTURE_IMPLEMENTATION','cases_passed':len(cases),'cases':cases,
        'codec_source_sha256':sha(Path(__file__).with_name('offline_codec.c').read_bytes()),
        'ELF_sha256':{p.name:sha(p.read_bytes()) for p in a.output.glob('*-codec.elf')},
        'donor_AP_sha256':sha(donor),'donor_CP_sha256':sha(cp),'modeled_dependency':'donor0x1682960 return0/1; semanticA7CIIbindingunverified',
        'prototype':'Own C encoder; native AArch64 and Thumb outputs compared against actual donor conversion instructions',
        'not_implemented':['A7CII code placement','AP sender binding','CP configuration/state ownership','CP asynchronous8206scheduler path','image buffer lifecycle','shutter synchronization','physical pre-shutter capture'],
        'camera_IO':False,'firmware_modified':False}
    (a.output/'codec-verification.private.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))
if __name__=='__main__':main()
