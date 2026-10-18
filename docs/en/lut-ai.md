# LUT / DCP: AI implementation and reproduction guide

[Home](../../README.md) · [简体中文](../zh-CN/lut-ai.md) · [User workflow](custom-lut.md)

**Goal: start from the user's DCP/LUT and complete actual selected-slot installation, preview/new-photo acceptance and tested restoration. Installing FL23 first is not required.** Stock 2.01 is an independent route. Reusing transport/native-worker source under `src/fl23` does not mean running the FL23 installer or requiring the research body's historical three-look state.

Current `lut.py` commands are offline. This guide specifies the remaining device implementation and evidence. Read [AGENTS](../../AGENTS.md), [the complete workflow](custom-lut.md), [formats](technical/formats.md), [known layouts/hashes](technical/integration.md), [validation](technical/validation.md) and [earlier failures](technical/failures.md). FL23 has [its own AI guide](fl23-ai.md).

This is the implementation specification for the next AI/developer, covering main-guide steps 7–13 and actual device writes. **Interfaces marked “to implement” are development requirements, not commands already supplied by `python lut.py`.** Invented commands, another body's settings and uploading whole firmware are not substitutes.

## A. Choose the delivery route first

| Source | AP SHA-256 | CP SHA-256 | Next action |
|---|---|---|---|
| Stock 2.01 | `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b` | `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428` | Implement/review/test a stock-to-custom-runtime adapter |
| FL23-only | `1aaeb8fbe0297950cab454d498d1a5ba874f91542aa2737aae27a73971e324d7` | `60a9de1a0636c7f6b5b98607a4d25eeb48634e25294f632743a6d256e583b370` | Implement/review/test an FL23-to-custom-runtime adapter |
| Historical three-look/current six-look | See [source fingerprints](technical/integration.md) | See [source fingerprints](technical/integration.md) | Use the matching existing builder/table adapter, then implement orchestration |
| Other fingerprints, including already-updated six-look tables | Not automatically accepted | Not automatically accepted | Capture/compare/review a new source registration; the old adapter does not automatically apply |

Implement the minimal, testable exact-full7-v4 selected-table update first, then first installation. Completing one route does not complete the other. `sixbuild.build` starts with already-patched historical three-look programs; merely installing FL23 does not produce that source.

## B. Reuse the actual public sources

| Component | Existing entry | Implementation task |
|---|---|---|
| References/calibration/fitting | [references.py](../../src/looks/looktool/references.py), [calibration.py](../../src/looks/looktool/calibration.py), [native.py](../../src/looks/looktool/native.py) | Retain input-domain/calibration requirements and review actual fits |
| Manifests/table updates | [firmware.py](../../src/looks/looktool/firmware.py), [six.py](../../src/looks/looktool/six.py) | Reuse complete hashes, windows and exact inverses |
| Historical three-to-six programs | [sixbuild.py](../../src/looks/looktool/sixbuild.py) | Accept registered inputs only; implement a missing stock adapter separately |
| Native compiler inputs/report check | [worker.py](../../src/looks/looktool/worker.py) | `prepare_table_worker` supports only exact six-look table updates; `validate_worker_report` validates this job's ABI contract |
| USB/session/staging | [transport.py](../../src/fl23/transport.py), `Session` | Reuse body binding, timeout-stop and restricted temporary staging without relaxing FL23 guards |
| Native program write/restore | [installer.c](../../src/fl23/native/installer.c), [sha256.h](../../src/fl23/native/sha256.h) | Recompile with this job's header; the fixed FL23 `assets/installer.so` cannot execute another manifest |
| Host orchestration reference | [app.py](../../src/fl23/app.py), `Job.module`, `files`, `audit` | Implement a separate custom runner; do not invoke FL23 install/restore or reuse its fixed target checks unchanged |
| Retained image | [wbi.c](../../src/fl23/native/wbi.c) | Implement generic read-only state inspection before guarded mode2 invalidation |
| Private real-file reproduction | [test_private_reproduction.py](../../src/looks/tests/test_private_reproduction.py), [test_worker.py](../../src/looks/tests/test_worker.py) | Run with legitimate local fixtures, otherwise skip accurately |

The public repository does not include the research tree/private backups. Do not depend on the researcher's machine paths, old authorization reports or that body's 68 resource originals. Implement absent components using the protocols below, rather than asking users to find scripts missing from their release.

