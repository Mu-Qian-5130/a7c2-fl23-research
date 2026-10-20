# Pixel Shift research — development branch

[Home](../../README.md) · [简体中文](../zh-CN/pixel-shift.md)

Target: the native Sony workflow used by A7CR: tripod, static subject, four shifted RAW captures, then computer composition. Sixteen-shot support is a later goal. Published programs are **offline research, not an installable or working Pixel Shift release**.

On October 20, two owner-authorized three-byte RAM trials exposed the menu but left it disabled. The second used an SD card and still-photo P/M mode, so the missing card does not explain the failure. Both trials were restored and independently checked; neither captured images.

Further disassembly found a separate, undefined C2 parameter-capability entry. The original initializer adds four inhibition tokens for that entry, matching the live read-only counters. Ten ordinary exclusion rules were decoded; none applied to the observed still-M, idle state. A third private trial supplied a C2-native parameter definition and removed only those four unsupported-definition tokens, alongside the menu gate: six AP data windows, 47 bytes. Independent readback passed, but the owner entered an empty submenu before shutting down. Subsequent read-only inspection confirmed all six fields back at their original values; no inverse write was needed. No capture occurred.

The individual submenu options have another model-support table. A fourth RAM trial added off/four support: eight windows, 51 bytes; sixteen stayed hidden. Readback passed, but the owner reported missing icons and later camera errors/blackouts. The volatile tables reverted after power loss while the native four-shot setting remained saved. No capture was reported. The owner subsequently recovered the camera by an unrecorded method. Independent follow-up reads confirmed running mode, RAM Backup and saved Backup all OFF, and the owner confirmed 30 seconds of normal unplugged live view. The candidate remains withdrawn; this is not Pixel Shift or long-term hardware validation. The trial did not edit ROM, CP or calibration, but the native menu did persist a setting. Private device workers are not distributed here.

## Implemented

