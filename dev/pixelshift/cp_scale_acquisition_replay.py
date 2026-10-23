"""Connect native cached-state reduction/recording to scale/vector arithmetic.

Original reduction slice and complete acquisition callback create every sample
halfword; the host never populates the measurement sample array or scale bytes.
Cached raw words, coefficients, collector selection and call ordering are
synthetic fixtures. This is not real feedback acquisition, a full adjustment
script, normal startup, settling, exposure or a device calibration operation.
The calculation's local record update and native return execute; restoring the
paused emulator caller context afterward is an explicit harness boundary.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_scale_calculation_replay import calculate, profile as calculation_profile
from cp_phase_pair_replay import pair_sequence
from cp_serial_replay import literals


@lru_cache(maxsize=2)
def profile(directory):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
    data, c = calculation_profile(directory)
    target = c['entry'] == 0x13ca30
    p = dict(reduce=0x41ba66 if target else 0x41bc7e,
             reduce_end=0x41bab6 if target else 0x41bcce,
             collect=0xab16d2 if target else 0xab1530,
             collect_end=0xab17aa if target else 0xab1608,
             cached_state=c['measurements']+0x100)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    code = list(md.disasm(data[p['collect']-0x108000:p['collect']-0x108000+0xd8], p['collect']))
    p['getter'] = int(next(ins.op_str for ins in code if ins.mnemonic == 'bl').lstrip('#'), 0)
    getter = list(md.disasm(data[p['getter']-0x108000:p['getter']-0x108000+12], p['getter']))
    p['getter_data'] = next(value for reg, value in literals(getter) if reg == 'r0')
    return data, c, p


def acquire(cpu, directory, c, case, baseline):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, expected_profile, p = profile(directory)
    if c['measurements'] != expected_profile['measurements']:
        raise ValueError('Acquisition and calculation do not share the native record')
    source = p['cached_state']
    metadata = (p['getter_data'], c['disabled'], c['disabled']-10, c['disabled']-9)
    for at, length in [(source, 256), (p['getter_data'], 64)] + [(at, 1) for at in metadata]:
        for page in range(at & ~4095, (at+length+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    finish, stack = 0x3001e000, 0x3001f000
    # Branch selector and collector bookkeeping are independent fixture inputs.
    cpu.mem_write(source+0x76, b'\1')
    cpu.mem_write(c['disabled'], b'\0')
    cpu.mem_write(c['disabled']-10, b'\0')
    cpu.mem_write(c['disabled']-9, b'\0')
    count = case['count']
    phase, sample_writes, reduction_calls, collector_calls = 'reduce', [], 0, 0
    start = c['measurements']+0x80
    expected_samples = []
    for delta in ((case['x'], case['y']), tuple(case['z'])):
        for _ in range(count):
            expected_samples += [baseline, (baseline[0]+delta[0], baseline[1]+delta[1])]

    def code_hook(uc, at, length, unused):
        ranges = [(p['reduce'], p['reduce_end'])] if phase == 'reduce' else [
            (p['collect'], p['collect_end']), (p['getter'], p['getter']+10)]
        if not any(lo <= at and at+length <= hi for lo, hi in ranges):
            raise ValueError('Native acquisition entered an unresolved dependency: ' + hex(at))

    def write_hook(uc, access, at, length, value, unused):
        if stack-1024 <= at and at+length <= stack:
            return
        ranges = [(source+0x38, 4)] if phase == 'reduce' else [
            (start, 16*count), (c['root']+8, 4), (c['disabled'], 1),
            (c['disabled']-10, 1), (c['disabled']-9, 1)]
        if not any(lo <= at and at+length <= lo+n for lo, n in ranges):
            raise ValueError('Native acquisition wrote unrelated data: ' + hex(at))
        if start <= at < start+16*count:
            sample_writes.append((at-start, length))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, code_hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)
    try:
        for sample in expected_samples:
            if any(not -32768 <= value <= 32767 for value in sample):
                raise ValueError('Use bounded signed synthetic cache values')
            # Independent raw-cache fixtures. The original reduction computes
            # sum(four halfwords)-16*reference for each channel.
            for offsets, value in zip(((0x18, 0x1a, 0x28, 0x2a), (0x1c, 0x1e, 0x2c, 0x2e)), sample):
                for offset, raw in zip(offsets, (16384+value, 0, 0, 0)):
                    cpu.mem_write(source+offset, struct.pack('<H', raw))
            cpu.mem_write(source+0x70, struct.pack('<H', 1024))
            phase = 'reduce'
            cpu.reg_write(arm.UC_ARM_REG_R12, source)
            # The reduction starts inside a larger native frame and uses
            # positive SP offsets; reserve that frame below the stack top.
            cpu.reg_write(arm.UC_ARM_REG_SP, stack-0x100)
            cpu.emu_start(p['reduce'] | 1, p['reduce_end'], count=80)
            if cpu.reg_read(arm.UC_ARM_REG_PC) != p['reduce_end']:
                raise ValueError('Native cached-state reduction missed its boundary')
            if struct.unpack('<2h', cpu.mem_read(source+0x38, 4)) != sample:
                raise ValueError('Native cached-state reduction differs from independent fixture math')
            reduction_calls += 1
            phase = 'collect'
            cpu.reg_write(arm.UC_ARM_REG_SP, stack)
            cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
            cpu.emu_start(p['collect'] | 1, finish, count=300)
            if cpu.reg_read(arm.UC_ARM_REG_PC) != finish:
                raise ValueError('Native acquisition callback did not return')
            collector_calls += 1
        expected_bytes = b''.join(struct.pack('<2h', *sample) for sample in expected_samples)
        if (bytes(cpu.mem_read(start, len(expected_bytes))) != expected_bytes
                or struct.unpack('<I', cpu.mem_read(c['root']+8, 4))[0] != start+len(expected_bytes)
                or sample_writes != [(n*4+offset, 2) for n in range(len(expected_samples)) for offset in (0, 2)]):
            raise ValueError('Original collector did not create every measurement halfword in order')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    return dict(original_reduction_calls=reduction_calls, original_collector_calls=collector_calls,
                measurement_sample_bytes=len(expected_bytes), native_cursor_advanced_bytes=len(expected_bytes),
                native_written_sample_halfwords=len(sample_writes), host_assigned_sample_halfwords=False,
                cached_raw_words_are_synthetic=True, collector_selection_and_order_are_fixtures=True,
                full_adjustment_script_executed=False, raw_feedback_transport_executed=False)


def replay(directory, case, baseline=(0, 0)):
    result = pair_sequence(directory, full_control=True,
        scale_initializer=lambda cpu, vector: calculate(cpu, directory, case,
            measurement_initializer=lambda cpu, c, values: acquire(cpu, directory, c, values, baseline),
            complete_local_return=True))
    return dict(scale_calculation=result['scale_initialization'], shots=result['shots'],
                original_factory_scale_bytes=result['original_scale_bytes'],
                native_full_consumer_producer_and_packet_formatters=(
                    result['full_control_producer_executed'] and result['native_first_then_second_formatters']),
                same_ram=True,
                synthetic_inputs=dict(case, baseline=baseline), camera_io=False, installable=False,
                physical_shift_verified=False)


def compare(c2, reference):
    nominal = dict(gain=16, range=10, span=10, x=200, y=100, z=[100, 100])
    inputs = [(dict(nominal, count=n), baseline) for n in (1, 2, 4)
              for baseline in ((0, 0), (-123, 77))]
    inputs += [(dict(nominal, count=1, x=0), (29, -17)),
               (dict(nominal, count=2, y=-100), (51, 223))]
    rows = []
    for case, baseline in inputs:
        a, b = replay(c2, case, baseline), replay(reference, case, baseline)
        if a != b:
            raise ValueError('C2/CR cached acquisition/calculation/vector behavior differs')
        rows.append(dict(input=dict(case, baseline=baseline), target=a, reference=b))
    return dict(schema='a7c2-native-scale-acquisition/1', paired_cases=len(rows),
                paired_vector_steps=4*len(rows), cases=rows, camera_io=False,
                installable=False, physical_shift_verified=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'paired_vector_steps', 'camera_io')}))


if __name__ == '__main__':
    main()
