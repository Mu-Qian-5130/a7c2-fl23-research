# Custom looks: implementation and camera integration

[Home](../../../README.md) · [简体中文](../../zh-CN/technical/integration.md)

Read [the workflow](../custom-lut.md), [formats](formats.md), [validation](validation.md), [failures](failures.md) and [the source rules](../../../src/looks/AGENTS.md) first. Work is scoped to ILCE-7CM2 firmware 2.01 and exact program fingerprints. A user request to import a look authorizes implementation within that scope, not bypassing identity guards or overwriting unrelated recipes.

## Device CLI added in v2.1 preview

`lut.py import/install/verify/restore/recover/resume` now implement the device workflow in `devicejob.py`. Stock and FL23 first-import adapters, repeated selected-slot updates, 68-resource transactions, selected ST settings and retained-image preparation are included. New names are staged atomically before programs start referencing them. The source/target and inverse remain exact per job; unknown sources stop. See [the AI guide](../lut-ai.md). The historical offline commands below retain their original restricted sources. Physical-camera and Mac USB acceptance of the new importer is still pending.

## Current evidence and layout

The owner's six looks are installed in NC/CC/NN/Eterna/GR-positive/GR-negative order. The owner reports photos work and latest v4 switching looks normal. V4 complete disk readback and fresh settings preservation were verified before that physical report. A v4 post-reload machine check is pending; running CP instruction/table RAM has not been directly read. Keep those statements separate.

| Build | AP SHA-256 | CP SHA-256 |
|---|---|---|
| Historical three-look preview-v2 | `86f4ac7d255cf6ffac56425539b8180e4893c7d39e1d38fbfeb6a93e145b1ad9` | `b307c7ffe5eab8a58138fd5d51157b15969c4f2963c1f58f5a9e5a2adbc8cac8` |
| Six-look switch-v2, photo-working but preview intermittent | `690b5f17f21cba5c7cd937e6feb0f6967ea2793c0b4ca6fc1fffdcaa1ed0d761` | `100e286f3d4c308dc4619d8d9630fba3dd7432d73bdbf7eb169c13aa2d30fc58` |
| Six-look upload-retry-v4, current owner-tested candidate | `690b5f17f21cba5c7cd937e6feb0f6967ea2793c0b4ca6fc1fffdcaa1ed0d761` | `90d1ed6d47df21c881936816647973b1562764458122eb72869e60b1a624900b` |

These are research-build identities, not arbitrary factory camera eligibility. The six prefix is file 0x8000 / VA 0x110000:32 B header then six 1215 B tables startingVA0x110020. Header magic0x364c3741, version0x10006, then six FNV32 values. Every selected table is checked before use. Selectors10–15 emit markers249–254 only for base ST0. The original native LUT builder consumes type 1/transform 2 corrections. Segment headers and BSS are unchanged.

Source inspection of the NOR loader found whole-file preload/transfer behavior; controlled bootstrap replay reached main after 63,020 instructions without overwriting the region. Physical six-look effects support activation. This still does not establish arbitrary future allocation safety or a direct CP memory dump. Do not generalize the placement to other firmware or bootstrap variants.

## Conversion workflow

1. Inspect supplied DCP/cube dimensions, domain, hashes and rights. Preserve Sony sensor/body calibration; extract look/tone only. File names suggesting A7C II compatibility do not prove calibration matrices match.
2. Establish a Sony-ST input model using paired linear RAW/ST output and ISP response measurements. Use independent scenes and fixed exposure/WB; Log LUTs require an explicit bridge. The historic owner fits used one scene and a provisional response, not a complete Adobe pipeline.
3. Fit native signed 7-bit tables, report synthetic residuals, clipping, neutral and skin behavior. Preserve source attribution. Native precision retention is not full-DCP mapping retention.
4. Build a selected-slot plan. Import only those slots, provision ST and preserve fresh unselected recipes. The menu is editable; do not claim a hard ST lock. Read saved/runtime bindings separately.
5. Use the appropriate exact-source offline adapter. Six-table replacement updates only selected tables/checksums. The full six program builder requires the pinned historical three-look inputs. Unknown hashes stop; a later table update needs a reviewed new source identity.

## Offline adapters

Run from the extracted tools root. The commands below prepare private artifacts and never connect to USB.

| Command | Exact supported source and output |
|---|---|
| `prepare-transition --layout three-preview-v2` | Data-only replacement of slots 1–3 on the pinned historical three-look source |
| `prepare-transition --layout full7-v4` | Selected slots 1–6 and their checksums on the pinned six-look source |
| `prepare-preview-retry` | Three instruction windows, 44 bytes total, switch-v2 → v4; tables and AP unchanged |
| `prepare-six-program` | Historical three-look preview-v2 plus pinned native FL23 CP and six private tables → guarded full7-v4 programs |

