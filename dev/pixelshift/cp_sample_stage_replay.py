"""Continue original input publication through full native sample averaging.

The input source replay supplies independently modeled register words, not
successful sensor feedback. Original prepare and averaging functions execute;
native counters/indices control sample accumulation and eight-stage advance.
Geometry/command fields and invocation timing are explicit fixtures. Cases
either bypass calibration validation or retain its native rejection of the
synthetic input; neither establishes valid calibration. The full script
scheduler, real settling and physical
capture do not execute. No host fills an average or advances a native stage.
"""
import argparse
from functools import lru_cache
import json
from pathlib import Path
import struct

from cp_input_source_replay import replay as source_replay
from cp_scale_calculation_replay import profile as calculation_profile


@lru_cache(maxsize=2)
def profile(directory):
    data, c = calculation_profile(directory)
    target = c['entry'] == 0x13ca30
    p = dict(prepare=0x41b65c if target else 0x41b874,
             sample=0x41b784 if target else 0x41b99c,
             source=c['measurements']+0x100, skip_validation=c['root']+0x10)
    return data, c, p


def average(cpu, directory, input_profile, expected, requested_count, validate_inputs):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    import unicorn.arm_const as arm
    _, c, p = profile(directory)
    source = p['source']
    for at, length in ((source, 0x180), (p['skip_validation'], 4),
                       (c['command'], 2), (c['local_record']-1, 15), (c['disabled']-10, 2)):
        for page in range(at & ~4095, (at+length+4095) & ~4095, 4096):
            if not any(lo <= page <= hi for lo, hi, _ in cpu.mem_regions()):
                cpu.mem_map(page, 4096)
    stack, finish = 0x3001f000, 0x3001e000
    cpu.mem_write(source, bytes(256))
    cpu.mem_write(source+0x18, b'\xa5'*32)
    cpu.mem_write(c['command'], struct.pack('<H', (requested_count << 8) | 0x10))
    cpu.mem_write(p['skip_validation'], struct.pack('<I', int(not validate_inputs)))
    cpu.mem_write(c['disabled']-10, bytes(2))
    cpu.mem_write(c['local_record']-1, b'\x6b'+b'\xbd'*13+b'\x6b')
    snapshot = bytes(cpu.mem_read(input_profile['snapshot'], 340))
    cpu.reg_write(arm.UC_ARM_REG_C1_C0_2, 0x00f00000)
    cpu.reg_write(arm.UC_ARM_REG_FPEXC, 0x40000000)
    cpu.reg_write(arm.UC_ARM_REG_FPSCR, 0)
    calls, native_stages, native_errors = 0, [0], []
    protected = [getattr(arm, 'UC_ARM_REG_R'+str(n)) for n in range(4, 12)]
    protected += [getattr(arm, 'UC_ARM_REG_D'+str(n)) for n in range(8, 16)]
    protected_values = [0x44550000+n for n in range(8)]
    protected_values += [0x3ff0000000000000+n for n in range(8)]

    def hook(uc, at, length, unused):
        regions = [(p['prepare'], p['prepare']+0x128), (p['sample'], p['sample']+0x44a),
                   (input_profile['getter'], input_profile['getter']+0x16),
                   (c['local_update'], c['local_update']+0x70),
                   (c['local_getter'], c['local_getter']+12)]
        if not any(lo <= at and at+length <= hi for lo, hi in regions):
            raise ValueError('Native sampling stage entered an unresolved dependency: ' + hex(at))

    def write_hook(uc, access, at, length, value, unused):
        if stack-4096 <= at and at+length <= stack:
            return
        if not any(lo <= at and at+length <= lo+n for lo, n in
                   ((source, 256), (source+0x100, 128), (c['local_record'], 13), (c['disabled']-10, 2))):
            raise ValueError('Native sampling stage changed unrelated state: ' + hex(at))

    ch, wh = cpu.hook_add(UC_HOOK_CODE, hook), cpu.hook_add(UC_HOOK_MEM_WRITE, write_hook)

    def run(entry):
        for register, value in zip(protected, protected_values):
            cpu.reg_write(register, value)
        cpu.reg_write(arm.UC_ARM_REG_SP, stack)
        cpu.reg_write(arm.UC_ARM_REG_LR, finish | 1)
        cpu.emu_start(entry | 1, finish, count=5000)
        if cpu.reg_read(arm.UC_ARM_REG_PC) != finish or cpu.reg_read(arm.UC_ARM_REG_SP) != stack:
            raise ValueError('Original sample stage did not return with a balanced stack')
        if [cpu.reg_read(register) for register in protected] != protected_values:
            raise ValueError('Original sample stage changed callee-saved core/VFP registers')

    count = requested_count or 2
    try:
        for stage in range(8):
            if struct.unpack('<H', cpu.mem_read(source+0x62, 2))[0] != stage:
                raise ValueError('Original stage index was not retained between native calls')
            run(p['prepare'])
            for sample_index in range(count):
                run(p['sample'])
                calls += 1
                current = struct.unpack('<H', cpu.mem_read(source+0x62, 2))[0]
                if current != stage+int(sample_index+1 == count):
                    raise ValueError('Native stage advanced before/after its source-defined sample threshold')
            native_stages.append(current)
            native_errors.append(struct.unpack('<H', cpu.mem_read(source+0x44, 2))[0])
            value = struct.unpack('<H', cpu.mem_read(source+0x18+stage*2, 2))[0]
            if value != 4*expected[0 if stage < 4 else 1]:
                raise ValueError('Native averaging differs from independently modeled constant input')
        averages = list(struct.unpack('<8H', cpu.mem_read(source+0x18, 16)))
        if (averages != [4*expected[0]]*4+[4*expected[1]]*4
                or bytes(cpu.mem_read(input_profile['snapshot'], 340)) != snapshot
                or cpu.mem_read(c['disabled']-10, 1)[0] != 16
                or cpu.mem_read(c['local_record']-1, 1)[0] != 0x6b
                or cpu.mem_read(c['local_record']+13, 1)[0] != 0x6b):
            raise ValueError('Native stage progression/averages/source preservation differs')
        expected_error = 0x505 if validate_inputs else 0
        if native_errors[-1] != expected_error or struct.unpack('<H', cpu.mem_read(source+0x66, 2))[0] != 0:
            raise ValueError('Native validation did not retain the expected rejection/bank state')
    finally:
        cpu.hook_del(ch)
        cpu.hook_del(wh)
    return dict(requested_samples=requested_count, effective_samples=count,
                original_prepare_calls=8, original_sample_calls=calls, native_stage_history=native_stages,
                native_average_halfwords=averages, native_script_index=16,
                native_error_history=native_errors, native_final_error=expected_error,
                native_final_bank=0, native_callee_saved_registers_preserved=True,
                host_assigned_averages_or_advanced_stages=False, source_snapshot_preserved=True,
                full_original_sampling_function_executed=True,
                calibration_validation_bypassed_by_fixture=not validate_inputs,
                native_validation_rejected_inputs=validate_inputs,
                calibration_success_verified=False,
                full_script_scheduler_executed=False, physical_feedback_or_settling_verified=False)


def replay(directory, *, requested_count=0, flags=(1, 0), policy=1, validate_inputs=False):
    return source_replay(directory, flags=flags, present=(1, 1), policy=policy,
        observe_snapshot=lambda cpu, p, expected: average(cpu, directory, p, expected,
                                                         requested_count, validate_inputs))


def compare(c2, reference):
    rows = []
    for count in (0, 1, 3):
        for flags in ((1, 0), (0, 1)):
            for validate_inputs in (False, True):
                args = dict(requested_count=count, flags=flags, validate_inputs=validate_inputs)
                a, b = replay(c2, **args), replay(reference, **args)
                if a != b:
                    raise ValueError('Native C2/CR input-to-average stage behavior differs')
                rows.append(dict(input=args, target=a, reference=b))
    return dict(schema='a7c2-native-sampling-stage/1', paired_cases=len(rows), cases=rows,
                camera_io=False, physical_shift_verified=False, installable=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--c2', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = compare(args.c2, args.reference)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2)
    print(json.dumps({key: report[key] for key in ('paired_cases', 'camera_io', 'physical_shift_verified')}))


if __name__ == '__main__':
    main()
