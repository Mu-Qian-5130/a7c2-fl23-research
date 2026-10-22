"""Synthetic ABI/layout invariants; no copied native gamma records or USB."""
import struct
import unittest
from looktool import photoformat, photobuild
from test_photoformat import curve

try:
    from keystone import Ks, KS_ARCH_ARM, KS_MODE_THUMB, KS_MODE_V8
except ImportError:
    Ks = None


@unittest.skipIf(Ks is None, 'Optional native assembler unavailable')
class PhotoBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ks = Ks(KS_ARCH_ARM, KS_MODE_THUMB | KS_MODE_V8)
        source = bytearray(0x1101fa0)
        def put(at, text):
            data = bytes(ks.asm(text, addr=at+0x108000)[0])
            source[at:at+len(data)] = data
        for at, text in {0xb27500:'subw r1,r0,#249', 0x323474:'ldr.w r6,[r0,r3,lsl #2]',
            0x6492e4:'push {r4,r5,r6,r7,lr};add r7,sp,#12',
            0x64963c:'push {r4,r5,r6,r7,lr};add r7,sp,#12',0x64836c:'bl 0x751092',
            0x323c64:'bl 0x42b44c',0x9ce8b8:'bl 0x42b44c'}.items():put(at,text)
        for low, high, reg in ((0x32345a,0x323464,'r11'),(0x323d82,0x323d8a,'r1'),
            (0x323dd0,0x323dd8,'r1'),(0x323eb6,0x323eba,'r0'),(0x9cf436,0x9cf43e,'r1')):
            put(low,f'movw {reg},#0x9480');put(high,f'movt {reg},#0x120')
        for at in (0x32325c,0x323278,0x9cf404):put(at,'cmp r0,#50')
        for row in range(50):
            struct.pack_into('<7I',source,0x1209480-0x108000+28*row,
                             *(0x180000+row*0x2000+column*0x400 for column in range(7)))
            for column in range(7):
                at=0x180000+row*0x2000+column*0x400-0x108000
                source[at:at+576]=curve()
        cls.source=bytes(source)
        cls.baseline=photoformat.PhotoBank(curve(),curve(),bytes(576),bytes(64))

    def test_identity_copies_both_complete_ST_rows_and_selects_each_domain(self):
        target,report=photobuild.build(self.source,self.baseline,[{} for _ in range(6)])
        original=self.source[0x1209480-0x108000:0x1209480-0x108000+50*28]
        for slot in range(6):
            pair=struct.unpack_from('<2I',target,photobuild.DATA_FILE+16+slot*8)
            self.assertEqual(pair,(50+2*slot,51+2*slot))
            for domain,row in enumerate((0,10)):
                at=photobuild.TABLE_FILE+(50+2*slot+domain)*28
                self.assertEqual(target[at:at+28],original[row*28:(row+1)*28])
        self.assertEqual(report['gamma_rows'],62)
        self.assertTrue(report['complete_ST_gamma_domains_preserved'])
        self.assertLessEqual(report['code_bytes'],report['code_capacity'])
        self.assertEqual(target[0x20124:0x20154],self.source[0x20124:0x20154])
        self.assertLessEqual(photobuild.DATA_FILE+report['basis_bytes'],0x1101fa0)


if __name__=='__main__':unittest.main()
