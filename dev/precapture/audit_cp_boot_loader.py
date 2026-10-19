"""Read-only native NOR/CP-transfer boot routing audit on synthetic memory.

Original AArch64 instructions and pure config getters execute. NOR reads and
logging are stop boundaries, with no supplied hardware success. CP-transfer
markers are explicitly synthetic; observing them does not verify image bytes.
"""
import argparse
import hashlib
import itertools
import json
import struct
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2,
    UC_ARM64_REG_X5, UC_ARM64_REG_X19, UC_ARM64_REG_X20, UC_ARM64_REG_X21,
    UC_ARM64_REG_SP, UC_ARM64_REG_LR, UC_ARM64_REG_PC)
from audit_control import SPECS

LOADER_SHA = '5887ce4e6ca5fe1acdf6b675457f70e9798c61686f1d62c95190158855c96b22'
MEM, STACK, STOP = 0x30000000, 0x40000000, 0x60000000
CONFIG, CP_TRANSFER = 0xFE040000, 0x800107F20


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--loader', type=Path, required=True)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    loader, cp = args.loader.read_bytes(), args.cp.read_bytes()
    if hashlib.sha256(loader).hexdigest() != LOADER_SHA:
        raise ValueError('Unsupported original NOR loader')
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original target CP')
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for at, size in ((0, 0x20000), (MEM, 0x2000), (STACK, 0x4000), (STOP, 4096),
                     (CONFIG, 0x1000), (CP_TRANSFER & ~4095, 4096)):
        u.mem_map(at, size)
    u.mem_write(0, loader)
    stop_at, observed = set(), []
    def stop(cpu, address, size, user):
        if address in stop_at:
            observed.append(dict(address=address, args=[cpu.reg_read(r) for r in
                (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2)]))
            cpu.emu_stop()
    u.hook_add(UC_HOOK_CODE, stop)
    def run(entry, boundaries, argument=None):
        stop_at.clear();stop_at.update(boundaries);observed.clear()
        u.reg_write(UC_ARM64_REG_SP, STACK + 0x3000)
        u.reg_write(UC_ARM64_REG_LR, STOP)
        if argument is not None:
            u.reg_write(UC_ARM64_REG_X0, argument)
        u.emu_start(entry, STOP, count=500)
        pc = u.reg_read(UC_ARM64_REG_PC)
        if pc == STOP:
            assert not observed
            return dict(address=STOP, result=u.reg_read(UC_ARM64_REG_X0))
        assert len(observed) == 1 and pc == observed[0]['address']
        return observed[0]
    sectors = (len(cp) + 511) // 512
    read_cases = []
    for source_sector, destination, file_sectors in itertools.product(
            (0x1000, 0x1800), (0x108000, 0x508000), (sectors, sectors + 128)):
        row = bytearray(64)
        struct.pack_into('<II', row, 0, source_sector, file_sectors)
        struct.pack_into('<I', row, 16, destination)
        u.mem_write(CONFIG + 0x140, bytes(row))
        config_before = bytes(u.mem_read(CONFIG, 4096))
        for label, entry in (('prefix', 0xF9CC), ('remainder', 0xF8CC)):
            item = run(entry, {0xFC84})
            offset = 0 if label == 'prefix' else 0x500000
            count = 0x500000 if label == 'prefix' else file_sectors * 512 - offset
            expected = [destination + offset, source_sector * 512 + offset, count]
            assert item['address'] == 0xFC84 and item['args'] == expected
            assert bytes(u.mem_read(CONFIG, 4096)) == config_before
            read_cases.append(dict(path=label, source_sector=source_sector,
                destination=destination, file_sectors=file_sectors,
                read_arguments=expected, read_executed=False))
    branch_cases = []
    for flags, mode in itertools.product((0, 4), range(4)):
        frame = bytearray([0xA5]) * 0x300
        frame[0x238] = flags;frame[0x1F5] = mode
        for path, entry, next_entry, skip_string in (
                ('prefix', 0x9A54, 0xF9CC, 0x13919),
                ('remainder', 0x99E8, 0xF8CC, 0x138EE)):
            u.mem_write(MEM, bytes(frame))
            item = run(entry, {next_entry, 0xB50C}, MEM)
            skipped = bool(flags & 4 or mode == 2)
            assert item['address'] == (0xB50C if skipped else next_entry)
            if skipped:
                assert item['args'][:2] == [2, skip_string]
            assert bytes(u.mem_read(MEM, len(frame))) == bytes(frame)
            branch_cases.append(dict(path=path, flags=flags, mode=mode,
                skipped=skipped, boundary=hex(item['address']), boundary_executed=False))
    transfer_cases = []
    for marker, prior_status, metadata in itertools.product(
            (0, 0x454E524B), (0, 1, 7), (0, len(cp), 0x12345678)):
        frame = bytearray([0xA5]) * 0x300
        struct.pack_into('<I', frame, 0x1B8, prior_status)
        u.mem_write(MEM, bytes(frame))
        u.mem_write(CP_TRANSFER, struct.pack('<IIQ', marker, 0, metadata))
        item = run(0x9974, {0xB50C}, MEM)
        expected = bytearray(frame)
        if marker == 0x454E524B:
            struct.pack_into('<I', expected, 0x1B8, 0)
            struct.pack_into('<Q', expected, 8, metadata)
            assert item['address'] == 0xB50C and item['args'][:2] == [2, 0x138C4]
            outcome = 'synthetic-transfer-marker'
        elif prior_status == 1:
            assert item['address'] == STOP and item['result'] == 1
            outcome = 'waiting-already-announced'
        else:
            struct.pack_into('<I', expected, 0x1B8, 1)
            assert item['address'] == 0xB50C and item['args'][:2] == [2, 0x1398B]
            outcome = 'waiting-log-boundary'
        assert bytes(u.mem_read(MEM, len(frame))) == bytes(expected)
        transfer_cases.append(dict(marker=hex(marker), prior_status=prior_status,
            metadata_word=metadata, outcome=outcome, logging_executed=False,
            physical_transfer_performed=False))
    # Follow the actual marker-produced word through the original jump setup.
    # Logging/MMIO/cache/SEV/privileged control writes are explicit boundaries,
    # not made successful to claim a continuous physical boot execution.
    entry_cases = []
    for entry_address, flags in itertools.product((0, 0x108000, 0x619EA0, 0xDEADBEEF), (0, 8)):
        frame = bytearray([0xA5]) * 0x300
        struct.pack_into('<I', frame, 0x1B8, 0)
        frame[0x238] = flags
        u.mem_write(MEM, bytes(frame))
        u.mem_write(CP_TRANSFER, struct.pack('<IIQ', 0x454E524B, 0, entry_address))
        assert run(0x9974, {0xB50C}, MEM)['address'] == 0xB50C
        assert struct.unpack('<Q', u.mem_read(MEM + 8, 8))[0] == entry_address
        u.reg_write(UC_ARM64_REG_X19, MEM)
        item = run(0x957C, {0xB50C})
        assert item['args'] == [2, 0x13CF1, entry_address]
        assert u.reg_read(UC_ARM64_REG_X21) == entry_address
        assert u.reg_read(UC_ARM64_REG_X20) == flags >> 3
        # Separate post-MMIO/cache slice. No result from those omitted
        # operations is consumed; x21/x20 are the retained native inputs.
        assert run(0x95F8, {0x9600})['args'][:2] == [entry_address, flags >> 3]
        assert run(0xAE20, {0x89D8, 0x89E8})['address'] == (0x89D8 if flags else 0x89E8)
        assert u.reg_read(UC_ARM64_REG_X0) == entry_address
        run(0x89E4, {0x89E8})
        assert u.reg_read(UC_ARM64_REG_X5) == 0x30
        run(0x89F8, {0x89FC})
        assert u.reg_read(UC_ARM64_REG_X5) == 0x13
        assert u.reg_read(UC_ARM64_REG_X0) == entry_address
        entry_cases.append(dict(synthetic_entry=hex(entry_address), flags=flags,
            marker_word_used_as='kernel-entry-address', entry_argument_preserved=True,
            intended_SPSR_EL3='0x13', intended_execution_state='AArch32 SVC',
            privileged_registers_or_ERET_executed=False))
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
    md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    for at, mnemonic, operands in ((0x9600, 'sev', ''),
            (0x89E8, 'msr', 'scr_el3, x5'), (0x89FC, 'msr', 'spsr_el3, x5'),
            (0x8A00, 'msr', 'elr_el3, x0'), (0x8A04, 'eret', '')):
        ins = next(md.disasm(loader[at:at + 4], at))
        assert (ins.mnemonic, ins.op_str) == (mnemonic, operands)
    report = dict(schema='OFFLINE_ORIGINAL_NOR_CP_BOOT_ROUTES/1', camera_io=False,
        loader_sha256=LOADER_SHA, original_cp_sha256=hashlib.sha256(cp).hexdigest(),
        read_cases=read_cases, branch_cases=branch_cases, transfer_cases=transfer_cases,
        transfer_entry_cases=entry_cases,
        limits=['Config records and CP completion markers are synthetic, not current camera readings',
            'All native NOR read/log boundaries stop before execution',
            'The transfer +8 word is consumed as a kernel entry address, not an image size or integrity result',
            'MMIO, cache maintenance, SEV and privileged transition remain unexecuted boundaries',
            'Optional native adjacent-byte swap follows a successful NOR read and is not executed here',
            'File updates do not establish NOR-cache invalidation or the next physical boot source',
            'No executable placement, initialization, camera boot or pre-capture is established'])
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(f'{len(read_cases) + len(branch_cases) + len(transfer_cases) + len(entry_cases)} native loader routing cases checked; no hardware read or camera I/O.')


if __name__ == '__main__':
    main()
