import builtins
import copy
import struct
import unittest
from unittest.mock import patch
from looktool import editrecipe,photobasis,photobuild,photofull,photoio,photoformat
import test_photoio


class FullNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_photoio.PhotoIOTests.setUpClass()
        cls.source=test_photoio.PhotoIOTests.source;cls.bank=test_photoio.PhotoIOTests.bank
        cls.legacy=test_photoio.PhotoIOTests.delta
        curve=cls.bank.regular_curve
        x=photoformat.gamma_coordinates(curve)
        y=list(photoformat.gamma_values(curve))[:128]
        base=dict(matrix_780f_hex=bytes(276).hex(),cc1_direct_raw=[0]*8,gamma_7806_y=[v*2 for v in y])
        fitted=copy.deepcopy(base);fitted['cc1_direct_raw'][4]=8
        raw=bytearray(276);struct.pack_into('<h',raw,26,-40);fitted['matrix_780f_hex']=raw.hex()
        cls.stage=editrecipe.from_fit(fitted,base,[v*32 for v in (*x[:127],x[-1])],'a'*64)

    def test_full_install_uses_template_without_an_assembler_and_roundtrips(self):
        original=builtins.__import__
        def restricted(name,*args,**kwargs):
            if name.startswith('keystone'):raise AssertionError('Production path must not assemble')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',restricted):
            result=photoio.update(self.source,{4:self.stage},self.bank,allocation_proved=True)
            self.assertEqual(photoio.inspect(result)['mask'],8)
        self.assertEqual(photoio.slot_delta(result,4,self.bank),self.stage)
        self.assertEqual(photoio.slot_bytes(result,4),editrecipe.pack(self.stage))
        self.assertEqual(result[0x20124:0x20154],self.source[0x20124:0x20154])
        self.assertEqual(len(result),len(self.source))

    def test_legacy_migration_slot_replace_and_clear_keep_other_data(self):
        old=photoio.update(self.source,{2:self.legacy},self.bank,allocation_proved=True)
        legacy_bytes=photoio.slot_bytes(old,2)
        full=photoio.update(old,{4:self.stage},self.bank)
        self.assertEqual(photoio.slot_bytes(full,2),legacy_bytes)
        changed=photoio.update(full,{6:self.stage,4:None},self.bank)
        self.assertEqual(photoio.slot_bytes(changed,2),legacy_bytes)
        self.assertIsNone(photoio.slot_delta(changed,4,self.bank))
        self.assertEqual(photoio.slot_delta(changed,6,self.bank),self.stage)

    def test_unknown_prefix_code_and_changed_body_basis_are_rejected(self):
        source=bytearray(self.source);source[photofull.PREFIX_FILE]=1
        with self.assertRaisesRegex(ValueError,'prefix is occupied'):
            photoio.update(bytes(source),{1:self.stage},self.bank,allocation_proved=True)
        full=photoio.update(self.source,{1:self.stage},self.bank,allocation_proved=True)
        for at in (photofull.PREFIX_FILE+3000,photobuild.CODE_FILE+20):
            altered=bytearray(full);altered[at]^=1
            with self.assertRaises(ValueError):photoio.inspect(bytes(altered))
        other=photobasis.apply(self.bank,tone=[1,0,0])
        with self.assertRaisesRegex(ValueError,'Fresh native ST'):
            photoio.update(full,{1:self.stage},other)

    def test_no_silent_gamma_or_gain_rounding(self):
        for field,index in [('gamma_7806_y',1),('cc1_direct_raw',4)]:
            value=copy.deepcopy(self.stage);value['fitted'][field][index]+=1
            with self.assertRaisesRegex(ValueError,'losslessly'):
                photoio.update(self.source,{1:value},self.bank,allocation_proved=True)

    def test_post_reload_permits_only_other_slot_updates(self):
        from looktool import device_layout,six
        source=bytearray(self.source);raw=six.prefix([bytes(1215)]*6)
        source[six.TABLE_FILE:six.TABLE_FILE+len(raw)]=raw
        before=photoio.update(bytes(source),{1:self.stage,2:self.legacy},self.bank,allocation_proved=True)
        after=photoio.update(before,{2:None,6:self.stage},self.bank)
        self.assertTrue(device_layout.same_selected_programs({'appFw.so':b'unchanged','cpapp-b.bin':before},
            {'appFw.so':b'unchanged','cpapp-b.bin':after},1))
        changed=photoio.update(after,{1:None},self.bank)
        self.assertFalse(device_layout.same_selected_programs({'appFw.so':b'unchanged','cpapp-b.bin':before},
            {'appFw.so':b'unchanged','cpapp-b.bin':changed},1))

    def native_slot_pointer(self,cp,slot):
        from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
        from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_PC
        base=photobuild.BASE;stack=0x30010000;stop=0x31000000
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB);u.mem_map(base,(len(cp)+4095)&~4095);u.mem_write(base,cp)
        u.mem_map(stack-65536,131072);u.mem_map(stop,4096)
        u.reg_write(UC_ARM_REG_R0,slot-1);u.reg_write(UC_ARM_REG_SP,stack);u.reg_write(UC_ARM_REG_LR,stop|1)
        u.emu_start(photofull.template()['labels']['check_slot']['address']|1,stop,count=200000)
        self.assertEqual(u.reg_read(UC_ARM_REG_PC),stop);self.assertEqual(u.reg_read(UC_ARM_REG_SP),stack)
        return u.reg_read(UC_ARM_REG_R0)

    def test_interrupted_prefix_relocation_never_activates_an_old_gamma_pointer(self):
        before=photofull.update(self.source,{i:self.legacy for i in range(1,7)},self.bank,allocation_proved=True)
        after=photoio.update(before,{1:self.stage},self.bank)
        mixed=bytearray(before);mixed[photofull.PREFIX_FILE:photofull.PREFIX_END]=after[photofull.PREFIX_FILE:photofull.PREFIX_END]
        for slot in range(2,7):
            self.assertNotEqual(self.native_slot_pointer(before,slot),0)
            self.assertNotEqual(self.native_slot_pointer(after,slot),0)
            self.assertEqual(self.native_slot_pointer(bytes(mixed),slot),0)

    def test_each_gamma_pointer_and_activation_mask_is_part_of_the_native_guard(self):
        cp=photoio.update(self.source,{3:self.stage},self.bank,allocation_proved=True)
        self.assertNotEqual(self.native_slot_pointer(cp,3),0)
        for pointer in range(14):
            bad=bytearray(cp);at=photobuild.TABLE_FILE+(50+4)*28+pointer*4
            bad[at]^=4
            self.assertEqual(self.native_slot_pointer(bytes(bad),3),0)
        bad=bytearray(cp);bad[photobuild.DATA_FILE+8]^=1
        self.assertEqual(self.native_slot_pointer(bytes(bad),3),0)


if __name__=='__main__':unittest.main()
