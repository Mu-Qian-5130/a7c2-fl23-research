"""FL23 PR assets and real custom-look/FL23 installation order; no USB."""
import copy
import os
from pathlib import Path
import struct

import pytest

from desktopapp.worker import setup_runtime
setup_runtime()
from looktool import bundle, device_layout, direct, firmware, lookfile, nameworker
from looktool import photobasis, photobuild, photoformat, photoio
from looktool.devicesession import modules
from test_checkpoint import stock_names


def test_gui_uses_both_merged_pr_color_and_gamma_assets():
    core=modules()[1]
    legacy=core.BASE.parent/'fl23/assets'
    for name in ('patches.json','colors.json','fx2_fl23_donor.json'):
        assert core.read_json(core.BASE/'assets'/name)==core.read_json(legacy/name)
    for row in core.read_json(core.BASE/'assets/colors.json'):
        core.colour_record(row)
    block=next(new for at,old,new,legacy in device_layout.fl23_native_windows() if at==0x1100b80)
    assert struct.unpack_from('<II',block,0xe78+19*8)==(48,46)
    assert struct.unpack_from('<II',block,0xe78+20*8)==(49,47)
    helper=next(new for at,old,new,legacy in device_layout.fl23_native_windows() if at==0x138832)
    assert helper==bytes.fromhex('00bf'*7+'49f6f811c0f22011704700bf')


@pytest.fixture(scope='module')
def original_camera_inputs():
    root=os.environ.get('A7C2_FIRMWARE_ROOT')
    if not root:
        pytest.skip('Optional private original firmware; never reads a camera')
    core=modules()[1]
    folder=Path(root)/'a7c2-2.01/components'
    programs={name:(folder/name).read_bytes() for name in core.PROGRAMS}
    records=core.backup_records((folder/'CX89700_ALLLANG.bin').read_bytes())
    return programs,records


@pytest.fixture(scope='module')
def looks_first(original_camera_inputs,tmp_path_factory):
    programs,records=original_camera_inputs
    current=dict(programs,**{'resources/'+n:stock_names() for n in nameworker.filenames()})
    bootstrap=device_layout.replace(programs['appFw.so'],programs['cpapp-b.bin'],
        {1:bytes(1215)},hash_checks=False,transitions=False)[2]['cpapp-b.bin']
    bank=photoformat.extract_bank(bootstrap,records[1][0x02a40001].data,
        records[1][0x02a4000d].data,gamma_table_va=0x1209480,
        regular_row=0,still_row=10,color_parameter=0)[0]
    root=tmp_path_factory.mktemp('fl23-native-looks')
    selected=[]
    for slot in range(1,7):
        delta=photobasis.pack(bank,tone=[16+slot,0,0])[1]
        document=lookfile.write(root/f'{slot}.a7look',f'Look {slot}',bytes([slot])*1215,
            method='offline regression fixture',attribution='test',native_photo=delta)
        selected.append(dict(slot=slot,name=document['name'],document=document))
    target,wanted,_=bundle.plan(current,records,dict(fl23=False,sound=False),selected)
    working=copy.deepcopy(records)
    for chip in (0,1):
        for key,value in wanted[chip].items():
            working[chip][key]=working[chip][key]._replace(data=value)
    return current,records,target,working,selected


def assert_active_fl23(cp):
    original=0x1209480-photobuild.BASE
    for row in (46,47,48,49):
        assert cp[photobuild.TABLE_FILE+row*28:photobuild.TABLE_FILE+(row+1)*28]==cp[original+row*28:original+(row+1)*28]
    assert photoio.inspect(cp)['mask']==63


def test_enabling_fl23_after_six_looks_matches_fl23_first(looks_first):
    current,records,installed,working,selected=looks_first
    target,wanted,_=direct.plan(installed,working,'fl23_enable')
    combined,combined_wanted,_=bundle.plan(current,records,dict(fl23=True,sound=False),selected)
    assert target==combined
    for key,value in wanted[1].items():
        assert value==combined_wanted[1][key]
    assert_active_fl23(target['cpapp-b.bin'])
    assert device_layout.tables(target['cpapp-b.bin'])==device_layout.tables(installed['cpapp-b.bin'])
    for slot in range(1,7):
        assert photoio.slot_bytes(target['cpapp-b.bin'],slot)==photoio.slot_bytes(installed['cpapp-b.bin'],slot)


def test_reenable_repairs_current_pr_bytes_with_a_stale_active_table(looks_first):
    _,_,installed,working,_=looks_first
    target,_,_=direct.plan(installed,working,'fl23_enable')
    stale=bytearray(target['cpapp-b.bin'])
    start=photobuild.TABLE_FILE
    stale[start:start+50*28]=installed['cpapp-b.bin'][start:start+50*28]
    with pytest.raises(ValueError,match='runtime bytes conflict'):
        photoio.inspect(bytes(stale))
    source=dict(target,**{'cpapp-b.bin':bytes(stale)})
    repaired,_,_=direct.plan(source,working,'fl23_enable')
    assert repaired==target
    assert_active_fl23(repaired['cpapp-b.bin'])
    import compat
    programs={n:source[n] for n in modules()[1].PROGRAMS}
    _,enabled,after,forward,reverse=compat.plan(programs['appFw.so'],programs['cpapp-b.bin'])
    assert not enabled  # Native FL23 bytes match, but the active table needs repair.
    assert firmware.apply(programs,forward)==after
    assert firmware.apply(after,reverse)==programs
    assert compat.plan(after['appFw.so'],after['cpapp-b.bin'],transitions=False)[1]


