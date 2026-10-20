"""Original AP codec fixture with one explicit domain-dependency model."""
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)
from .memory import MEM, STOP, STACK

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


