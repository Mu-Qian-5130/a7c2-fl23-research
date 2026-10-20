# Pixel Shift research — development branch

[Home](../../README.md) · [简体中文](../zh-CN/pixel-shift.md)

Target: the native Sony workflow used by A7CR: tripod, static subject, four shifted RAW captures, then computer composition. Sixteen-shot support is a later goal. Published programs are **offline research, not an installable or working Pixel Shift release**.

On October 20, two owner-authorized three-byte RAM trials exposed the menu but left it disabled. The second used an SD card and still-photo P/M mode, so the missing card does not explain the failure. Both trials were restored and independently checked; neither captured images.

Further disassembly found a separate, undefined C2 parameter-capability entry. The original initializer adds four inhibition tokens for that entry, matching the live read-only counters. Ten ordinary exclusion rules were decoded; none applied to the observed still-M, idle state. A third private trial supplies a C2-native parameter definition and removes only those four unsupported-definition tokens, alongside the menu gate: six AP data windows, 47 bytes. Independent readback confirms the definition and cleared inhibition; manual menu/capture testing is pending. The retained-image cache was cleared first. No instructions, firmware files, CP or calibration were changed. Physical displacement remains unverified. Private device workers are not distributed here.

## Implemented

- [Call-path audit](../../dev/pixelshift/audit.py): resolves Pixel Shift sequence RTTI and actual virtual methods in privately extracted C2/A7CR 2.01 application programs. It checks sequence → wrapper → generic capture packet builder and finds code references to named Pixel Shift routines.
- [Original-instruction replay](../../dev/pixelshift/native_replay.py): four/sixteen-shot selection matches A7CR in 18 paired cases; generic capture command `0x4036` matches in 44 paired packet cases. Selection stops before Bluetooth feedback configuration. Packet replay omits one diagnostic trace and stops before transport send. No hardware operation is given a simulated success.
- [Native mode setup](../../dev/pixelshift/trinity_replay.py): the firmware calls Pixel Shift `TRINITY`. Original command `0x40ee` and CP mode assignment match in 20 paired cases, including off, four/sixteen shots, intervals and the native test flag. The CP slice assigns the mode only; it does not demonstrate actuator control.
- [CP metadata replay](../../dev/pixelshift/cp_metadata_replay.py): 63 paired cases verify original group-ID, shot-ordinal and frame-count emission into an already allocated six-byte `PixelShiftInfo` field. Frame state is synthetic; no sensor is emulated.
- [CP capture-mode replay](../../dev/pixelshift/cp_capture_replay.py): 63 paired cases execute original configuration selection and TRINITY consistency checks. Given native configuration byte `0xd88`, mode 2 can become mode 23; a synthetic native-state byte can prevent conversion. TRINITY is cleared when the selected mode is incompatible. No capture or actuator call is executed; the AP-to-configuration-byte source remains unverified.
- [Capability descriptor replay](../../dev/pixelshift/capability_replay.py): 52 paired cases execute the original model mapping and descriptor reader. C2 model input 16 maps to column 9, where the relevant Pixel Shift support is off. A two-byte change enables this flag in emulation. Live capability caches and hardware are outside this test; no patch file is generated, and an A7CR identity is not guessed from an index.
- [Parameter eligibility replay](../../dev/pixelshift/eligibility_replay.py): 26 additional original-instruction cases distinguish menu support, a defined parameter and accepted values. C2's permissive fallback accepts values without defining the feature; A7CR defines off/four/sixteen. Replaying C2 initialization with synthetic registries records four inhibition notifications; an emulated native definition removes those requests. The notifier is observed, not executed. The audit also decodes ten incoming rules, retaining restrictions such as AUTO/movie mode, capture encoding and AF-ON.
- [RAW group inspector](../../dev/pixelshift/raw_group.py): reads Sony `PixelShiftInfo` (`0x202f`), checks four unique source shots and exposure metadata, and rejects ordinary bursts, mixed groups and composite images. Passing metadata does not prove physical displacement or compatible composition.
- [RAW displacement measurement](../../dev/pixelshift/displacement.py): compares both green Bayer sublattices, measures fractional translation and checks for a one-pixel square. Independent synthetic scenes pass; no-motion, wrong-spacing and bad-frame cases fail. Real ordinary C2 RAW decoding has been checked, but no real Pixel Shift sequence is available yet. Camera/scene movement can imitate this image evidence; it cannot certify motor position or settling.

The sequence's virtual `run()` addresses are C2 `0x348bcf0` and A7CR `0x348c1b8`. C2 `0x34d1508` calls builder `0x353a260`; A7CR `0x34d19f0` calls `0x353a748`. These are research addresses, not write locations. The generic command is also used outside Pixel Shift. Do not issue it to the camera based on this audit.

## Reproduce offline

Use Python 3.10+ and install the [research requirements](../../dev/pixelshift/requirements.txt):

```text
python -m pip install -r dev/pixelshift/requirements.txt
python dev/pixelshift/audit.py --c2 private/c2/components --reference private/a7cr/components --output private/audit.private.json
python dev/pixelshift/native_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/replay.private.json
python dev/pixelshift/trinity_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/trinity.private.json
python dev/pixelshift/cp_metadata_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/metadata.private.json
python dev/pixelshift/cp_capture_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/cp-capture.private.json
python dev/pixelshift/capability_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/capability.private.json
python dev/pixelshift/eligibility_replay.py --c2 private/c2/components --reference private/a7cr/components --output private/eligibility.private.json
python dev/pixelshift/raw_group.py source.ARW
python dev/pixelshift/raw_group.py 1.ARW 2.ARW 3.ARW 4.ARW --validate-four
python dev/pixelshift/displacement.py 1.ARW 2.ARW 3.ARW 4.ARW --output private/displacement.private.json
python -m unittest discover -s dev/pixelshift/tests -v
```

On macOS use `python3`; Mac execution has not been tested. Without private firmware, ten original-firmware tests skip. To include them, set `A7C2_PIXELSHIFT_FIRMWARE_ROOT` to the private firmware root containing `a7c2-2.01/components` and `a7cr-support/components`. Nineteen test methods cover 260 paired native cases, 26 additional eligibility cases, synthetic metadata failures and displacement checks. A real ordinary C2 RAW was correctly identified as having no Pixel Shift group. Displacement measurement uses `rawpy`, retains the original Bayer samples, and requires four source RAWs passing the metadata contract.

## Remaining work

Verify the new RAM trial through the native menu, then continue per-shot configuration and CP/stabilizer tracing. Establish positioning units, settle completion and exposure synchronization; verify return-to-center on completion/cancellation. Then verify actual displaced RAW samples, group/calibration metadata and a compatible composer. Neither five-axis stabilization nor shared names establishes half-pixel positioning support. No installable patch is provided until these paths are understood.

Do not enable a menu alone, copy A7CR body calibration, forge RAW group tags/model names, or call ordinary bursts Pixel Shift. Keep firmware, original RAWs and generated reports private. Main and Releases are unchanged.

Native references: [A7CR Pixel Shift guide](https://helpguide.sony.net/ilc/2370/v1/en/contents/0414M_pixel_shift_shooting.html), [Sony composition workflow](https://support.d-imaging.sony.co.jp/app/imagingedge/en/instruction/1_2_about_psm.php).
