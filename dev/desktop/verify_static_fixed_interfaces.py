"""Check relocated host interfaces and existing API file results without I/O."""
import argparse
import json
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'src/looks'), str(ROOT/'src/vertical')]
from desktopapp import iconresources, menuicons, sshupdates
from looktool import (bundle, device_layout, direct, editrecipe, fixedbank,
                      fixedbankcode, lookfile, nameworker, photoformat, photoio, resources)
from looktool.devicesession import modules
from looktool.fixedregion import SOURCE_DATA_START
from verticaltool import imagebank, nativeportrait


def artwork(before, after, expected, slot, name):
    group = int(name[6:8])
    old, new, wanted = [imagebank.inspect(raw, group) for raw in (before, after, expected)]
    chosen = ({0x6c5+slot-1, 0x8ef+13*(slot-1), 0x181a+13*(slot-1)}
              if group == 0 else {0x13a3+slot-1})
    assert (old['count'], old['unused'], set(old['records'])) == (new['count'], new['unused'], set(new['records']))
    spans = []
    for index, a in old['records'].items():
        c = new['records'][index]
        assert after[a['start']:a['start']+a['size']] == before[a['start']:a['start']+a['size']]
        if index in chosen:
            e = wanted['records'][index]
            n = 3840 if a['width'] == 58 else 5600
            assert menuicons.decode(after[c['start']:c['start']+c['size']], n) == menuicons.decode(expected[e['start']:e['start']+e['size']], n)
            spans.append((a['at']+12, a['at']+20))
        else:
            assert a == c
    start = 0
    for lo, hi in sorted(spans):
        assert before[start:lo] == after[start:lo]
        start = hi
    assert before[start:] == after[start:len(before)]
    if '_23_' in name:
        assert nativeportrait.owned(after)


def rejected(call, text):
    try:
        call()
    except ValueError as exc:
        assert text in str(exc), str(exc)
    else:
        raise AssertionError('Expected refusal: '+text)