def test_native_fl23_and_custom_base_fl23_use_the_same_ap_mode(looks_first):
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_W0,UC_ARM64_REG_W1,UC_ARM64_REG_X2,UC_ARM64_REG_X30
    current,records,installed,working,_=looks_first
    standalone,wanted,_=direct.plan(current,records,'fl23_enable')
    combined,_,_=direct.plan(installed,working,'fl23_enable')
    assert wanted[0]=={0x02cf1287:b'\x0a',0x02cf1289:b'\x0b'}
    for target in (standalone,combined):
        ap=target['appFw.so']
        cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        cpu.mem_map(0x3528000,4096);cpu.mem_write(0x35287f0,ap[0x35287f0:0x3528880])
        cpu.mem_map(0x4c7c000,4096);cpu.mem_write(0x4c7cf7c,ap[0x4c7cf7c:0x4c7cf88])
        cpu.mem_map(0x30000000,4096);cpu.mem_map(0x31000000,4096)
        for selector in (10,15,17,18):
            for binding,mode in ((10,19),(11,20)):
                for register,value in ((UC_ARM64_REG_W0,selector),(UC_ARM64_REG_W1,binding),
                        (UC_ARM64_REG_X2,0x30000000),(UC_ARM64_REG_X30,0x31000000)):
                    cpu.reg_write(register,value)
                cpu.emu_start(0x35287f0,0x31000000,count=100)
                assert bytes(cpu.mem_read(0x30000000,1))==bytes([mode])


def test_preview_and_photo_constructors_use_the_updated_fl23_records(looks_first):
    from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
    from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R4,UC_ARM_REG_R11,UC_ARM_REG_LR
    current,records,installed,working,_=looks_first
    standalone,_,_=direct.plan(current,records,'fl23_enable')
    combined,_,_=direct.plan(installed,working,'fl23_enable')
    for target,relocated in ((standalone,False),(combined,True)):
        cp=target['cpapp-b.bin']
        cpu=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        cpu.mem_map(photobuild.BASE,(len(cp)+4095)&~4095);cpu.mem_write(photobuild.BASE,cp)
        cpu.mem_map(0x31000000,4096)
        # Every gamma-table constructor edited by the two engines, including
        # the separate 0x9cf... path, must resolve to the table we inspect.
        table=photobuild.TABLE_VA if relocated else 0x1209480
        for low,high,register in ((0x32345a,0x323464,UC_ARM_REG_R11),
                (0x323d82,0x323d8a,UC_ARM_REG_R1),(0x323dd0,0x323dd8,UC_ARM_REG_R1),
                (0x323eb6,0x323eba,UC_ARM_REG_R0),(0x9cf436,0x9cf43e,UC_ARM_REG_R1)):
            cpu.reg_write(register,0)
            for at in (low,high):
                cpu.emu_start((photobuild.BASE+at)|1,photobuild.BASE+at+4,count=1)
            assert cpu.reg_read(register)==table
        entry=photobuild.BASE+(0xb27500 if relocated else 0x138832)
        for mode,photo_row,movie_row,photo_record in ((19,48,46,0),(20,49,47,2)):
            for domain,row,index in ((0,photo_row,photo_record),(1,movie_row,photo_record+1)):
                cpu.reg_write(UC_ARM_REG_R0,mode);cpu.reg_write(UC_ARM_REG_R4,domain)
                cpu.reg_write(UC_ARM_REG_LR,0x31000001)
                cpu.emu_start(entry|1,0x31000000,count=100)
                assert cpu.reg_read(UC_ARM_REG_R0)==mode
                modes=cpu.reg_read(UC_ARM_REG_R1)
                actual_row=struct.unpack('<I',cpu.mem_read(modes+mode*8+domain*4,4))[0]
                assert actual_row==row
                pointer=struct.unpack('<I',cpu.mem_read(table+row*28+6*4,4))[0]
                assert pointer==0x1208b80+index*576
                curve=bytes(cpu.mem_read(pointer,576))
                assert struct.unpack_from('<I',curve,0x21c)[0]==(5 if domain==0 else 6)


def test_real_write_plan_contains_active_rows_and_both_saved_bindings(looks_first,tmp_path):
    from types import SimpleNamespace
    from looktool import checkpointworker
    _,_,installed,working,_=looks_first
    target,wanted,_=direct.plan(installed,working,'fl23_enable')
    camera=SimpleNamespace(records=lambda raw:working)
    prepared=direct.DirectJob(tmp_path/'settings').settings(camera,
        {'settings-ram.bin':b'ram','settings-saved.bin':b'saved'},wanted)
    for fields in prepared[1:3]:
        assert fields[0][0x02cf1287].data==b'\x0a'
        assert fields[0][0x02cf1289].data==b'\x0b'
        for key,value in wanted[1].items():
            assert fields[1][key].data==value
    changes=list(checkpointworker.differences(installed['cpapp-b.bin'],target['cpapp-b.bin']))
    for row in (46,47,48,49):
        start=photobuild.TABLE_FILE+row*28
        assert any(at<start+28 and start<at+len(old) for at,old,new in changes)
    # Compile the actual AArch64 program workers, without executing them.
    builds=checkpointworker.build_programs(installed,target,tmp_path/'workers')
    assert builds and all(Path(build['path']).read_bytes().startswith(b'\x7fELF') for build in builds)

