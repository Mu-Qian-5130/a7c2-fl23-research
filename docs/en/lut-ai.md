# LUT importer: AI reproduction guide

[Home](../../README.md) · [简体中文](../zh-CN/lut-ai.md)

The [user guide](custom-lut.md) is an eight-stage manual workflow. Its device commands are implemented; do not replace installation with offline manifest generation. Read [source rules](../../src/looks/AGENTS.md), [integration](technical/integration.md) and [historical failures](technical/failures.md). FL23's entry and files must remain unchanged.

## Run the user's workflow

```text
python -m pip install -r src/looks/requirements-device.txt
python lut.py doctor --device
python lut.py import "REFERENCE.dcp" --name "DISPLAY NAME" --slot 1
python lut.py install "JOB_PATH" --battery-percent 90
```

The default bridge is a shared one-scene approximation, not factory calibration or a full Adobe renderer. Use `--calibration` for better measurements. CUBE needs its declared ST input or an explicit bridge; never assume a Log cube is ST. Use actual battery readings, not the example value.

After all I/O ends, the user performs the cold reload and preview/new-photo/playback checks. Then run `verify JOB --accept-photos`. Do not manufacture acceptance or infer boot safety from readback/emulation. Restoration uses `restore JOB`, reload and another physical acceptance. Restore chained imports newest-first.

## Implementation map

| Source | Responsibility |
|---|---|
| `devicecli.py`, `devicejob.py` | Human commands; durable job, fitting, duplicate backups, native phases, readback, reload/restore/recovery |
| `device_layout.py`, `assets/runtime-v1.json` | Exact stock/FL23/standalone sources and legacy full7-v4 updates; no arbitrary firmware |
| `devicesession.py`, `usbidentity.py`, `usbservice.py`, `devicelock.py` | Stable normal-USB serial binding, guarded busy-only service acquisition, pinned programs/native model, temporary allowlist and locks |
| `devicesettings.py` | Descriptor-derived ST fields, other AP settings and four protected CP units; runtime telemetry is diagnostic |
| `resources.py`, `nameworker.py`, `native/names.c` | 68-resource atomic inode replacement, selected names, stock2860→2866 extension and exact inverse |
| `nativebuild.py` | Job-pinned native compilation using Zig; no imports, correct ELF/relocations and staging bound |
| `dev/release/build_lut.py` | Single-file bundle with verified extraction; no body data or external inputs |

All paths except the last are under `src/looks`. Programs/names/settings remain separate transactions, even when one command orchestrates them. Original factory calibration/protected CP units are never imported from a DCP or written. The selected base picker remains editable; do not describe it as a hard lock.

## Exact adapter boundaries

- Full7-v4 AP is exact `six.AP_SHA`; CP identity excludes only six table/checksum bytes and pins every other byte. Each job still stores full before/after hashes.
- First install accepts the exact stock or matching FL23 pair listed in `runtime-v1.json`. Standalone AP masks are validated by complete reconstruction; unselected default recipes/caps are preserved. Partial imports retain native dynamic titles.
- The standalone title dispatcher fits the existing132-byte converter window. The old switch's10 entries plus its2-byte aligned padding become the12-entry native map. Its sole page/add consumer, incoming branches, original virtual call site, program headers and relocations were checked offline. This is not physical boot proof.
- First-install CP reuses the v4 runtime with its retired DCP payloads removed and zero tables in unselected positions. Stock AP does not enable FL23 menus; no FL23 color/calibration units are provisioned. Unknown programs stop.
- Resource changes preserve old mmaps via atomic inode replacement. Exact inverse supports original hardlinks or reconstruction. Do not reuse the failed display/segment/icon approach.

## Interrupted operations

Preserve `job.private.json`, both source copies, input/model, candidates, manifests, workers and raw evidence. Never edit a job to advance its phase.

| State | Allowed next action |
|---|---|
| `PREFLIGHT_VERIFIED` | Explicit install |
| `AWAITING_RELOAD` | Physical reload/acceptance, then verify |
| `NEEDS_REVIEW` | Recover existing result only; no loader replay |
| Proven program/name/settings phase | Explicit resume of remaining work |
| `RESTORED_AWAITING_RELOAD` | Reload and verify restoration |

Every reconnect requires the normal Mass Storage USB serial hash to match the job before authentication. A service-only connection stops and requires a normal reconnect. `readHasp()` is diagnostic only: its 88-byte response varies across sessions and cannot identify a body. Legacy jobs without a stable binding cannot be forced forward; retain them and prepare a fresh job. Unknown native output remains untouched. An authenticated failed report can permit continuation only after rollback/read-only evidence and complete source/target classification. Settings comparison covers the writable AP group `02cf` and all four protected CP units. The known `02cf0b6e` diagnostic value and unrelated runtime groups are backed up but do not block installation; their values are never written.

If the initial storage query stays in recognized busy states or standard missing-card sense `02/3a/00`, the LUT layer can acquire service access once. USB timeouts, unknown sense codes and other manufacturers stop. On a first capture, complete AP/CP files must match a supported layout before the pinned read-only probe confirms native model index 16. No program/name/settings write is allowed before that confirmation. FL23 transport source is unchanged.

## Reproduce tests and package

```text
python -m unittest discover -s tests -v
```

Run that from `src/looks`. Optional instruction/native replay dependencies are in `requirements-research.txt`. Exact full-image tests require private owner fixtures through `A7C2_RESEARCH_FIXTURES`; absence means skipped, not passed. From root also run the existing FL23 and host suites, `dev/release/check_publication.py`, then `dev/release/build_lut.py` and test the emitted standalone CLI.

Separate software tests, exact-image reproduction, device readback, loaded state, physical camera behavior and Mac USB acceptance in every report. No physical-camera or physical-Mac acceptance was performed for this new importer. Do not weaken source checks to finish a demonstration.