## C. Device interfaces and phase records to implement

These names specify proposed Python responsibilities, **not runnable public CLI commands**:

| Interface to implement | Inputs | Required output/check |
|---|---|---|
| `prepare_device_job` | Project, target body, new workspace/second backup | Identity, full files/settings/resources, adapter, duplicate hashes, plan |
| `check_device_job` | Pinned plan and compiled worker | Fresh source/field preconditions, native mode0 result; no program/recipe changes |
| `install_device_job` | Checked plan and actual battery level | Single-invocation intent, staged native evidence and full readbacks |
| `inspect_existing_result` | Failed/unknown job | Existing request/worker/report/current full files only; no repeated invocation |
| `verify_after_reload` | Same body and install report | Boot evidence, AP spans, CP disk file, recipes/protected units and user observations |
| `restore_device_job` | Exact inverse and current target | Inverse dependency order, full readbacks/reload; not arbitrary recovery |

Keep `source/`, `settings/`, `resources/`, `candidate-v1/`, `transition-v1/`, `worker-v1/`, `evidence/` and a phase journal. Before invocation, persist identity, worker hash, mode and source/target. Exceptions mark `OUTCOME_UNKNOWN`, not “failed, therefore nothing written.”

Suggested phases: `CAPTURED → BACKUPS_VERIFIED → PLAN_VERIFIED → NATIVE_CHECKED → RESOURCES_COMMITTED → PROGRAMS_COMMITTED → SETTINGS_COMMITTED → HOST_VERIFIED → RELOAD_PREPARED → RELOAD_VERIFIED → PHYSICAL_ACCEPTED`. Table-only jobs explicitly record verified skips for unnecessary resources/settings. Bind each phase to artifact hashes and advance only on evidence.

## D. Runnable offline worker compilation for existing six-look tables

Prepare the selected-table manifests from the main guide, fresh complete `source/appFw.so` and `source/cpapp-b.bin`, and `bindings.json` in the job directory. Run the script below from the tool root with dependencies installed. Install a host-appropriate Zig and put `zig` on PATH. It accepts exact full7-v4 only, rejecting stock, FL23 and other sources.

Save this as your own `prepare_native_worker.py` and pass the job directory. It creates only a private header/worker/contract on the computer, without USB:

```python
from pathlib import Path
import hashlib
import json
import subprocess
import sys

repo = Path.cwd()
sys.path.insert(0, str(repo / "src/looks"))
from looktool.worker import prepare_table_worker

job = Path(sys.argv[1]).resolve()
read_json = lambda p: json.loads(p.read_text(encoding="utf-8-sig"))
header, contract = prepare_table_worker(
    (job / "source/appFw.so").read_bytes(),
    (job / "source/cpapp-b.bin").read_bytes(),
    read_json(job / "transition-v1/forward.private.json"),
    read_json(job / "transition-v1/reverse.private.json"),
    read_json(job / "bindings.json"),
)
out = job / "worker-v1"
out.mkdir(exist_ok=False)
h = out / "manifest.private.h"
h.write_text(header, encoding="ascii")
worker = out / "transition.so"
native = repo / "src/fl23/native"
command = [
    "zig", "cc", "-target", "aarch64-linux-gnu", "-shared", "-fPIC",
    "-O2", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables", "-nostdlib",
    "-Wl,--no-undefined", "-Wl,-Bsymbolic", "-Wl,-z,noexecstack",
    "-I", str(native), '-DPATCH_MANIFEST="' + h.as_posix() + '"',
    "-o", str(worker), str(native / "installer.c"),
]
subprocess.run(command, check=True)
contract["worker_sha256"] = hashlib.sha256(worker.read_bytes()).hexdigest()
contract["manifest_sha256"] = hashlib.sha256(h.read_bytes()).hexdigest()
(out / "contract.private.json").write_text(
    json.dumps(contract, indent=2), encoding="utf-8"
)
print("OFFLINE BUILD ONLY; no USB access or camera installation")

```

`worker-v1` must not exist. The header contains source-derived private bytes and must stay outside Git. `prepare_table_worker` rebuilds/compares the selected-table update, rejects other changes, validates complete inverses and checks ST assertions in JSON. It cannot establish live camera bindings.