```text
python lut.py prepare-preview-retry "D:\MyLook\appFw.so" "D:\MyLook\switch-v2-cpapp-b.bin" "D:\MyLook\preview-transition"
python lut.py prepare-six-program "D:\MyLook\six-candidate" "D:\MyLook\three-appFw.so" "D:\MyLook\three-cpapp-b.bin" "D:\MyLook\fl23-cpapp-b.bin" "D:\MyLook\bindings.json" "D:\MyLook\six-program-transition"
```

The six-program command emits forward/reverse manifests and `integration-required.json`. It does not provision the 68 resource files, fresh ST settings, native transaction or retained-image state. Unknown source hashes stop. A table update changes CP identity and requires a reviewed adapter for later updates. The retired unguarded `bootstrap6.build` refuses execution. Calibration, fitting and data-transition commands are in [the manual](../manual.md).

## Names, settings and preview

Name resources are separate from programs. This body uses68 language/layout files and full names, with IDs0x0200ab2d/ab2c/ab2e/ab2f/ab30/ab31 in slot order. Do not copy the original assets or per-body backup into a public package. Preserve IDs/layout extents and verify the native reader. A partial import must retain the dynamic getter for unselected slots; the old three-look static-title implementation incorrectly displayed ST for4–6. All six now intentionally imported does not make that old mixed-slot behavior correct.

FL2/FL3 integrate native mode/gamma/chroma/matrix paths, so their preview behavior does not prove a new custom LUT reaches live view. Root+1 is a processing-context field, not a universal synonym for video/photo. Keep gamma-domain parameters distinct.

V4 is a44 B preview-only change at file 0x13553a/4,0xb2750e/18,0xb27578/22. For a validated imported root0 cached table, cache-hit handling reuses native0x23d56c to request re-upload. The native uploader0x42cd28 gates on state+0x24 before 0x78aa20 copies the packed1620 B bank. A simulated omitted submission can advance tags without uploading, then leave later frames stale. V4 retries without rebuilding the bank. This model is not a captured real scheduling trace.

Re-upload may occur on every eligible preview update, not merely when a user changes slots. Ten controlled identical updates yield ten uploads versus one before v4, one build in either case. Do not promise negligible performance/power cost; measure before optimizing. Preserve the switch-v2 correction of an incoming branch into the second half of a B.W instruction. Do not resurrect the withdrawn 4B0xff2f04 notification experiment: its flag is not established as preview invalidation.

## Before and after an authorized device write

Capture fresh complete programs, both settings domains and protected calibration; keep two verified copies, preferably on separate drives. Do not replace a current backup with an older recipe snapshot. Require exact model/version/source, adequate continuous power, whole-file preconditions, tested inverse and native preflight. Name, program and settings changes are separate reviewable transactions.

Use one service session at a time. The LUT layer binds the normal USB serial hash before authentication. Only recognized initial busy states or standard missing-card sense `02/3a/00` allow one guarded service acquisition; complete programs and native model proof precede persistent writes. An opaque HASP response is not a stable body ID. A timeout/disconnect or unknown native result must stop; recover existing result/temporary files rather than replaying a write. Recovery also needs normal USB identity. Do not reinstall drivers just because a response timed out. FL23 transport remains unchanged.

After mutation, verify complete files, size/inode, read-only mount, known-temp cleanup and fresh settings preservation. Compare every writable AP-group `02cf` setting except the known `02cf0b6e` diagnostic value, plus all four protected CP units. Unrelated runtime groups remain backed up and are not compared or written. Missing keys, changed attributes, unselected AP-setting changes and calibration differences still stop installation. The retained-image step is separate: inspect actual mode first. Never blindly rerun a worker expecting mode 2 when mode is already0. Do not use repeated flashing to force a stale runtime to reload.

After all I/O has ended, request one necessary full power-removal/reload test. Verify AP runtime spans, CP complete disk file, saved/runtime recipes, protected units and boot evidence. Kernel boot/file hashes do not prove running CP instructions. Then separately test unpressed-shutter preview switching, photo output/playback and original FL/FL2/FL3. Preserve the owner's distinction: photos may work while preview is stale.

## Publication

No full firmware, calibration/backup, photo, serial, local credential/path or fitted look payload belongs in the public repo. Generated manifests contain private source-derived data. The owner explicitly requested original DCP references in the separate Release attachment; retain their exact bytes, individual attribution and original notices without applying the code MIT license. Publish authored tooling, synthetic fixtures and sanitized evidence. Do not invoke Claude or additional agents without current explicit authorization.
