"""Instruction tests with controlled contexts; no camera or RTOS emulation."""
import struct
import unittest

from unicorn import Uc,UC_ARCH_ARM,UC_ARCH_ARM64,UC_MODE_THUMB,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm_const import *
from unicorn.arm64_const import *
from looktool.hooks import assembler,helper_code,ap_converter,HELPER


class HookTests(unittest.TestCase):
    def test_six_selectors_require_st_and_preserve_native_modes(self):
        u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(0x3528000,4096);u.mem_write(0x3528804,ap_converter())
        u.mem_map(0x30000000,4096);u.mem_map(0x31000000,4096)
        error=[]
        def hook(cpu,at,size,_):
            if at==0x3528874:error.append(True);cpu.emu_stop()
        u.hook_add(UC_HOOK_CODE,hook)
        modes=[0,3,2,1,16,15,17,18,5,13,19,20]
        cases=0
        for selector in [*range(32),65535,0xffffffff]:
            for binding in [*range(12),12,255,0xffffffff]:
                error.clear();u.mem_write(0x30000000,b'\xa5')
                for reg,value in [(UC_ARM64_REG_X0,selector),(UC_ARM64_REG_X1,binding),(UC_ARM64_REG_X2,0x30000000),(UC_ARM64_REG_LR,0x31000000)]:u.reg_write(reg,value)
                u.emu_start(0x3528804,0x31000000,count=100)
                if binding>11:self.assertTrue(error)
                else:
                    expected=249+selector-10 if binding==0 and 10<=selector<=15 else modes[binding]
                    self.assertEqual(bytes(u.mem_read(0x30000000,1)),bytes([expected]))
                    self.assertFalse(error)
                cases+=1
        self.assertEqual(cases,510)

    def test_helper_six_markers_storage_availability_and_legacy(self):
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(HELPER&~4095,4096);u.mem_write(HELPER,helper_code(assembler()))
        u.mem_map(0x30000000,0x20000);u.mem_map(0x31000000,4096)
        root,env,state,output,work=0x30001000,0x30002000,0x30004000,0x30003000,0x30005000
        u.mem_write(0x30000000,struct.pack('<II',root,env));u.mem_write(output+12,struct.pack('<I',work))
        cases=0
        for marker in range(256):
            for flag in (0,1,2,255):
                for direct in (0,1,2):
                    for bank in (0,0x30009000):
                        u.mem_write(root+1,bytes([flag]));u.mem_write(root+0x2e,bytes([marker]));u.mem_write(env+6,bytes([direct]));u.mem_write(work+0x6b0,struct.pack('<I',bank))
                        for reg,value in [(UC_ARM_REG_R0,7),(UC_ARM_REG_R1,9),(UC_ARM_REG_R2,0x3000b000),(UC_ARM_REG_R5,state),
                                          (UC_ARM_REG_R8,output),(UC_ARM_REG_R9,0x30000000),(UC_ARM_REG_R10,root),
                                          (UC_ARM_REG_SP,0x3001f000),(UC_ARM_REG_LR,0x31000001)]:u.reg_write(reg,value)
                        u.emu_start(HELPER|1,0x31000000,count=200)
                        ptr,kind,transform=struct.unpack('<IBB',u.mem_read(state+0x184,6))
                        selected=249<=marker<=254 and ((flag==1 and direct<=1) or (flag==0 and (direct==1 or (direct==0 and bank!=0))))
                        self.assertEqual((ptr,kind,transform),(0x110000+(marker-249)*1215,1,2) if selected else (0x3000b000,9,7))
                        self.assertEqual(u.reg_read(UC_ARM_REG_PC),0x31000000)
                        self.assertEqual(u.reg_read(UC_ARM_REG_SP),0x3001f000)
                        cases+=1
        self.assertEqual(cases,6144)


if __name__=='__main__':unittest.main()