- [Call-path audit](../../dev/pixelshift/audit.py): resolves Pixel Shift sequence RTTI and actual virtual methods in privately extracted C2/A7CR 2.01 application programs. It checks sequence → wrapper → generic capture packet builder and finds code references to named Pixel Shift routines.
- [Original-instruction replay](../../dev/pixelshift/native_replay.py): four/sixteen-shot selection matches A7CR in 18 paired cases; generic capture command `0x4036` matches in 44 paired packet cases. Selection stops before Bluetooth feedback configuration. Packet replay omits one diagnostic trace and stops before transport send. No hardware operation is given a simulated success.
- [Native mode setup](../../dev/pixelshift/trinity_replay.py): the firmware calls Pixel Shift `TRINITY`. Original command `0x40ee` and CP mode assignment match in 20 paired cases, including off, four/sixteen shots, intervals and the native test flag. The CP slice assigns the mode only; it does not demonstrate actuator control.
- [CP command dispatch](../../dev/pixelshift/cp_dispatch_replay.py): 80 paired cases execute the original command table lookup, optional consistency callback, mode handler and parameter-change flag setter on AP-built `0x40ee` packets. Initial RAM and pending-check fields are synthetic; only diagnostic printing is omitted. Transport, the CP scheduler and capture are not executed.
- [CP configuration snapshot](../../dev/pixelshift/cp_config_replay.py): eight paired cases carry that handler-written mode, in the same emulator RAM, through the native snapshot routine and its original ARM `memcpy`. All 3428 copied bytes match. LiRo field `+0x180` becomes capture-configuration field `+0x1a0`; the mode is not assigned again by the test. Other input fields and snapshot arguments are synthetic, and scheduling between the two entries is not executed.
- [CP frame propagation](../../dev/pixelshift/cp_frame_replay.py): 24 paired cases extend that same RAM through the original frame mapper, carrying the mode to frame `+0x98`, then through a later control-flag setter and request-selection slice. The frame's `+0x20` view explains the setter's `+0x78` access. Preparation gates, other fields and branch inputs are outside the replay or synthetic; later request overrides and transport are not executed. The selected value is not an identified actuator command.
- [CP per-frame selection](../../dev/pixelshift/cp_sequence_replay.py): 64 paired cases execute original state-byte getters, the selector and its 17-record descriptor initializer. In mode 23, all four frame ordinals select the same first-column sequence, whereas ordinary mode 2 can select subsequent-frame columns. The test stops before sequence configuration; selected callbacks, exposures and positioning are not executed.
- [Sequence/clear boundary replay](../../dev/pixelshift/lifecycle_replay.py): 22 paired cases verify the original still-record factory request, its enqueue gate, the `0x40ef` clear packet and the CP descriptor referring to `TrinityShotEnd`. C2 and A7CR use their own manager addresses. Synthetic state and omitted mutex/diagnostic calls are explicit; execution stops before allocation, construction, transport or the clear service. Neither callback completion nor physical centering is verified.
- [CP metadata replay](../../dev/pixelshift/cp_metadata_replay.py): 63 paired cases verify original group-ID, shot-ordinal and frame-count emission into an already allocated six-byte `PixelShiftInfo` field. Frame state is synthetic; no sensor is emulated.
- [CP capture-mode replay](../../dev/pixelshift/cp_capture_replay.py): 63 paired cases execute original configuration selection and TRINITY consistency checks. Given native configuration byte `0xd88`, mode 2 can become mode 23; a synthetic native-state byte can prevent conversion. TRINITY is cleared when the selected mode is incompatible. No capture or actuator call is executed; the AP-to-configuration-byte source remains unverified.
- [CP timing replay](../../dev/pixelshift/cp_timing_replay.py): eight paired cases trace `SetSteadyCapTimer` up to timer creation. The requested delay is the exposure offset minus 9000 microseconds, falling back to one microsecond below that boundary; the callback is `eventCallback_End_Wait_StartSteadyCap`. This establishes a timer-based scheduling path, not a sensor-position acknowledgement. Timer/event APIs are not executed.
- [Capability descriptor replay](../../dev/pixelshift/capability_replay.py): 52 paired cases execute the original model mapping and descriptor reader. C2 model input 16 maps to column 9, where the relevant Pixel Shift support is off. A two-byte change enables this flag in emulation. Live capability caches and hardware are outside this test; no patch file is generated, and an A7CR identity is not guessed from an index.
- [Individual-option replay](../../dev/pixelshift/option_replay.py): 78 paired cases execute the original model-based child visibility getter. Child descriptors use a different field offset from the parent and require the value exactly 1. C2's three rows are hidden; an emulated off/four-only change permits those two while leaving sixteen hidden. This does not execute live permissions, cached state, menu rendering or capture.
- [Parameter eligibility replay](../../dev/pixelshift/eligibility_replay.py): 26 additional original-instruction cases distinguish menu support, a defined parameter and accepted values. C2's permissive fallback accepts values without defining the feature; A7CR defines off/four/sixteen. Replaying C2 initialization with synthetic registries records four inhibition notifications; an emulated native definition removes those requests. The notifier is observed, not executed. The audit also decodes ten incoming rules, retaining restrictions such as AUTO/movie mode, capture encoding and AF-ON.
- [RAW group inspector](../../dev/pixelshift/raw_group.py): reads Sony `PixelShiftInfo` (`0x202f`), checks four unique source shots and exposure metadata, and rejects ordinary bursts, mixed groups and composite images. Passing metadata does not prove physical displacement or compatible composition.
- [RAW displacement measurement](../../dev/pixelshift/displacement.py): compares both green Bayer sublattices, measures fractional translation and checks for a one-pixel square. Independent synthetic scenes pass; no-motion, wrong-spacing and bad-frame cases fail. Real ordinary C2 RAW decoding has been checked, but no real Pixel Shift sequence is available yet. Camera/scene movement can imitate this image evidence; it cannot certify motor position or settling.

The sequence's virtual `run()` addresses are C2 `0x348bcf0` and A7CR `0x348c1b8`. C2 `0x34d1508` calls builder `0x353a260`; A7CR `0x34d19f0` calls `0x353a748`. These are research addresses, not write locations. The generic command is also used outside Pixel Shift. Do not issue it to the camera based on this audit.

The reference-first CP trace now connects mode dispatch to the configuration snapshot and per-frame sequence selection. A7CR's `0x4036` capture request uses destination `0x90040193`, separate from the `0x40ee` parameter destination `0x90030001`. The native frame builder retains one group object across TRINITY frames, and `TrinityShotEnd` resets the ordinal and releases that object. These are software lifecycle facts, not proof of sensor movement or centering. A previously inspected `+0xb8` to `+0x1a0` copy is a configuration serialization helper, not the primary source of TRINITY mode. Offset matches in unrelated structures are insufficient evidence.

