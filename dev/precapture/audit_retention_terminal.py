"""Original retention event4 ordering on synthetic metadata, offline only.

Stop before logs, frame/holder release and node-pool locks. Separate slices
after those calls do NOT fabricate their return or prove physical completion.
No camera access, payload placement, image allocation or installable patch.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R9, UC_ARM_REG_SP, UC_ARM_REG_LR)
from support.capture_native import NativeCapture, BASE, OWNER, STACK, STOP, DEBUG, words
from support.cp_mapping import PINNED

QUEUE, POOL = 0x1a45c70, 0x1a444f4
HOLDER, NODE, FRAME = OWNER + 0x1000, OWNER + 0x1800, OWNER + 0x4000
OLD_HOLDER, OLD_FRAME = OWNER + 0x2000, 0x31000000


def audit(cp):
    n = NativeCapture(cp)
    u = n.u
    u.mem_map(0x1a44000, 0x2000)
    u.mem_map(OLD_FRAME, 0x7000)
    n.call(0xa09cce, [])  # Whole original pure queue/pool initialization.
    initial = bytes(u.mem_read(QUEUE, 0x34))
    cases = []
    for state in (0, 1, 2):
        for count in (0, 1):
            q = bytearray(initial)
            struct.pack_into('<I', q, 0x1c, state)
            struct.pack_into('<I', q, 0x30, 17)
            q[0x2c] = q[0x2d] = 1
            if count:
                struct.pack_into('<3I', q, 4, NODE, NODE, 1)
                u.mem_write(NODE, words(QUEUE + 4, QUEUE + 4, OLD_HOLDER))
            u.mem_write(QUEUE, bytes(q))
            u.mem_write(FRAME, bytes(0x7000))
            u.mem_write(FRAME + 0x66e8, words(3))
            u.mem_write(HOLDER, words(FRAME))
            u.mem_write(OLD_FRAME, bytes(0x7000))
            u.mem_write(OLD_FRAME + 0x66e8, words(2))
            u.mem_write(OLD_HOLDER, words(OLD_FRAME))
            u.mem_write(DEBUG, bytes(0x100))
            got = n.run(0x3720c4, (0xa3b61c,), [
                (UC_ARM_REG_R0, QUEUE), (UC_ARM_REG_R1, 4),
                (UC_ARM_REG_R2, HOLDER), (UC_ARM_REG_R3, 0),
                (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
            assert got['args'][:3] == [4, 0x8004, 4]
            assert bytes(u.mem_read(QUEUE, 0x34)) == q
            got = n.run(0x3720fc, (0xa3b61c,))  # Post-log, no log result used.
            assert got['args'][:2] == [4, 0x8008]
            assert struct.unpack('<I', u.mem_read(QUEUE + 0x1c, 4))[0] == state
            assert struct.unpack('<I', u.mem_read(QUEUE + 12, 4))[0] == count
            # Event4 in state2 clears native latches/increments serial before
            # it releases incoming marker3; states0/1 use the other callback.
            assert struct.unpack('<I', u.mem_read(QUEUE + 0x30, 4))[0] == 17 + (state == 2)
            assert bytes(u.mem_read(QUEUE + 0x2c, 2)) == (bytes(2) if state == 2 else b'\1\1')
            got = n.run(0x372284, (0x36bf24,))
            assert got['args'][0] == FRAME
            before_release = bytes(u.mem_read(QUEUE, 0x34))
            assert struct.unpack_from('<I', before_release, 0x1c)[0] == state
            assert struct.unpack_from('<I', before_release, 12)[0] == count
            # Separate post-frame-release slice. The release did not execute.
            got = n.run(0x3722c0, (0xa018dc,))
            assert got['args'][0] == HOLDER
            assert bytes(u.mem_read(QUEUE, 0x34)) == before_release
            # Separate post-callback slice, not a fake successful holder free.
            # The original dispatcher stores state0 BEFORE draining old nodes.
            got = n.run(0x37212e, (0x372418,))
            q_after = bytes(u.mem_read(QUEUE, 0x34))
            assert struct.unpack_from('<I', q_after, 0x1c)[0] == 0
            assert struct.unpack_from('<I', q_after, 12)[0] == count
            if count:
                assert got['address'] == BASE + 0x372418
                assert got['args'][:2] == [QUEUE, 1]  # Native discard flag.
                # Actual dequeue prefix unlinks one metadata node, but stops
                # at native pool-return BEFORE any OS-lock call or image work.
                got = n.run(0x372418, (0xa01bb6,))
                assert got['args'][:2] == [POOL, NODE]
                assert struct.unpack('<3I', u.mem_read(QUEUE + 4, 12)) == (QUEUE + 4, QUEUE + 4, 0)
                # Node removal and count0 still are not pixel-release proof.
                assert bytes(u.mem_read(OLD_HOLDER, 4)) == words(OLD_FRAME)
                assert bytes(u.mem_read(OLD_FRAME + 0x66e8, 4)) == words(2)
            else:
                assert got['address'] == STOP
            cases.append(dict(previous_state=state, old_node_count=count,
                frame_release_entered_but_not_executed=True,
                holder_release_entered_but_not_executed=True,
                state_zero_before_dequeue=bool(count),
                node_count_zero_does_not_prove_pixel_release=bool(count)))
    return cases


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    result = dict(schema='OFFLINE_NATIVE_RETENTION_EVENT4_ORDER/1',
        cp_sha256=digest, camera_io=False, cases=audit(cp),
        limits=['Explicit independent slices do not model successful external calls',
            'No real frame/holder release, pool lock, image processing or CP scheduling executes',
            'State0 and node count0 are not sufficient physical terminal fences',
            'No proof that older frames cannot arrive after marker3 is supplied',
            'No new callback slot or counter ownership is granted'])
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(f"Original event4 order: {len(result['cases'])} cases. No camera I/O.")


if __name__ == '__main__':
    main()
