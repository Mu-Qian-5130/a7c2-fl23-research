# Electronic shutter sound: native implementation research

[Home](../../../README.md) · [简体中文](../../zh-CN/technical/shutter-sound.md)

Branch: `feature/electronic-shutter-sound`, based on main commit `80959db`. **Not an enabled feature or an installer.** No camera I/O, sound playback or firmware/settings change has been performed for this branch.

## Goal and reference

Reuse Sony's existing shutter sounds and capture-timed playback, as on [A1 II](https://helpguide.sony.net/ilc/2440/v1/en/contents/231h_audio_signal_volume.html). Electronic shutter selection and Silent Mode are separate: C2's [Silent Mode](https://helpguide.sony.net/ilc/2360/v1/en/contents/0414D_silent_mode_setting.html) locks shooting sounds off. A valid implementation must keep that behavior and must not play a sound merely because a button was pressed or a RAW file appeared.

The [service-preload project](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a) was read at commit `1619f938663a36d41e72302a8cfee89a0f6acd1a`. It documents USB/Senser authentication, Jiritsu path handling and one-shot root-child preload execution. It contains no shutter-sound implementation. Child execution does not establish access to CP state or capture synchronization; a permanent patch still needs a separate implementation and recovery plan. Its documentation is CC BY-SA 4.0; no upstream implementation code or Sony sound files are copied into this repository.

## Verified offline findings

- C2 firmware 2.01 includes `beeplist.txt`, `SysSound.bin`, KA/SHA sounds and several 10 fps shutter variants. Its 71 registry rows contain 11 backed PIN entries; A1 II 4.00 has 73 rows and 9 backed PIN entries. Every registered resource with a concrete size/offset matched its packed bytes. This proves storage, not audible output.
- C2 AP property-name tables identify shooting audio as `02cf048b` and the derived menu beep setting as `02cf00c6`. An existing owner backup recorded `00` and `01000000`, respectively; historical values are not current live evidence. The native four-way setting dispatch is present. Setting these fields arbitrarily is not an activation fix.
- C2 CP has native capture start/end selection at `0x4a09f4` / `0x4a0a74`, capture dispatch at `0xb19e5c`, and a sound-request routine at `0xb0a02e`. Direct-call inspection connects these sites. There are other guards and asynchronous consumers; complete exposure-to-speaker behavior has not been traced.
- The original C2 predicate at `0x67f692` and A1 II counterpart at `0x6d17fc` both return true only for the tested request-state `2` and sound-mode `3`. Thirty synthetic input cases per body executed the original Thumb instructions and original leaf getters. No playback routine or successful capture was mocked. These numeric state meanings are not promoted to a complete camera-state model.

The C2 SPOT continuous-length token is literally `4.00E+00`; the inspector retains the text rather than inventing a corrected length. A1 II contains RESERVE/barcode aliases sharing IDs; placeholder rows are retained. Native IDs/offsets differ between bodies and must not be copied blindly.

## Reproduce without a camera

Supply private, extracted original AP/CP files and the original `avsystemsound` directory. Do not publish firmware, body settings or sound assets.

```text
python dev/shutter_sound/inspect_native.py --ap appFw.so --cp cpapp-b.bin --sounds avsystemsound --output report.private.json
python dev/shutter_sound/verify_predicate.py cpapp-b.bin --output predicate.private.json
python -m unittest discover -s dev/shutter_sound/tests -v
```

The predicate test requires `unicorn`. For A1 II comparisons, pass `--model a1ii-4.00`. Inspection checks original resource bytes and native property descriptors without a whole-firmware hash whitelist. Reports and original bytes stay private. This CLI has no install command and never opens USB.

## Remaining implementation work

Establish where an actual electronic exposure loses its sound event: AP configuration, capture event generation, native PIN routing or output selection. Check against the donor's real call chain and C2 live configuration before changing instructions. Preserve Silent Mode, audio-off, movie audio and normal mechanical-shutter behavior. Then prepare one narrowly scoped reversible change, verify its inverse offline, and validate single-shot/burst timing and sound output on the camera. A root-child preload or a passing readiness predicate cannot replace those steps.
