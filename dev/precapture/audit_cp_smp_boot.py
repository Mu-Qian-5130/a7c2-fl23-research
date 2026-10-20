"""Original CP secondary-start guards and four-marker comparison, offline only.

MPIDR-derived selector inputs and phase words are explicit independent fixtures.
The comparison stops before lock cleanup/wait; it is not a complete barrier,
native producer, scheduler, peer-ready signal or camera-readiness test.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as R
from support.reference import SPECS

BASE, FLAG, PREFIX = 0x108000, 0x108d94, 0x120a000
PHASES, STOP = 0x1a9db14, 0x60000000


def word(cpu, at, value):
    cpu.mem_write(at, struct.pack('<I', value & 0xffffffff))


def audit(cp):
    if hashlib.sha256(cp).hexdigest() != SPECS['a7c2-2.01']['sha256']:
        raise ValueError('Unsupported original stock CP')
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for at,size in ((BASE,0x2000),(0x60d000,4096),(0x613000,4096),
                    (PREFIX,4096),(0x1a9d000,0x2000),(STOP,4096)):
        cpu.mem_map(at,size)
        if at in (BASE,0x60d000,0x613000):
            cpu.mem_write(at,cp[at-BASE:at-BASE+size])
    boundaries=set();observed=[]
    def trace(u,address,size,user):
        if address in boundaries:
            observed.append(address);u.emu_stop()
    cpu.hook_add(UC_HOOK_CODE,trace)
    def run(entry,stops,inputs=()):
        boundaries.clear();boundaries.update(stops);observed.clear()
        for register,value in inputs:cpu.reg_write(register,value)
        cpu.emu_start(entry,0xffffffff,count=100)
        assert len(observed)==1 and cpu.reg_read(R.UC_ARM_REG_PC)==observed[0], 'Expected source boundary not reached'
        return observed[0]
    get=lambda at:struct.unpack('<I',bytes(cpu.mem_read(at,4)))[0]
    # Resolve original PC-relative literals for both sides of the startup cell.
    assert get(0x108380)==get(0x108388)==FLAG
    cases=[]
    for raw in range(8):
        expected=0x108054 if raw&3==0 else 0x1080a8
        got=run(0x10804c,(0x108054,0x1080a8),((R.UC_ARM_REG_R3,raw),))
        assert got==expected and cpu.reg_read(R.UC_ARM_REG_R3)==raw&3
        cases.append(dict(case='post-MPIDR-path-selector',synthetic_raw_low_bits=raw,
                          selected='primary' if got==0x108054 else 'secondary',MPIDR_read_executed=False))
    word(cpu,FLAG,0xa5a5a5a5);before=bytearray(cpu.mem_read(BASE,0x2000))
    assert run(0x108054,(0x108060,))==0x108060
    expected=bytearray(before);struct.pack_into('<I',expected,FLAG-BASE,0)
    assert bytes(cpu.mem_read(BASE,0x2000))==bytes(expected)
    cases.append(dict(case='primary-resets-secondary-start-cell',address=hex(FLAG),
                      other_prefix_bytes_unchanged=True))
    for value in (0,1,2,0xffffffff):
        word(cpu,FLAG,value);before=bytes(cpu.mem_read(BASE,0x2000))
        got=run(0x1080b4,(0x1080c4,0x1080cc))
        assert got==(0x1080cc if value==1 else 0x1080c4)
        assert bytes(cpu.mem_read(BASE,0x2000))==before
        cases.append(dict(case='secondary-start-cell-guard',synthetic_word=hex(value),
                          admitted=value==1,wait_or_cache_init_executed=False))
    # Independent post-BSS slice. The pointer is an explicit fixture also
    # observed in the actual guest's preserved native BSS prefix.
    word(cpu,PREFIX+0x14,FLAG);word(cpu,FLAG,0)
    before=bytearray(cpu.mem_read(BASE,0x2000))
    assert run(0x60d358,(0x60d374,))==0x60d374
    expected=bytearray(before);struct.pack_into('<I',expected,FLAG-BASE,1)
    assert bytes(cpu.mem_read(BASE,0x2000))==bytes(expected)
    cases.append(dict(case='primary-publishes-secondary-start-cell',address=hex(FLAG),
                      DSB_SEV_instructions_executed=True,physical_wakeup_not_established=True,
                      subsequent_runtime_library_call_executed=False))
    # Pure original comparator after native producer/lock acquisition.
    # Stop BEFORE either pending cleanup or the successful cleanup path.
    comparisons=[]
    for phase in (1,2,5):
        for markers in itertools.product((phase-1,phase,phase+1),repeat=4):
            comparisons.append((phase,markers))
        for slot in range(4):
            markers=[phase]*4;markers[slot]=0xffffffff
            comparisons.append((phase,tuple(markers)))
    for phase,markers in comparisons:
        arena=bytearray([0xa5])*0x2000
        for core,value in enumerate(markers):struct.pack_into('<I',arena,PHASES-0x1a9d000+12*core,value)
        cpu.mem_write(0x1a9d000,bytes(arena))
        signed=lambda value:value if value<0x80000000 else value-(1<<32)
        ready=all(signed(value)>=phase for value in markers)
        got=run(0x613dc0,(0x613ddc,0x613e3c),((R.UC_ARM_REG_R6,PHASES),(R.UC_ARM_REG_R12,phase)))
        assert got==(0x613e3c if ready else 0x613ddc)
        assert bytes(cpu.mem_read(0x1a9d000,len(arena)))==bytes(arena)
        cases.append(dict(case='four-marker-signed-comparison',phase=phase,
                          synthetic_markers=[hex(x) for x in markers],predicate_ready=ready,
                          markers_unchanged=True,producer_lock_cleanup_or_wait_executed=False))
    return dict(cases=cases,secondary_start_cell=hex(FLAG),phase_array=hex(PHASES),
        phase_stride=12,comparison_members=4,
        limits=['Selector input is independent post-MPIDR data; no physical CPU topology is admitted',
                'Startup cell is an inter-core software prerequisite, not an AP peer/sensor-ready signal',
                'Four-marker comparison alone does not prove its producers, lock release or scheduling',
                'DSB/SEV interpretation here does not deliver a physical event to another processor',
                'No AP/CP communication, RAW ownership, exposure, save or restoration runs'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();cp=args.cp.read_bytes()
    report=dict(schema='OFFLINE_CP_SECONDARY_START_AND_PHASE_COMPARISON/1',camera_io=False,
                CP_sha256=hashlib.sha256(cp).hexdigest(),**audit(cp))
    paths=[Path(__file__),Path(__file__).with_name('support')/'reference.py']
    report['sources']={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with args.output.open('x',encoding='utf-8') as f:
        json.dump(report,f,indent=2);f.write('\n')
    print(f"{len(report['cases'])} original secondary-start/comparison contracts; no physical startup or barrier-completion claim.")


if __name__=='__main__':
    main()
