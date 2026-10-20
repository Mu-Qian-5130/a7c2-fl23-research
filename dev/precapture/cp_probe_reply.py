"""Build a CURRENT-source private RPC observer for offline review ONLY.

No USB, installer, boot/reload operation or authorization is supplied.
The only modified callback entry is the original unsupported-mode branch.
Supported-mode instruction paths and4172/4173 handlers stay unchanged.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from audit_dormant_diagnostic import fixture
from looktool.hooks import assembler, HELPER
from looktool.sixbuild import CHECKER
from looktool.six import read_tables

SOURCE='3d6656b933fc681282f920364e5f3b788117c4345a89ec6b9df9862c5563f8a1'
BASE=0x108000
HOOK, ZERO, STORE = [BASE+x for x in (0x45e724,0x45e750,0x45e7b0)]
ENTRY, LEGACY, NONCE, FINAL = HELPER+0x64, HELPER+0xc2, CHECKER+0x5c, CHECKER+0x9a
MODE, STATUS = 0xe1, 0x5a


def build(cp):
    if hashlib.sha256(cp).hexdigest()!=SOURCE:
        raise ValueError('Exact current CP source required; no source masks or stock adaptation')
    # This checks actual current helper+retry overlays and declared text bounds.
    # The older dormant logger prototype is NOT installed or combined here.
    _,gaps,_=fixture(cp,'status')
    asm=assembler()
    assert cp[HOOK-BASE:HOOK-BASE+4]==asm(f'movs r1,#0x80;b {ZERO:#x}',HOOK)
    # R1 is the original callback's input mode minus1, R4 its24-byte message.
    # Status5a intentionally fails the old AP log-copy client's status1 check.
    patches=[(HOOK,asm(f'b.w {ENTRY:#x}',HOOK)),
        (ENTRY,asm(f'cmp r1,#0xe0;bne {LEGACY:#x};mrs r3,cpsr;b.w {NONCE:#x}',ENTRY)),
        (LEGACY,asm(f'movs r1,#0x80;b.w {ZERO:#x}',LEGACY)),
        (NONCE,asm(f'ldr r0,[r4,#20];b {FINAL:#x}',NONCE)),
        (FINAL,asm(f'movs r1,#{STATUS};b.w {STORE:#x}',FINAL))]
    assert [len(b) for a,b in patches]==[4,12,6,4,6]
    for at,raw in patches[1:]:
        assert any(a<=at and at+len(raw)<=a+n for a,n in gaps)
        assert not any(cp[at-BASE:at-BASE+len(raw)])
    target=bytearray(cp);rows=[]
    for at,raw in patches:
        old=cp[at-BASE:at-BASE+len(raw)];target[at-BASE:at-BASE+len(raw)]=raw
        rows.append(dict(file_offset=at-BASE,before_hex=old.hex(),after_hex=raw.hex()))
    target=bytes(target)
    restored=bytearray(target)
    for row in rows:
        a=row['file_offset'];old=bytes.fromhex(row['before_hex']);restored[a:a+len(old)]=old
    assert bytes(restored)==cp
    assert read_tables(target)==read_tables(cp)
    assert target[0x20124:0x20154]==cp[0x20124:0x20154]
    assert target[0xff466c:0xff4694]==cp[0xff466c:0xff4694]
    assert target[0x7d2a9c:0x7d2aa4]==cp[0x7d2a9c:0x7d2aa4]
    report=dict(schema='OFFLINE_CP_PRIVATE_RPC_OBSERVER/1',camera_io=False,
        source_sha256=SOURCE,target_sha256=hashlib.sha256(target).hexdigest(),patches=rows,
        touched_envelope_bytes=32,actual_changed_bytes=sum(a!=b for a,b in zip(cp,target)),
        request=dict(route='0x908f084b',bytes=24,mode=MODE,nonce_offset=20),
        response=dict(status_offset=1,status=STATUS,nonce_echo_offset=8,CPSR_offset=16,
            retained_input_nonce_offset=20,ignored_caller_scratch_offset=12),
        supported_modes=[1,2,3,4],handler_4172_4173_unchanged=True,
        program_headers_and_six_tables_unchanged=True,inverse_exact=True,
        limits=['Private mode is only for a DIRECT CP RPC client; never interpret data as an address/length',
            'Status5a must be checked before parsing nonce/CPSR; existing status1 log clients must reject it',
            'The12-offset response word is opaque caller scratch, not identity/address data; ignore/sanitize it',
            'CPSR is sampled after diagnostic comparison; condition flags are not incoming caller flags',
            'Only existing declared text gaps are used; no new mapping, startup code or native service call',
            'No install/reload/restore workflow or bounded RPC client is provided by this builder',
            'Offline byte inversion is NOT camera boot, loaded-source, hardware pre-capture or recovery proof',
            'ROM writes require a reviewed candidate/recovery plan and explicit owner approval'])
    return target,patches,report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cp',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True,help='New PRIVATE review directory')
    p.add_argument('--emit-review-image',action='store_true',help='Private uninstalled image, NOT an installable package')
    a=p.parse_args();target,patches,report=build(a.cp.read_bytes())
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'observer-review.private.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if a.emit_review_image:(a.output/'NOT-INSTALLABLE-cp-private-observer.bin').write_bytes(target)
    print('Private-mode32-byte review built; exact inverse checked. No camera access or install/reload approval.')
if __name__=='__main__':main()
