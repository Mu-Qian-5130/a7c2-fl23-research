# Manual commands

[Home](../../README.md) · [简体中文](../zh-CN/manual.md)

Use [Windows](#windows) for the supplied launchers and FL23 camera operations, or [macOS](#macos) for the direct Python offline workflow.

## Windows

Open CMD or Windows PowerShell 5.1/7 in the extracted tools folder. All commands
below use the same Python backend as the GUI/AI workflow; no PowerShell upgrade,
profile setup, activation script or execution-policy change is needed.

### FL2/FL3

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

### DCP/LUT offline conversion

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

### Startup troubleshooting

`FL23.cmd` and `Custom-LUT.cmd` run CMD and Python, not PowerShell. Install 64-bit Python 3.10+ with
the `py` launcher or a working `python` on PATH. An existing local `.venv` is
preserved; an incomplete/unsupported one stops rather than being overwritten.
Paths with spaces and non-ASCII folder names are passed as separate arguments.
If Python is in a custom location, set `A7C2_PYTHON` to its full executable path
using your shell, then rerun the chosen CMD entry. The optional dev/windows/Start.ps1 is only a 5.1
compatible wrapper; if policy blocks it, use the CMD entry directly.

## macOS

### Prepare Python

Download and extract the same v2.0 tools ZIP. Open Terminal in the extracted folder containing `src`, `docs` and `FL23.cmd`. The `.cmd` files and `src/launcher.py` are Windows launchers; use Python directly on Mac.

Install a current 64-bit Python 3.10+ from [python.org](https://www.python.org/downloads/macos/). On Apple Silicon, use native arm64 or universal2 Python; use matching dependencies. Check the interpreter and create a **new** Mac environment:

```sh
cd "$HOME/Downloads/a7c2-tools-2.0"
python3 --version
python3 -m venv .venv-macos
.venv-macos/bin/python -m pip install -r src/looks/requirements.txt
```

If `.venv-macos` already exists, preserve it and inspect it before reusing it. Do not copy a Windows `.venv` to Mac. The commands below stay in the tools root and use the environment explicitly; no activation, Homebrew, `sudo` or execution-policy change is required.

### DCP/LUT offline operations

```sh
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool --version
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool inspect "$HOME/Downloads/Profiles/profile.dcp"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool plan "src/looks/examples/six-looks.json"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool check-bindings "$HOME/MyLook/project.json" "$HOME/MyLook/bindings.json"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool calibrate "$HOME/MyLook/patches.npz" "$HOME/MyLook/response.json" "$HOME/MyLook/calibration.json"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool fit "$HOME/MyLook/project.json" "$HOME/MyLook/candidate-v1"
env PYTHONPATH="$PWD/src/looks" .venv-macos/bin/python -m looktool prepare-transition "$HOME/MyLook/candidate-v1" "$HOME/MyLook/appFw.so" "$HOME/MyLook/cpapp-b.bin" "$HOME/MyLook/bindings.json" "$HOME/MyLook/transition-v1" --layout full7-v4
```

Replace sample input paths with your own files and use new output folders. The example `plan` needs no DCP files; other commands require the same measured calibration, exact source and ST binding evidence described above. Keep project paths in Mac format (`/Users/...` or `/Volumes/...`), preserving paths relative to the project JSON. These commands never connect to the camera.

The optional interface uses Tkinter. If Python has Tk support, open it with:

```sh
.venv-macos/bin/python src/looks/gui.py
```

If `_tkinter` is missing, use the CLI or install a Python distribution with Tk support. For program-building commands only, install `src/looks/requirements-research.txt` in this environment and run `python -m looktool` with the same `PYTHONPATH` prefix; the Windows `--research` launcher flag is not a looktool argument. Assembly/emulation dependencies must support your Python/macOS architecture.

### FL23 package check and camera installation

This offline asset check needs no USB driver or camera connection:

```sh
.venv-macos/bin/python src/fl23/app.py check-package
```

The current release has no validated macOS camera backup/install/restore procedure. The bundled legacy macOS driver source is not wired into this tool's service transport and does not establish support for current macOS or Apple Silicon. Use the [Windows FL23 procedure](fl23.md) for device operations; a successful Mac package check does not validate USB flashing. Mac execution has not been tested on physical Mac hardware in this project.

### Use the DCPs in Lightroom / Camera Raw

From Finder, use **Go → Go to Folder** and enter `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles`. Create the folder if missing, copy the original `.dcp` files there, then restart Lightroom/Camera Raw and select an A7C II RAW. `~` means your user Library. This installs desktop RAW profiles, not camera firmware.
