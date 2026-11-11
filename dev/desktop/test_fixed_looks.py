"""Fixed presets retain ordinary parameters, slot isolation and reversible bytes."""
import struct
import pytest
from looktool import fixedlooks,fixedlookscode,device_layout,runtimebindings
from test_fl23_native_photo import original_camera_inputs

def test_all_64_native_recipes_reproduce_the_distributed_asset():
    for mask in range(64):
        generated={str(k):v.hex() for k,v in fixedlookscode.code(mask).items()}
        assert generated==fixedlooks.asset()['templates'][mask]
        assert all(len(bytes.fromhex(v))==len(bytes.fromhex(fixedlooks.asset()['before'][k])) for k,v in generated.items())

def test_real_ap_all_slot_combinations_and_exact_restore(original_camera_inputs):
    ap=original_camera_inputs[0]['appFw.so']
    assert fixedlooks.inspect(ap)['mask']==0
    for mask in range(64):
        target=fixedlooks.patch(ap,mask)
        assert fixedlooks.inspect(target)['mask']==mask
        assert fixedlooks.present(target) and fixedlooks.inspect(target)['enabled']
        assert fixedlooks.restore(target)==ap
        phoff=struct.unpack_from('<Q',ap,0x20)[0]
        entry_size,count=struct.unpack_from('<HH',ap,0x36)
        assert target[:phoff+entry_size*count]==ap[:phoff+entry_size*count]
        for slot in range(6):
            row=0x59896e8+slot*0xb8
            assert target[row:row+0x48]==ap[row:row+0x48]
            assert target[row+0x50:row+0xb8]==ap[row+0x50:row+0xb8]
        assert fixedlooks.patch(target,mask)==target

@pytest.mark.parametrize('which',['predicate','setter','mask','image'])
def test_partial_or_mixed_native_generation_is_rejected(original_camera_inputs,which):
    ap=original_camera_inputs[0]['appFw.so'];target=bytearray(fixedlooks.patch(ap,63))
    if which=='predicate':target[0x1b5cd14]^=1
    elif which=='setter':target[0x2614d4c]^=1
    elif which=='image':target[0x59896e8+0x48]^=1
    else:
        raw=fixedlooks.windows(42)[0x21ab9e8];target[0x21ab9e8:0x21ab9e8+len(raw)]=raw
    with pytest.raises(ValueError):fixedlooks.inspect(bytes(target))
    with pytest.raises(ValueError):fixedlooks.patch(bytes(target),1)

def test_base_sync_rejects_a_non_ST_value_for_fixed_slot(original_camera_inputs):
    ap=fixedlooks.patch(original_camera_inputs[0]['appFw.so'],2)
    key=0x02cf0cd2
    with pytest.raises(ValueError,match='fixed'):runtimebindings.targets(ap,{key:b'\x08'})
    assert runtimebindings.targets(ap,{key:b'\0'})[0]['value']==0
    assert runtimebindings.targets(ap,{0x02cf0cd0:b'\x08'})[0]['value']==8

def test_converter_mask_updates_and_slot_deactivation_keep_fixed_state(original_camera_inputs):
    ap,cp=(original_camera_inputs[0][name] for name in ('appFw.so','cpapp-b.bin'))
    installed=device_layout.replace(ap,cp,{2:bytes(1215)},hash_checks=False,transitions=False)[2]
    fixed=fixedlooks.patch(installed['appFw.so'],2)
    combined=device_layout.replace(fixed,installed['cpapp-b.bin'],{6:bytes([1])*1215},hash_checks=False,transitions=False)[2]
    assert fixedlooks.inspect(combined['appFw.so'])['mask']==34
    assert device_layout.structural_ap(combined['appFw.so'])['mask']==34
    assert combined['appFw.so'][0x59896e8+0x48:0x59896e8+0x50]==ap[0x59896e8+0x48:0x59896e8+0x50]
    mixed=bytearray(combined['appFw.so']);mixed[0x35287f0:0x3528874]=bytes.fromhex(device_layout.runtime()['ap_templates'][2])
    with pytest.raises(ValueError,match='mask'):device_layout.structural_ap(bytes(mixed))
    restored=device_layout.deactivate(combined['appFw.so'],combined['cpapp-b.bin'],6,
        bytes(1215),hash_checks=False,transitions=False)[2]
    assert fixedlooks.inspect(restored['appFw.so'])['mask']==2
    empty=device_layout.deactivate(restored['appFw.so'],restored['cpapp-b.bin'],2,
        bytes(1215),hash_checks=False,transitions=False)[2]
    assert fixedlooks.inspect(empty['appFw.so'])['mask']==0
    assert fixedlooks.inspect(empty['appFw.so'])['enabled']
    reimport=device_layout.replace(empty['appFw.so'],empty['cpapp-b.bin'],{3:bytes(1215)},hash_checks=False,transitions=False)[2]
    assert fixedlooks.inspect(reimport['appFw.so'])['mask']==4

def test_native_sync_guards_cover_helpers_within_worker_buffer(original_camera_inputs,tmp_path,monkeypatch):
    ap=fixedlooks.patch(original_camera_inputs[0]['appFw.so'],63)
    monkeypatch.setattr(runtimebindings,'compile_worker',lambda *args,**kwargs:None)
    runtimebindings.build(ap,runtimebindings.targets(ap,{0x02cf0cd0:b'\0'}),tmp_path)
    header=(tmp_path/'look-bindings.private.h').read_text()
    assert '{0x2614d20UL,76,' in header
    assert '{0x21b14b4UL,16,' in header
    import re
    assert all(int(size)<=128 for size in re.findall(r'\{0x[0-9a-f]+UL,(\d+),code_',header))
