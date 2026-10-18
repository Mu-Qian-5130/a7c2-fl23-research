# Validation and limits — October 18, 2026

[Home](../../../README.md) · [简体中文](../../zh-CN/technical/validation.md)

## Physical observations

| Item | Evidence | Limit |
|---|---|---|
| FL2/FL3 | Owner previously captured and replayed FL2/FL3/ST successfully | One body; portable frontend not independently installed on a second body |
| Six imported looks | Owner confirmed normal photo output and six-name operation | Color differences are not Fuji/Ricoh pixel-equivalence measurements |
| Earlier six preview | Owner repeatedly reported stale viewfinder colors; pressing shutter restored display | Photos were already correct; this was a preview problem |
| Preview v4 | Owner says current repeated switching tests appear normal | No measured duration/count or frame recording; long-term stability not established |
| Startup | Owner clarified slower startup happened only the first time after power removal, then said it was fine | No timed boot benchmark or persistent slowdown demonstrated |

V4 installation completed native and independent host full-file readbacks, AP 24-span checks,54 selected recipe checks, four protected CP-unit comparisons, original read-only mount and temporary-file cleanup. Fresh before/after complete setting preservation passed. The retained-image state was already0 from the preceding invalidation and was verified read-only; the mode 2→0 worker was not blindly repeated.

Those checks preceded the owner's physical v4 report. A separate v4 post-reload machine check has not yet been recorded. Earlier switch-v2 had a new-kernel-boot check and fullCP readback. Neither stage directly captured running CP instructions or tables. Do not silently relabel earlier evidence as a newer build's runtime verification.

## Color and precision

Six owner-supplied DCP fits use NC/CC/NN/Eterna/GR-positive/GR-negative order. Fuji LookTables are72×12×16; Ricoh90×16×16, both with sRGB value axis and128 tone points. Only look/tone stages are used. Sony physical calibration is retained even where Ricoh profile matrices differ.

Each native table is5×9×9×3 signed 7-bit corrections,1215 bytes; six total 7290 plus32 header bytes. No additional coefficient precision reduction was installed. A previous lower-precision experiment was abandoned. Native-grid fitting does not retain all original high-resolution DCP entries.

Historic same-scene spatial holdout used2293 patches with mean encoded RGB fit errors around 0.0057/0.0042/0.0044/0.0035/0.0042/0.0038. These diagnose fitting against a provisional one-scene rendering model; they are not an end-to-end camera-match score or independent-scene validation. The public fit CLI may produce different candidates and must report its own calibration and error.

## Preview and native tests

V4 uses three instruction windows totaling44 B. Native query/controller/uploader tests cover48 lost-submission reproductions, four random120-frame schedules,38 native/snapshot comparisons, six direct-path comparisons, and invalid-storage/effect-disabled/missing-bank cases. Source fails the controlled omitted-submission case; v4 restores exact packed1620 B bytes on later submits. Memcpy and interrupt barriers are modeled. Actual camera scheduling and hardware timing are not captured.

The existing text extent and generated native mapper were checked; segment/BSS boundaries do not move. A direct-branch audit checks overwritten instruction boundaries. A byte pattern decoded as a branch inside an identified old raw table was classified as data, not ignored as an unexplained executable reference.

Re-submitting a cached table costs extra transfers. Ten identical controlled updates: source1 upload/v410 uploads, both1 build. CPU load, frame rate, power, heat and video behavior remain uncharacterized. A single positive switch test does not settle these questions.

The native transaction worker passed16 controlled install/restore/failure cases. Complete on-camera and host readbacks are additional evidence, not a full RTOS/ISP/boot emulator or a guarantee of power-loss recovery.

## Public reproducibility

Public tests cover DCP/cube parsing, color domains, ST ownership, fitting, range/plane order, selected-slot checksum updates, strict fingerprints, exact reverse transitions and output preservation. Research tests add AArch64/Thumb hooks. Optional private-fixture tests reproduce the complete installed AP 690b5f17… and CP 90d1ed6d… from the same private sources without distributing them, and test the44 B preview transition plus slot6 data replacement. These tests do no USB I/O.

The original host USB support subset has 22 offline tests: readiness/busy bounds, initial-query recovery, timeout-stop behavior, no identity authentication, unchanged service/write AST and atomic updater/original-backup guards. The single-file Windows updater was also verified offline. No other user's completed camera installation is inferred from those tests.

## Unfinished validation

- Independent v4 post-reload machine evidence and longer randomized physical preview runs.
- Multi-scene/color-chart characterization, skin/neutral/high-saturation accuracy and direct preview/photo comparison.
- Other bodies, region/settings combinations, RAW/HEIF/burst/video regressions, durability and power/heat/frame-rate effects.
- A camera-menu ST lock, if desired; the current gate is not a lock.
- Physical acceptance of the implemented portable importer/stock adapter; Mac USB installation.
- Future official firmware compatibility. Current offsets/hashes do not carry across upgrades.

See [failures.md](failures.md) for the restart-loop incident and withdrawn candidates. No claim of universal stability or guaranteed recovery is made.

The current two-entry publication additionally passed 38 host/launcher tests, 35 look-toolkit tests and 8 FL23 offline tests. These are offline software checks, not another camera installation.

## New importer: software evidence only

The implemented job flow has simulated import/readback/reload/acceptance/exact-restore and lost-completion/partial-settings/reverse-continuation coverage. Offline first-import tests cover exact stock and FL23 sources and arbitrary later slot additions. The new title/converter replay covers all64 masks, 13,824 title cases (native base getter controlled) and11,648 converter cases, with no external direct branch into replaced interiors. Both stock/update resource workers passed32 native syscall/fault cases each, using official file ownership. All68 original and68 six-look resource files were transformed/inverted exactly. An actual DCP fit compiled a22,472-byte first-install worker; these results include no camera USB I/O.

The public importer, first-install AP/CP and single-file runtime have not been physically installed/boot-tested in this implementation session. Mac dependency wheel availability was checked; physical Mac execution/USB remains untested. Shared appearance-model residuals are not full DCP fidelity or independent-scene calibration.