## Virtual-machine observations

Experiments using [a7c2-re](https://github.com/chocotan/a7c2-re) run the original AP with limited virtual services. The native menu displayed Off/Shoot 4 Shots and rejected FOUR in Intelligent Auto, leaving mode and virtual Backup OFF. An early forced-menu profile lacked sequence `0x4bd` and later faulted in `sequence_still_record::suspend(NULL)`. A separate normal-boot run did create `0x4bd` with the correct native vtable; a nonzero cache alone was followed through its metadata to verify the ID. Its UI was still black and a MENU input did not advance the frame. Thus the early-profile failure does not establish a missing C2 implementation or the cause of the physical incident. Complete boot, P/M input, FOUR selection, saved-ON/menu-hidden recovery and capture remain unverified. Sensor/IBIS behavior is outside the available model.

A separate guest RAM enable/restore cycle matched all eight original fields after restoration, with mode/virtual Backup OFF throughout. It removed/re-added only the four undefined-parameter tokens while retaining the AUTO counters. This tests the RAM inverse, not saved-ON recovery, flash persistence or physical restoration.

## Reproduce offline

Use Python 3.10+ and install the [research requirements](../../dev/pixelshift/requirements.txt):

```text
python -m pip install -r dev/pixelshift/requirements.txt
python dev/pixelshift/audit.py --c2 private/c2/components --reference private/a7cr/components --output private/audit.private.json
python dev/pixelshift/native_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/replay.private.json
python dev/pixelshift/trinity_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/trinity.private.json
python dev/pixelshift/cp_dispatch_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-dispatch.private.json
python dev/pixelshift/cp_config_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-config.private.json
python dev/pixelshift/cp_frame_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-frame.private.json
python dev/pixelshift/cp_sequence_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-sequence.private.json
python dev/pixelshift/lifecycle_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/lifecycle.private.json
python dev/pixelshift/cp_metadata_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/metadata.private.json
python dev/pixelshift/cp_capture_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-capture.private.json
python dev/pixelshift/cp_timing_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-timing.private.json
python dev/pixelshift/capability_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capability.private.json
python dev/pixelshift/option_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/options.private.json
python dev/pixelshift/eligibility_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/eligibility.private.json
python dev/pixelshift/raw_group.py source.ARW
python dev/pixelshift/raw_group.py 1.ARW 2.ARW 3.ARW 4.ARW --validate-four
python dev/pixelshift/displacement.py 1.ARW 2.ARW 3.ARW 4.ARW --output private/displacement.private.json
python -m unittest discover -s dev/pixelshift/tests -v
```

On macOS use `python3`; Mac execution has not been tested. Without private firmware, seventeen original-firmware tests skip. To include them, set `A7C2_PIXELSHIFT_FIRMWARE_ROOT` to the private firmware root containing `a7c2-2.01/components` and `a7cr-support/components`. Twenty-six test methods cover 544 paired native cases, 26 additional eligibility cases, synthetic metadata failures and displacement checks. A real ordinary C2 RAW was correctly identified as having no Pixel Shift group. Displacement measurement uses `rawpy`, retains the original Bayer samples, and requires four source RAWs passing the metadata contract.

## Remaining work

Keep the withdrawn physical trial disabled. Continue the normal virtual boot/menu lifecycle and per-shot CP/stabilizer tracing. Establish positioning units, settle completion and exposure synchronization; verify return-to-center on completion/cancellation. Before another physical test, prepare an independently reviewed candidate with an OFF path that remains available after power loss and a precise inverse. Actual displaced RAWs, group/calibration metadata and compatible composition are still required. Neither five-axis stabilization nor shared names establishes positioning support; no installable patch is provided yet.

Do not enable a menu alone, copy A7CR body calibration, forge RAW group tags/model names, or call ordinary bursts Pixel Shift. Keep firmware, original RAWs and generated reports private. Main and Releases are unchanged.

Native references: [A7CR Pixel Shift guide](https://helpguide.sony.net/ilc/2370/v1/en/contents/0414M_pixel_shift_shooting.html), [Sony composition workflow](https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/1_2_about_psm.php).
