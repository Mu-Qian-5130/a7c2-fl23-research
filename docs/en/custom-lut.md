# Custom LUT / DCP: from a file to the camera

[Home](../../README.md) · [简体中文](../zh-CN/custom-lut.md)

**You can operate this manually; no AI is required.** `lut.py` includes conversion, backups, actual device writes, full readback and restoration, independently of FL23 installation. It accepts recognized ILCE-7CM2 2.01 programs only. An existing-six-look slot update passed on one Windows camera, including preview/photos and standalone reload verification. Stock first-install and Mac USB writing remain untested. Treat this as experimental.

Download the tool, then follow [setup](manual.md) for Python and USB:

| What you need | Download / source |
|---|---|
| Run the tool, recommended | [Single-file lut.py](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1-preview.2/lut.py); save the file rather than copying the webpage |
| Complete tools, source and guides | [Tools ZIP](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1-preview.2/a7c2-tools-2.1-preview.2.zip); extract it and enter the folder containing `lut.py` |
| Read / modify the source | [This version's source](https://github.com/QAQLeonard/a7c2-fl23-research/tree/v2.1-preview.2) · [LUT implementation](https://github.com/QAQLeonard/a7c2-fl23-research/tree/v2.1-preview.2/src/looks) |

All attachments and checksums are on the [release page](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1-preview.2). `main` currently contains FL23 only; current LUT development is on [feature/lut-device-import](https://github.com/QAQLeonard/a7c2-fl23-research/tree/feature/lut-device-import). For a first installation, use the fixed version linked above.

Open a terminal in the folder containing `lut.py` and run the commands below there. Use `python` on Windows or `python3` on Mac; if you created a virtual environment, use its interpreter with the installed dependencies. Both downloads use the same commands; only [dependency setup](manual.md#python-and-dependencies) differs.

## 1. Choose DCP / LUT

Obtain your `.dcp` or `.cube`; the [reference pack](profiles.md) contains original DCPs. Choose custom slot 1–6 and its displayed name. Import one slot per job; repeat for additional looks and keep each job's restoration history.

DCP conversion defaults to the bundled **one-scene A7C II rendering approximation**, extracting LookTable/tone without transplanting donor sensor matrices. This is not the complete Adobe renderer or guaranteed Fuji/Ricoh matching. Override with your measured `--calibration "model.json"`. Factory per-body calibration is preserved.

CUBE output must be sRGB. For Sony ST sRGB input, add `--input-space sony-st-srgb`; other inputs such as Log also need `--input-space "space name" --bridge "ST-to-that-space.cube"`. A Log LUT is never silently treated as an ST LUT.

## 2. Convert

```text
python lut.py import "look.dcp" --name "Classic Neg." --slot 1
```

Without `--write`, this prepares, backs up and preflights without installing tables. It connects for diagnostics but does not modify firmware/names/recipes. You do not need project JSON editing, patch authoring or an AI implementation.

## 3. Back up the camera

The same command from step 2 converts the table first, then captures complete programs, all 68 name resources and saved/live settings, verifies two backup copies, builds exact restoration data and runs native preflight. No separate backup command is needed here.

Keep the printed **Job path**. The second copy defaults to `~/.a7c2-lut/backups`; prefer another drive with `--backup-dir "new-empty-folder-on-external-drive"`. Retain the entire job and backup folders.

## 4. Write

After `PREFLIGHT_VERIFIED`, supply the actual battery percentage:

```text
python lut.py install "JOB_PATH" --battery-percent 90
```

Or combine preparation and installation:

```text
python lut.py import "look.dcp" --name "Classic Neg." --slot 1 --write --battery-percent 90
```

Program windows, name resources and the selected ST recipe are separate transactions. Unselected recipes and existing FL2/FL3 are preserved. Keep imported slots on ST; the base picker is not hard-locked. Maintain power and USB, and leave the camera alone during writing.

## 5. Full readback

The tool checks complete AP/CP files, every name resource and saved settings, rather than only patched bytes. Errors stop the job and retain evidence. Continue only after `AWAITING_RELOAD`.

## 6. Reload

Once all I/O has ended, disconnect USB and other external power, shut down normally, wait for the access lamp, then remove the battery for at least one minute. Reinstall it and start the camera. The first startup may be slower. Do not reflash to force a reload.

## 7. Verify preview and photos

Before pressing the shutter, switch repeatedly/randomly between ST and imported looks and check immediate live-view updates. Then capture/play back new photos, check names and original looks. Working photos do not establish working preview.

Reconnect in Mass Storage mode:

```text
python lut.py verify "JOB_PATH" --accept-photos
```

Use `--accept-photos` only after those physical checks succeed. The tool additionally checks a new boot, disk programs, loaded AP spans and recipes; it does not directly dump running CP instructions/tables.

## 8. Restore if needed

```text
python lut.py restore "JOB_PATH" --battery-percent 90
```

The job restores its original recipes/programs/names and reads them back, then reports `RESTORED_AWAITING_RELOAD`. Repeat steps 6–7 and `verify ... --accept-photos`. Restore multiple imports in reverse order: later jobs change complete-source fingerprints, so an older job cannot be forced over them.

**Disconnect or unknown result:** keep the folders and first run `python lut.py recover "JOB_PATH"`. It reads existing results, classifies state and cleans confirmed owned temporary files without reexecuting a loader. Only a proven phase permits `python lut.py resume "JOB_PATH" --battery-percent 90`. If it remains `NEEDS_REVIEW`, stop; do not repeat import/install blindly.

[The AI guide](lut-ai.md) covers implementation/reproduction; ordinary installation does not require it.