def main(a):
    a.output.mkdir(parents=True, exist_ok=False)
    report = dict(status='RUNNING', camera_io=False, system_VM=False,
                  tests=[], hot_reload=False, new_hashes=False)
    def save():
        (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    def passed(name, **details):
        report['tests'].append(dict(name=name, **details))
        save()
        print('STATIC_INTERFACE_PASSED', name, flush=True)
    try:
        _, current, _, manifest = sshupdates.baseline(a.baseline)
        cp, ap = current['cpapp-b.bin'], current['appFw.so']
        image = fixedbank.extract_cp(cp)
        parsed = fixedbank.parse(image)
        labels = device_layout.structural(ap, cp)['label_ids']
        records = modules()[1].backup_records(current['settings-ram.bin'])
        for chip, fields in enumerate(manifest['wanted']):
            for key, value in fields.items():
                key = int(key)
                records[chip][key] = records[chip][key]._replace(data=bytes.fromhex(value))
        doc = lookfile.read(a.look)
        full = lookfile.read(a.icon_look)
        names = nameworker.filenames()
        api_report = json.loads((a.api_results/'linux-result.json').read_text(encoding='utf-8'))
        assert api_report['status'] == 'PASSED'
        plan = json.loads((a.api_results/'plan.private.json').read_text(encoding='utf-8'))
        for case in plan['cases']:
            slot, kind = case['slot'], case['format']
            root = a.api_results/(kind+'-'+str(slot))
            for n in names:
                before = current['resources/'+n]
                assert (root/'usr/share/app'/n).read_bytes() == resources.rename(before, {slot:full['name']}, labels)[0], (kind, slot, n)
            for n in iconresources.NAMES:
                before = current['images/'+n]
                expected = menuicons.replace(before, {slot:full['menu_icon']}, group=int(n[6:8]), all_views=True)[0]
                artwork(before, (root/'usr/share/app'/n).read_bytes(), expected, slot, n)
            actual = (root/'cp/cpapp-b.bin').read_bytes()
            assert device_layout.tables(actual)[slot-1] == lookfile.writer_document(full)
            stage = photoio.slot_delta(actual, slot, photoformat.PhotoBank.unpack(parsed['basis']))
            if kind == 'full':
                assert editrecipe.pack(stage) == editrecipe.pack(full['edit_native'])
                assert photoio.slot_bytes(actual, slot) == editrecipe.pack(full['edit_native'])
            else:
                assert stage is None and photoio.slot_bytes(actual, slot) is None
            passed('API-artwork-and-readback-'+kind+'-'+str(slot), names=len(names), icon_banks=4)

        bank = photoformat.PhotoBank.unpack(parsed['basis'])
        usb_targets = {}
        for slot in range(1, 7):
            target, wanted, rename = direct.plan(current, records, 'look_import', slot=slot, look=doc)
            expected = fixedbank.replace_cp(cp, fixedbank.update_documents(cp, image, {slot:doc}))
            assert target['cpapp-b.bin'] == expected, ('USB unexpected CP edit', slot)
            assert target['appFw.so'] == ap
            assert target['cpapp-b.bin'][:SOURCE_DATA_START] == cp[:SOURCE_DATA_START]
            assert target['cpapp-b.bin'][SOURCE_DATA_START+len(image):] == cp[SOURCE_DATA_START+len(image):]
            entries = fixedbank.parse(fixedbank.extract_cp(expected))['entries']
            assert all(entries[i] == parsed['entries'][i] for i in range(6) if i != slot-1)
            assert device_layout.tables(expected)[slot-1] == lookfile.writer_document(doc)
            assert photoio.inspect(expected, bank)['revision'] == 'cp-fixed-v1'
            assert photoio.slot_bytes(expected, slot) == editrecipe.pack(doc['edit_native'])
            assert editrecipe.pack(photoio.slot_delta(expected, slot, bank)) == editrecipe.pack(doc['edit_native'])
            usb_targets[slot] = target
            passed('USB-pure-plan-slot-'+str(slot), AP_unchanged=True, CP_only_new_source=True)
        options, selected = bundle.documents(dict(looks=[dict(slot=s, path=str(a.look)) for s in range(1,7)], fl23=False, sound=False))
        target, wanted, rename = bundle.plan(current, records, options, selected)
        expected = fixedbank.replace_cp(cp, fixedbank.update_documents(cp, image, {s:doc for s in range(1,7)}))
        assert target['cpapp-b.bin'] == expected and target['appFw.so'] == ap
        passed('USB-batch-six', AP_unchanged=True, CP_only_new_source=True)
        assert device_layout.same_selected_programs(current, usb_targets[6], 1)
        assert not device_layout.same_selected_programs(current, usb_targets[1], 1)
        broken = dict(current)
        raw = bytearray(cp);raw[0x50000] ^= 1;broken['cpapp-b.bin'] = bytes(raw)
        assert not device_layout.same_selected_programs(current, broken, 1)
        rejected(lambda: direct.plan(current, records, 'factory_reset'), 'reflashing')
        rejected(lambda: direct.plan(current, records, 'slot_default', slot=1), 'reflashing')
        rejected(lambda: device_layout.deactivate(ap, cp, 1, bytes(1296), transitions=False), 'reflashing')
        rejected(lambda: device_layout.replace(ap, cp, {1:lookfile.writer_document(doc)}), 'byte-only')
        passed('fixed-recovery-and-selected-slot-contracts')
        # Simulate an independent reviewed native pointer-row change; only the
        # relocated native rows should follow it, with custom records unchanged.
        raw = bytearray(cp);at = fixedbank.NATIVE_TABLE-0x108000
        raw[at+48*28:at+49*28] = cp[at+49*28:at+50*28]
        refreshed = photoio.refresh_gamma_table(bytes(raw))
        after = fixedbank.parse(fixedbank.extract_cp(refreshed))
        assert after['entries'] == parsed['entries'] and after['basis'] == parsed['basis']
        assert after['native'] == bytes(raw[at:at+1400])
        assert refreshed[0xa000:0x20000] == cp[0xa000:0x20000]
        assert refreshed[at:at+1400] == bytes(raw[at:at+1400])
        passed('native-row-refresh-without-old-prefix')
        operations = [dict(slot=s, path=str(a.icon_look)) for s in range(1,7)]
        package = a.output/'ssh-six'
        state = sshupdates.compile_look(a.baseline, operations, package)
        rows = state['rows'];assert rows[-1]['path'] == '/cp/cpapp-b.bin'
        actual = {r['path']:(package/r['after']).read_bytes() for r in rows}
        assert actual['/cp/cpapp-b.bin'] == expected
        assert '/usr/lib/appFw.so' not in actual
        title_map = {s:full['name'] for s in range(1,7)}
        for n in names:
            target_path = '/usr/share/app/'+n
            assert actual.get(target_path, current['resources/'+n]) == resources.rename(current['resources/'+n], title_map, labels)[0]
        expected_images = iconresources.replace({n:current['images/'+n] for n in iconresources.NAMES}, {s:full['menu_icon'] for s in range(1,7)})
        for n, data in expected_images.items():
            assert actual.get('/usr/share/app/'+n, current['images/'+n]) == data
        assert state['reload_required'] and state['look_storage'] == 'cp-fixed-v1'
        rejected(lambda: sshupdates.compile_look(a.baseline, [dict(slot=1,action='restore')], a.output/'forbidden-reset'), '重新生成固件')
        passed('SSH-six-source-names-icons-order', names=len(names), icon_banks=4, CP_last=True)
        report['status'] = 'PASSED';save()
    except BaseException:
        report.update(status='FAILED', error=traceback.format_exc());save();raise


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','look','icon-look','api-results','output'):
        p.add_argument('--'+name, type=Path, required=True)
    main(p.parse_args())
