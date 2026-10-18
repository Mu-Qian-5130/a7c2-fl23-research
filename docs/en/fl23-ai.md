# FL23: AI installation and reproduction guide

[Home](../../README.md) · [简体中文](../zh-CN/fl23-ai.md) · [User installation guide](fl23.md)

Goal: install FL2/FL3 on the exact supported stock A7C II 2.01 under Windows, with duplicate backups, writing, independent readback, cold-load, capture/playback and restoration. **Use the CLI first; the desktop interface is an alternative to the same backend.** This task does not import custom LUTs or change LUT resources/settings.

## 1. Starting point

Read [AGENTS](../../AGENTS.md), [the user guide](fl23.md), [manual commands](manual.md) and [validation](technical/validation.md). Only ILCE-7CM2 is supported; version text 2.01 is followed by whole-file identity checks. Stock AP SHA-256: `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`; CP: `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`.

Use 64-bit Python 3.10+ with Tkinter on Windows. The launcher prepares `.venv`; GUI needs Tkinter and device dependencies are in `src/fl23/requirements.txt`. Normal/service USB IDs are `054C:0E8A` / `054C:0336`; prepare libusbK for those identities as documented. macOS USB is not validated.

## 2. Existing implementation and boundaries

| Source | Role |
|---|---|
| [app.py](../../src/fl23/app.py) | `Job.prepare/install/verify/restore`: stages, backups, candidates, transactions and verification |
| [gui.py](../../src/fl23/gui.py) | Windows buttons dispatch to the same `app.py` commands |
| [core.py](../../src/fl23/core.py) | `ORIGINAL/FINAL`, fixed patches, per-body merging, guards and native report validation |
| [transport.py](../../src/fl23/transport.py) | `Session`: identity/authentication/bounded I/O, unknown-result stop, restricted staging/Backup writes |
| [assets/manifest.json](../../src/fl23/assets/manifest.json) | Exact fingerprints of compiled native assets |
| [native/installer.c](../../src/fl23/native/installer.c) | Fixed windows, retained size/inode, mode0 check/mode1 install/mode2 restore |
| [native/wbi.c](../../src/fl23/native/wbi.c) | Retained-image inspection/invalidation from the known precondition |
| [tests/test_offline.py](../../src/fl23/tests/test_offline.py) | Body isolation, occupied storage, unrelated changes, temp conflict and unknown-session checks |

Do not invent offsets or apply the fixed FL23 worker to a different LUT manifest. Preserve native bytes and service/write transport. Unknown sources require diagnosis rather than weaker guards. Backups must belong to this target body.

## 3. Offline startup checks

From the extracted root:

```text
.\FL23.cmd --check
.\FL23.cmd --setup-only
.\FL23.cmd check-package
```

These do not connect to the camera. Environment setup may install dependencies; incomplete existing environments are retained. Double-click `FL23.cmd` for desktop mode. Never run GUI and CLI device operations concurrently.

## 4. Complete CLI sequence

1. Select two new empty workspace/backup directories, preferably on separate disks. Retain previous workspaces.
2. Run `prepare`, requiring phase `prepared` and explicit backup/candidate/native-preflight success:

```text
.\FL23.cmd prepare --workspace "D:/CameraWork-A7C2-01" --backup-copy "E:/CameraBackup-A7C2-01"
```

3. Check identity, both backups, candidates and native mode0 evidence. With actual battery at least 50% and continuous connection, install. Replace the example 82 with the real percentage:

```text
.\FL23.cmd install --workspace "D:/CameraWork-A7C2-01" --battery-percent 82
```

4. After `installed_pending_cold_start`, full readback and all I/O completion, disconnect all external power, shut down normally, wait for the access lamp and remove the battery for at least one minute. Test names, no-shutter preview, new FL2/FL3/ST captures and playback. Reconnect Mass Storage:

```text
.\FL23.cmd verify --workspace "D:/CameraWork-A7C2-01"
```

5. Check complete programs, saved parameters and AP runtime spans, keeping user observations separate. Matching readback does not prove photographic behavior or all-mode stability.

## 5. Expected work at each stage

`prepare` reads target programs/body data, checks stock identities, merges this body's parameters, rejects occupied storage, builds fixed candidates, verifies duplicate originals and runs native check-only. Temporary diagnostics execute; programs/saved recipes are not installed.

`install` requires the same body and `prepared` phase, rechecks source/settings, applies fixed program windows/full readback, merges/saves target parameters, checks unrelated-property preservation and performs guarded retained-image handling. `verify` does not reinstall; it checks post-reload files/parameters and AP spans.

Persist intent before each native invocation, verify staging, invoke once and validate each result's magic/version/mode/length/errors/hashes. After timeout/unknown session, stop further packets including repeated cleanup. Retain `state.json`, logs, existing results and temporary files; inspect the actual outcome first.

## 6. Restoration and failures

Restore only to undo a supported FL23 installation with this body's complete verified backups and a recognized complete current program state. Follow the user's ST selection/full power-cycle/reconnection steps, then use the original workspace:

```text
.\FL23.cmd restore --workspace "D:/CameraWork-A7C2-01" --battery-percent 82
```

This restores this job's programs/target parameters, not arbitrary restart loops, partial damage or unknown states. Recover existing evidence before repeating a write/restore. After completion require readback, reload and new-photo acceptance again.

## 7. AI tests and handoff

Run `python -m unittest discover -s src/fl23/tests -v` and `python -m unittest discover -s dev/usb/tests -v`. The host suite includes actual CMD/PowerShell 5.1/7 forwarding, Unicode/spaced paths, exit codes and simulated USB states. These are not full camera boot, power-loss recovery or second-body validation.

Deliver commands/exit codes, source/target/duplicate-backup hashes, preparation/write/verify phases, full readbacks, preservation/cleanup, load evidence, user capture/playback and restoration results. Without device access/authorization, complete offline checks and state remaining physical stages rather than inventing installation success.
