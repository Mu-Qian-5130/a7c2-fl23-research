"""Native post-retention stage owner and completion boundary, offline only.

Uses synthetic metadata, not images. Original pure constructor/packet slices
and post-lock pool stores run. RTOS, locks, full release APIs and image work
never execute.
This does not establish a terminal ACK, barrier or installable candidate.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR)
from audit_capture_transition import NativeCapture, BASE, OWNER, STACK, STOP, words
from support.cp_mapping import PINNED

TABLE = 0x110eca4
CAP_OWNER, LATE_OWNER, CTRL = 0x1a3aae0, 0x1a3f45c, 0x1a442b4
PIPE, NODE = OWNER + 0x1000, OWNER + 0x2000


def audit(cp):
    n = NativeCapture(cp)
    u = n.u
    u.mem_map(0x1a3f000, 0x7000)
    u.mem_map(0x1a31000, 0x9000)
    u.mem_map(CAP_OWNER & ~4095, 4096)
    n.call(0xa08e2c, [])  # Original constructor; only native object/pool stores.
    n.call(0xa05d8e, [])
    n.call(0xa0195a, [])
    head, total, free = struct.unpack('<3I', u.mem_read(0x1a31f40, 12))
    assert (head, total, free) == (0x1a31f4c, 500, 500)
    nodes = []
    while head:
        assert head == 0x1a31f4c + len(nodes)*68 and len(nodes) < 500
        nodes.append(head)
        head = struct.unpack('<I', u.mem_read(head, 4))[0]
    assert len(nodes) == 500
    retention_task = struct.unpack('<3I', u.mem_read(CAP_OWNER + 0x14, 12))[:2]
    late_task = struct.unpack('<3I', u.mem_read(LATE_OWNER + 0x14, 12))[:2]
    assert retention_task == (0x88, 0x38) and late_task == (0x89, 0x39)
    assert struct.unpack('<I', u.mem_read(LATE_OWNER + 8, 4))[0] == BASE + 0x408020 + 1
    stage = struct.unpack('<6I', u.mem_read(TABLE + 6*24, 24))
    assert stage == (CTRL, 9, 0xb13a75, 0x1a500f4, 1, LATE_OWNER)
    # Native transitions to stage6 use this owner, not the retention task.
    u.mem_write(PIPE, bytes(64))
    got = n.run(0xa086ca, (0xa20ec2,), [
        (UC_ARM_REG_R0, PIPE), (UC_ARM_REG_R1, 6), (UC_ARM_REG_R2, 0),
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][:2] == [PIPE, 9]
    assert struct.unpack('<I', u.mem_read(PIPE + 0x20, 4))[0] == 6
    # Explicit continuation after internal preparation/descriptor selection;
    # its return is not fabricated and no OS delivery is performed.
    got = n.run(0xa08738, (0x407f1c,))
    assert got['args'][0] == LATE_OWNER and got['args'][2:] == [PIPE, 0]
    job = bytes(u.mem_read(got['args'][1], 20))
    assert job == words(0xb10e09, 0, BASE + 0xa08264 + 1, 0, 0)
    # Actual final-phase callback builds a different follow-up job on the
    # same stage owner. Queueing it does not establish its result.
    got = n.run(0xa08a18, (0x407f1c,), [
        (UC_ARM_REG_R0, PIPE), (UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][0] == LATE_OWNER and got['args'][2:] == [PIPE, 0]
    done = bytes(u.mem_read(got['args'][1], 20))
    assert done == words(0xb10e09, 0, BASE + 0xa081c4 + 1, 0, 0)
    # Whole original active-record completion prefix with explicit synthetic
    # metadata. Stop BEFORE returning its record to the native pool.
    u.mem_write(CTRL + 0x14, words(NODE, NODE, 1))
    u.mem_write(CTRL + 0x24, bytes(8))
    u.mem_write(NODE, words(CTRL + 0x14, CTRL + 0x14, PIPE) + bytes(0x70))
    pipe_before = bytes(u.mem_read(PIPE, 64))
    got = n.run(0xa09456, (0xa09a40,), [
        (UC_ARM_REG_R0, CTRL), (UC_ARM_REG_R1, PIPE),
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    pool = struct.unpack('<I', u.mem_read(CTRL + 0x20, 4))[0]
    assert got['args'][:2] == [pool, NODE]
    assert struct.unpack('<3I', u.mem_read(CTRL + 0x14, 12)) == (CTRL + 0x14, CTRL + 0x14, 0)
    assert bytes(u.mem_read(PIPE, 64)) == pipe_before
    # The native follow-up first performs stage bookkeeping, then posts a
    # final holder job BACK to CAM_CAP_MGR. Stop before that bookkeeping;
    # use an explicit independent post-call slice for the packet construction.
    got = n.run(0xa081c4, (0xa080c0,), [
        (UC_ARM_REG_R0, PIPE), (UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][0] == PIPE
    got = n.run(0xa08232, (0x407f1c,))
    assert got['args'][0] == CAP_OWNER and got['args'][2:] == [PIPE, 0]
    final_job = bytes(u.mem_read(got['args'][1], 20))
    assert final_job == words(0xb10e09, 0, BASE + 0xa08260 + 1, 0, 0)
    got = n.run(0xa08260, (0xa018dc,), [
        (UC_ARM_REG_R0, PIPE), (UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][0] == PIPE
    # Original holder release runs the frame destructor first, then returns
    # its holder to the shared68-byte metadata pool under native protection.
    # This post-destructor slice stops BEFORE the task/lock query.
    got = n.run(0xa018ec, (0x4ea67c,), [
        (UC_ARM_REG_R4, PIPE), (UC_ARM_REG_SP, STACK + 0x8000),
        (UC_ARM_REG_LR, STOP | 1)])
    assert got['args'][:2] == [0x1a31f40, PIPE]
    # Explicit post-lock slice with existing synthetic pool state; does not
    # supply a successful lock return or perform its unlock.
    u.mem_write(0x1a31f40, words(NODE, 500, 499))
    u.mem_write(PIPE, words(0x12345678) + bytes(64))
    got = n.run(0xa01924, (0x4ea67c,), [
        (UC_ARM_REG_R4, 0x1a31f40), (UC_ARM_REG_R5, PIPE),
        (UC_ARM_REG_SP, STACK + 0x8000), (UC_ARM_REG_LR, STOP | 1)])
    assert struct.unpack('<3I', u.mem_read(0x1a31f40, 12)) == (PIPE, 500, 500)
    assert bytes(u.mem_read(PIPE, 4)) == words(NODE)
    return dict(retention_task=dict(object=hex(CAP_OWNER), id=retention_task[0], queue=retention_task[1]),
        stage6_task=dict(object=hex(LATE_OWNER), id=late_task[0], queue=late_task[1]),
        stage6_table_words=[hex(v) for v in stage], native_enqueue_job_hex=job.hex(),
        final_phase_enqueue_job_hex=done.hex(), native_completion_record_count_zero_before_pool_return=True,
        final_holder_job_hex=final_job.hex(), final_holder_job_owner=hex(CAP_OWNER),
        protected_pool_api_completed=False, final_holder_release_executed=False,
        holder_pool_metadata_nodes=len(nodes), holder_node_bytes=68,
        independent_post_destructor_pool_return_slice=True, native_checks=6)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cp = a.cp.read_bytes()
    digest = hashlib.sha256(cp).hexdigest()
    if digest not in PINNED:
        raise ValueError('Unsupported complete target CP')
    result = dict(schema='OFFLINE_NATIVE_POST_RETENTION_OWNER/1', cp_sha256=digest,
        camera_io=False, **audit(cp), limits=[
            'A different native task owns post-retention stage6 work',
            'Explicit slices do not imply successful execution between boundaries',
            'No real RTOS delivery, RAW release, holder destruction or SD save is executed',
            'All-stage quiescence, marker ordering and absence of late frames remain unproven'])
    with a.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print('Original post-retention owners and six native contracts checked; no camera I/O.')


if __name__ == '__main__':
    main()