After compilation inspect AArch64 ET_DYN, `DT_INIT`, no external symbols/`DT_NEEDED`, supported local RELATIVE relocations only, and execute real-ELF syscall fault tests. Compilation alone does not permit device execution. Bind source/header/worker hashes to the plan and recheck before calling.

## E. The actual native program-write protocol

Reuse `Session` in a custom runner, one service session at a time. Existing allowlisted temporary names are `a7c2-preview-staged.so`, `a7c2.install.request`, `libJit.so`, `a7c2.install.result`. First reject unhandled prior contents/preload configuration.

1. Stage this worker and read back its complete bytes.
2. The 16-byte request is `struct.pack('<8sII', b'A7INS001', mode, 0)`: mode0 checks original source, mode1 installs, mode2 restores this job's target to source.
3. Read the request back, persist invocation intent, then write `libJit.so` **once** to trigger the existing native loader. Do not use shell/preload/raw flash.
4. Save the 240-byte report and call `validate_worker_report(raw, mode, contract)`.
5. After installation/restore independently read complete `/usr/lib/appFw.so` and `/cp/cpapp-b.bin` on the host, compare the proper targets and verify mounts, sizes/inodes, preservation and cleanup.

The report's first 112 bytes use `<8sIIII7q4Q`: magic/version/mode/phase/window writes; status/rollback/remount/readonly/cleanup/euid/pid; AP inode/CP inode/AP size/CP size. Four 32-byte hashes follow: actual operation-source AP/CP and actual operation-target AP/CP. Require magic `A7IRP001`, version1, phase9 and zero errors/euid; mode/write counts/sizes/directional hashes must match this job. Mode0 has no target writes and zero target hashes.

The worker itself permits only `/usr/lib/appFw.so` and `/cp/cpapp-b.bin`, retains size/inode and performs window checks, fsync, complete hashes and read-only restoration. It does **not** handle resources, Backup settings, retained images or photography; evidence for each is separate. The fixed targets in `src/fl23/core.py` also cannot validate arbitrary new tables unchanged.

## F. Three additional components required for first installation

**Runtime adapter:** register complete stock/FL23 AP/CP sources and reconstruct complete targets privately; publish authored generators/small patch constraints only. Review AP custom selectors, CP handoff, table format/checksums, still/live-view entries, loaded text/BSS and instruction boundaries. Prove loading/lifetime of storage rather than treating zero bytes as ownership. Reusing the successful six-look mechanism still requires proving complete source-relative differences/inverses. Do not reuse failed display trampolines or withdrawn notifications.

**Name resources:** implement UXC-v7 parsing, additions, inverse and an atomic resource transaction. The studied format starts with `b'uxc\x07\0\0\0\0'`; offset8 is `<HHI`, string kind8, inspected count/index span `count | (((count+1)&~1)<<12)`. u16 indices start at16, data base is 4-byte aligned; `0xffff` means absent, otherwise records are at `data_base + 4*pointer`. Records contain u32 ID, UTF-8, NUL and alignment. Validate existing IDs/text, 16-bit offsets and every language/layout. The body used 68 resources and the [known label IDs](technical/integration.md); a historical “+64B/fixed count” transform is not a stock converter. New titles apply only to selected slots; preserve the native dynamic getter elsewhere. Stage/verify/atomically replace resources on the same filesystem, retain verified original links until physical acceptance, and avoid unverified icon banks/RX segments.

**Slot settings:** derive Backup keys from fresh AP descriptors/settings instead of copying a whole donor Backup. In studied sources, descriptor offset is `0x57c6710 + (attribute-0x14ea)*32`; base attribute=`0x14ea+selector`, eight adjustment attributes=`0x1520+i*18+selector`, imported selector=slot+9 (10–15). These are exact-source discovery leads, not blind write addresses. Verify IDs/types/lengths/`0x02cf` group and multi-value native-getter cross-checks. Touch only selected 9×N fields. Set base ST and use a fresh ST baseline matching calibration conditions, not all-zero adjustments. Check each before/WRITE/READ, save the group once and verify storage. Preserve unselected recipes and CP units `0x02a40000/01/02/0d`. Do not globally widen FL23 `AP_KEYS`/`CP_KEYS`; implement a separate settings path constrained to this descriptor-derived plan.

First-install dependencies: readable resources → referencing programs → selected settings → complete preservation → retained-image handling → cold-load/physical acceptance. Multiple transactions are not globally atomic. Represent intermediate states such as resources committed/program failed, and supply compatible phase inverses instead of forcing progress.

