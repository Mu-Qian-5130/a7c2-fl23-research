# Vertical shooting display — development preview

[Home](../../README.md) · [简体中文](../zh-CN/vertical-display.md)

For **A7C II / ILCE-7CM2, firmware 2.01**. This branch contains an experimental shooting-display rotation tool. On one Windows-connected camera, enabling the native switch rotated exposure values; adding three resource aliases restored most missing portrait icons. The user accepted the current position of the Av/Tv/Ev/ISO dial-function guide.

**The saved vertical setting stays OFF.** The tool enables the current running session only. Three small filesystem aliases remain until explicitly removed. No AP/CP program, original bitmap, image index, Creative Look, or saved setting is replaced. This is not a Sony firmware-update file or a permanent startup-enable release.

## Run it

Download or clone **this branch's complete source tree**; the existing Release ZIP does not contain this experiment. Use 64-bit Python 3.10+. Windows commands below use `python`; use `python3` on macOS. Reuse the [existing USB setup](manual.md), connect in Mass Storage mode, and keep a charged battery and continuous USB connection during an operation. Do not run another camera tool concurrently.

```text
python -m pip install -r src/vertical/requirements.txt
python vertical.py status --firmware-version 2.01
python vertical.py enable --firmware-version 2.01
```

`enable` inspects the running/saved switch and resource paths, adds the aliases if absent, fully reads their targets back against the original graphics, and enables the RAM switch. Existing exact aliases are reused. Small private transaction reports go into `vertical-work`; full program/image backups are not duplicated because those files are not modified. Add `--work-dir "another-folder"` to choose the location; keep it for subsequent commands.

After completion, keep the camera ON, unplug USB and try both portrait directions. Check shooting icons, borders and exposure values. Keep the camera ON while reconnecting for `status`. A reload of the relevant RAM restores the saved switch value; an ordinary OFF/ON cycle is not proof that a reload occurred. To enable a later session, run `enable` again. The tool does not save the switch; later camera auto-save behavior has not been established by long-term tests.

## Turn it off or remove it

```text
python vertical.py disable --firmware-version 2.01
python vertical.py remove --firmware-version 2.01
```

`disable` sets the running switch OFF and keeps the aliases. `remove` first disables the switch, then removes only the three symlinks whose targets exactly match this experiment. It preserves foreign links and regular files. Use this command to remove the experiment; existing FL23/LUT Recovery does not manage these new aliases.

If an operation is interrupted or its outcome is unknown, preserve `vertical-work` and its reports. Do not repeatedly run `enable`. `status` does not clear an unresolved transaction, and existing native temporary files require inspection before more execution.

## Implementation and AI reproduction

Sources: [entry](../../vertical.py), [host transaction](../../src/vertical/verticaltool/device.py), [native workers](../../src/vertical/native), [offline tests](../../dev/vertical).

- Native parameter `0x7e3`, primary RAM RVA `0x7e732b8`: **0 = ON, 1 = OFF**. Getter bytes at `0x286caa0` are checked before the fixed four-byte write. The native model must be ILCE-7CM2. No firmware provenance hash whitelist is added.
- Backup key `0x02cf1906`: both saved and Backup-RAM records must remain `01`. Primary runtime RAM is a separate value. The tool does not call the Backup write/save APIs.
- Three aliases under `/usr/share/app`: `image_00_23_IPSX.uxc → image_00_32_IPSX.uxc`, likewise `01` and `02`. Reuse the camera's own graphics. Do not substitute another camera's banks, extend image indices, or modify ELF segments. The worker restores and checks the `/usr` read-only mount.
- One shared camera lock and one service session cover inspection, mutation and full readback. Known failed additions can remove their own links; an unknown native outcome stops without replaying the write. Run the physical shooting-display check separately from readback.

Optional source rebuild and tests, without a camera or private firmware:

```text
python -m pip install -r dev/vertical/requirements.txt
python dev/vertical/build_workers.py
python -m unittest discover -s dev/vertical -v
```

The four small compiled ARM64 workers are included in `src/vertical/assets`; normal use does not require Zig. `build_workers.py --zig PATH` selects an existing Zig executable.

## Validation limits

41 native syscall scenarios and 15 host/CLI cases pass offline. They cover RAM enable/disable, existing or conflicting aliases, readback failures, cleanup and unknown outcomes. The original private trials demonstrated most shooting graphics on one camera; this consolidated public CLI has offline coverage, not a new physical installation test. Physical alias removal, persistent startup enable, long-term behavior, complete MENU rotation and macOS USB are not validated. Portrait-specific artwork can still differ in size or shape from the reused landscape files.
