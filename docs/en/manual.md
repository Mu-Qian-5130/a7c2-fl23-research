# Manual commands

[Home](../../README.md) · [简体中文](../zh-CN/manual.md)

Open CMD or Windows PowerShell 5.1/7 in the extracted tools folder. All commands
below use the same Python backend as the GUI/AI workflow; no PowerShell upgrade,
profile setup, activation script or execution-policy change is needed.

## FL2/FL3

```text
.\FL23.cmd --check
.\FL23.cmd --setup-only
.\FL23.cmd check-package
.\FL23.cmd prepare --workspace "D:\CameraWork" --backup-copy "E:\CameraBackup"
```

The first three commands do not connect to the camera. Setup may install local
dependencies from the Internet. `prepare` contacts the camera and runs temporary
diagnostics, backs up this body and checks exact source eligibility; it does
not install program changes. Use two new empty folders, preserving older work.
For USB drivers and prerequisites read [the FL23 guide](fl23.md).

After preparation succeeds, with the camera connected and adequate power:

```text
.\FL23.cmd install --workspace "D:\CameraWork" --battery-percent 82
```

82 is an example: enter the actual battery percentage, at least 50. This command
writes to the camera. Do not chain it with `prepare`, retry after an unknown
result, or disconnect during I/O. Once the tool finishes, follow its power-off
instructions and test FL2/FL3 and ST photos/playback, then reconnect:

```text
.\FL23.cmd verify --workspace "D:\CameraWork"
```

If you deliberately want to restore this exact supported FL23 installation,
use its own verified workspace, actual battery percentage and supported
current source. Do not run restore as generic error handling:

```text
.\FL23.cmd restore --workspace "D:\CameraWork" --battery-percent 82
```

## DCP/LUT offline conversion

```text
.\Custom-LUT.cmd --setup-only
.\Custom-LUT.cmd inspect "D:\Profiles\profile.dcp"
.\Custom-LUT.cmd plan ".\src\looks\examples\six-looks.json"
.\Custom-LUT.cmd check-bindings "D:\MyLook\project.json" "D:\MyLook\bindings.json"
.\Custom-LUT.cmd calibrate "D:\MyLook\patches.npz" "D:\MyLook\response.json" "D:\MyLook\calibration.json"
.\Custom-LUT.cmd fit "D:\MyLook\project.json" "D:\MyLook\candidate-v1"
.\Custom-LUT.cmd prepare-transition "D:\MyLook\candidate-v1" "D:\MyLook\appFw.so" "D:\MyLook\cpapp-b.bin" "D:\MyLook\bindings.json" "D:\MyLook\transition-v1" --layout full7-v4
```

These commands are offline. Supply your own measured calibration, exact-source
private firmware and fresh ST binding evidence. Calibration is required before
fitting, not synthesized from an identity matrix to make the command pass.
Use new output folders; [data formats](technical/formats.md).

Program-building adapters additionally need `Custom-LUT.cmd --research ...`;
use `Custom-LUT.cmd --research --help` for the command list.
The generated manifest is not a completed camera install. Public one-command
stock-to-six installation and the name/settings/device integration are not
implemented. Both an AI and a manual user must stop at that boundary rather
than treating the FL23 installer as a custom-look flasher.

## Startup troubleshooting

`FL23.cmd` and `Custom-LUT.cmd` run CMD and Python, not PowerShell. Install 64-bit Python 3.10+ with
the `py` launcher or a working `python` on PATH. An existing local `.venv` is
preserved; an incomplete/unsupported one stops rather than being overwritten.
Paths with spaces and non-ASCII folder names are passed as separate arguments.
If Python is in a custom location, set `A7C2_PYTHON` to its full executable path
using your shell, then rerun the chosen CMD entry. The optional dev/windows/Start.ps1 is only a 5.1
compatible wrapper; if policy blocks it, use the CMD entry directly.