## G. Retained image, unknown outcomes and restoration

Implement read-only actual image-mode/backend and boot inspection first. The existing WBI worker expects mode2 and `*wbi4`; it is not a universal probe. Verify mode0 without replaying mode2→0. For known mode2, after evidence gates permit, perform `image_drop=1` then `image_mode=0` once, checking write lengths, closes, mode0/backend and a new drop log. Ask for power removal only after all I/O ends.

Unknown-result recovery reads the existing request/staged worker/240-byte report/current complete files first. If already completed, finish readback/cleanup without invoking again. Partial damage may not satisfy either fixed forward or inverse; analyze actual state. Stop cleanup packets after session timeout and preserve unexpected temporary contents.

For table-only restore, mode2 verifies the complete current target again before writing originals. Mode0 checks forward source; it is not a restore-target preflight. First-install inverse order is this job's settings → programs → resources, retaining compatible references and unrelated later user changes. Restoration does not initialize the body or overwrite an entire old Backup.

## H. Required tests and acceptance

1. Run offline `src/looks/tests` and `src/fl23/tests`. New `test_worker.py` covers mode/direction/phase/errors/privileges/sizes/inodes/hashes/lengths/unknown sources and actual-file selected-table constraints.
2. Test the new runner with fake devices: source changes, failed second-copy verification, temporary conflicts, disconnect before/after invocation, host timeout after device success, recovery without replay, corrupt report, full-host-readback mismatch, unexpected saved settings and cleanup failures.
3. Run real-ELF check/install/restore, short I/O, tamper, wrong size, missing file, bad request, nonroot, read/write/fsync errors, corrupt readback, mount/read-only-restoration failures. Python mocks/C text alone are insufficient.
4. Test parse→transform→parse→inverse for every resource input layout; atomic replacement failures, original links, old mmaps and unselected getters. Test settings field bounds, before conditions, persistence and unrelated-property preservation.
5. On an authorized body, preflight before separate transactions/full readback. End I/O before requesting necessary full power removal. After reload check AP, CP disk, recipes/protected units, then separately record names, no-shutter preview, new captures/playback and native looks. Preserve the limitation if CP RAM was not directly read.

Deliver actual device entrypoints, matching help/docs, tested inverses, phase/evidence paths and results limited to the bodies/modes actually tested. **For a user starting with only a DCP, missing calibration or a stock adapter remains implementation work. Do not invent defaults or deliver a candidate as proof of completed installation.**

## I. Implementing and accepting macOS support

The offline layer installs only `src/looks/requirements.txt` and runs `python lut.py doctor`, parsing/calibration/fitting/manifests. It does not import the FL23 installer, Tkinter or USB libraries. Verify native-architecture Python/NumPy/SciPy and `/Users/...` or `/Volumes/...` paths. Do not apply Windows driver instructions. Python routing tests are not physical Mac tests.

For **actual macOS writing**, implement and verify the USB host layer separately:

1. Establish Intel/Apple Silicon libusb/PyUSB availability and architecture; verify actual enumeration, interface ownership, claim/release and errors.
2. On a real Mac first test identity, service-identity transition/authentication, complete file reads and bounded timeouts. Existing `Session`/generic libusb source is a porting reference, not proof of macOS functionality.
3. Diagnose system-owned Mass Storage interfaces explicitly and use a verified userspace access mechanism. Do not ignore claim errors or remove checks to call it supported; do not require ordinary users to change system security settings.
4. Test request/report bytes, short I/O, disconnect/unknown outcomes and recovery without replay. Only after duplicate body backups, exact source and native preflight, perform a single authorized installation with full readback/reload/preview/photo and restore acceptance on Mac.

Until then, report Mac offline execution/testing separately from unverified/unimplemented Mac USB writes. Windows success does not establish Mac success. There is no current guaranteed one-click stock-to-custom Mac installer; the work items above tell the next AI what it must implement.

## J. Final user handoff

Fill [main steps 7–13](custom-lut.md#from-converted-files-to-camera-installation-steps-713): input reference, calibration/evidence/error, slots, body identity, stock/modified source, backups, program/resource/settings targets, native preflight/write report, host readback, load evidence, user preview/photo observations, restore tests, platform and remaining gaps. If only offline work is complete, state the concrete blocker and retain the workspace.
