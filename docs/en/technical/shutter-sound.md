# Electronic shutter sound: hardware-test candidate

[Home](../../../README.md) · [简体中文](../../zh-CN/technical/shutter-sound.md)

Branch: `feature/electronic-shutter-sound`, based on `80959db`. **A controlled test candidate is prepared; audible sound and camera stability remain unverified.** All work on this branch has been offline. Main and Releases are unchanged.

## Candidate and evidence

One two-byte CP Thumb instruction changes at file offset `0x3935ca` / runtime address `0x49b5ca`: `0021` → `0321`. Only the immediate byte differs. C2's ordinary electronic-shutter branch clears sound mode to zero after a sensor-descriptor query; the corresponding A1 II branch selects mode 3. This candidate retains the query and selects mode 3 too, using the existing kind-3 capture-sound dispatch. It edits no AP program, menu, audio setting, sound resource or calibration, and adds no runtime memory hook.

The first physical operation is a **read-only sound-registry preflight**. It must find populated kinds 1/2/3 (KA/SHA/KASHA) in native AP sound entries 0–5, which the original Audio Signals Off policy unregisters. A mismatch stops before firmware writes. Speaker routing, Silent Mode, sound-off behavior and capture timing still need physical tests.

| Offline check | Result and boundary |
|---|---|
| [AP/CP input fragments](../../../dev/shutter_sound/verify_selector_inputs.py) | Eight combinations propagate an electronic request to ordinary selector 1; six check precedence. Executes the actual model-feature lookup, setter and snapshot-copy instructions. Async propagation is not simulated. |
| [Selector differential](../../../dev/shutter_sound/trace_selector.py) | 300 synthetic cases / 600 original-and-trial executions. Other selectors, skip/defer guards and counter policy remain intact; async consumers are not fully simulated. |
| Original AP audio policy | Four traces observe registration arguments without performing registration. Live kind-3 binding remains a required preflight. |
| [Compiled transaction](../../../dev/shutter_sound/verify_worker.py) | 18 syscall-emulation cases: preflight, write, inverse, partial I/O, conflicts, readback corruption, rollback success/failure and mount failures. No camera/power-loss model. |
| [Compiled reader](../../../dev/shutter_sound/verify_probe.py) | Six synthetic-process tests; no live registry evidence. |
| Unit/workflow tests | 24 passed; workflow transport is mocked. |

C2 has 71 registry rows and 11 backed PIN resources, including KA/SHA/10fps; A1 II has 73 rows and 9 backed PIN resources. Concrete ranges match `SysSound.bin` byte for byte. File presence is not playback proof. The [A1 II feature](https://helpguide.sony.net/ilc/2440/v1/en/contents/231h_audio_signal_volume.html) is the donor reference; C2 [Silent Mode](https://helpguide.sony.net/ilc/2360/v1/en/contents/0414D_silent_mode_setting.html) must continue to disable shooting sounds.

## Offline reproduction

From this branch's repository root, using Python 3.10+ and privately extracted C2 2.01 components:

```text
python -m pip install -r src/looks/requirements-device.txt unicorn
python dev/shutter_sound/verify_selector_inputs.py --ap appFw.so --cp cpapp-b.bin --output inputs.private.json
python dev/shutter_sound/trace_selector.py cpapp-b.bin --output selector.private.json
python dev/shutter_sound/candidate.py --ap appFw.so --cp cpapp-b.bin --output private-candidate
python dev/shutter_sound/verify_worker.py --plan private-candidate/plan.private.json --output transaction.private.json
python dev/shutter_sound/verify_probe.py --worker private-candidate/probe.so --ap appFw.so --output reader.private.json
python -m unittest discover -s dev/shutter_sound/tests -v
```

[candidate.py](../../../dev/shutter_sound/candidate.py) never opens USB. Relevant instruction conflicts stop preparation, without whole-firmware hash admission. Output includes a private CP candidate and native transaction, read-only registry and retained-image workers; it is not a Sony-signed SD-card update.

## Controlled physical test

These [developer trial commands](../../../dev/shutter_sound/trial.py) are separate from the FL23/LUT tools. Use the existing [USB setup](../fl23.md), a fully charged battery and stable connection. First select P/A/S/M, electronic shutter, Silent Mode Off and Audio Signals On, noting the original settings.

```text
python dev/shutter_sound/trial.py preflight --firmware 2.01 --job private-shutter-job --backup-copy separate-backup-folder
python dev/shutter_sound/trial.py status --job private-shutter-job
python dev/shutter_sound/trial.py apply --job private-shutter-job
```

1. **Preflight:** binds the body through the service-first USB session, reads current programs and saved/live settings, reconstructs two compressed backups, checks relevant instructions, then runs the temporary registry reader, retained-image inspection and native mode-0 program check. No firmware, shooting-setting or retained-image write. Proceed only at phase `ready`.
2. **Apply:** reads fresh programs/settings, repeats registry and native mode-0 checks, writes only the two-byte instruction, compares both complete programs with the expected fresh result and checks writable AP settings/protected CP units. Other FL23/LUT changes are preserved. No firmware SHA whitelist.
3. **Reload:** after successful readback, retained-image mode 2 uses the existing drop-then-mode-0 sequence; mode 0 is left alone. End all USB I/O, shut down normally, wait for the access light, disconnect USB/other power and remove the battery for at least one minute. Disk readback or a new kernel boot is not direct CP RAM proof.
4. **Validate:** first one electronic exposure with sound and a saved image; half-press/cancel must not add a shutter sound. Then test Lo/Hi/Hi+ bursts, sound Off, Silent Mode On, mechanical shutter/EFCS, AF beeps, movie audio, FL2/FL3/custom looks and playback. Record delay, missed/extra sounds and faults. One successful exposure does not establish stability.

Restore just this instruction, preserving later unrelated edits:

```text
python dev/shutter_sound/trial.py restore --job private-shutter-job
```

Restore also uses fresh bytes, native preflight, full readback, settings checks and retained-image handling. Unknown outcomes become `needs_review`; the CLI never blindly repeats, restores or power-cycles them. Keep the original job/native reports for inspection. This narrow inverse is separate from [complete Recovery](../recovery.md).

## Custom sound import

[custom_sound.py](../../../dev/shutter_sound/custom_sound.py) remains an **offline prototype**. Same-size native BIN replacement updates bank/resource aliases with a compressed byte inverse; a real 1,216-byte resource round-tripped exactly. The native codec is unidentified, so arbitrary BIN data is not validated audio.

Mono PCM16 WAV extraction produces an LPCM registration template without resampling. Original AP supports ADPCM=0 / LPCM=1; [96 native-instruction cases](../../../dev/shutter_sound/verify_registration.py) match its 40-byte ABI before external send. PCM rate/layout, buffer lifetime and hardware playback remain unresolved. The synthetic 24kHz test is not a confirmed camera rate.

Identical 66,368-byte `SysSound.bin` copies exist in rootfs and `nflasha8`; active loading/caching is unresolved. **This trigger trial replaces neither copy and installs no WAV.** Native shutter sound should be tested before independently extending custom decoding/loading.

## Reference boundary

[service-preload](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a), pinned at `1619f938663a36d41e72302a8cfee89a0f6acd1a`, documents USB/Senser/Jiritsu and one-shot root-child preload, not shutter sound. This candidate uses this repository's existing temporary `libJit.so` transaction loader, without permanent preload. No upstream implementation or Sony audio is copied; the reference documentation uses CC BY-SA 4.0. Keep firmware, audio, body backups and generated reports private.
