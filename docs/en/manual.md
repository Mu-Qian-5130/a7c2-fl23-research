# Python CLI: setup and command reference

[Home](../../README.md) · [简体中文](../zh-CN/manual.md)

FL23 keeps its original `.\FL23.cmd` GUI and device workflow; use [the FL23 guide](fl23.md). Only LUT/DCP moves to root `lut.py`, without a GUI, CMD launcher or automatic dependency installation.

## Windows

Install 64-bit Python 3.10+, extract the complete tool and open a terminal beside `lut.py`. For a new environment:

```text
python -m venv .venv-lut
.\.venv-lut\Scripts\python.exe -m pip install -r src/looks/requirements.txt
.\.venv-lut\Scripts\python.exe lut.py doctor
```

Inspect existing `.venv-lut` rather than overwriting it. In subsequent examples, replace `python` with `.\.venv-lut\Scripts\python.exe` for this setup. Activation, Tkinter and PowerShell policy changes are unnecessary.

## macOS

Use architecture-matching 64-bit Python 3.10+ (native arm64/universal2 on Apple Silicon). Extract the tool and open a terminal at its root:

```sh
python3 -m venv .venv-lut
.venv-lut/bin/python -m pip install -r src/looks/requirements.txt
.venv-lut/bin/python lut.py doctor
```

Replace subsequent `python` prefixes with `.venv-lut/bin/python`; use `/Users/...` or `/Volumes/...` paths instead of Windows drive letters. Do not copy a Windows environment. Mac supports offline conversion/reports/file checks. FL23 retains its Windows launch procedure; macOS USB installation remains unverified.

## What each command does

`python` below means the interpreter with dependencies; `doctor` prints its actual path. Replace sample paths with your own. Do not chain a whole sequence containing camera writes.

| Command | Purpose | Camera changes |
|---|---|---|
| `python lut.py --help` | Top-level help | None |
| `python lut.py doctor` | Inspect Python/platform/dependencies; install nothing | None |
| `.\FL23.cmd check-package` | Validate fixed FL23 assets | None |
| `.\FL23.cmd prepare ...` | Read body, duplicate backups, candidates and native preflight | Temporary diagnostics; no program/recipe installation |
| `.\FL23.cmd install ...` | Install supported FL23 changes/full readback | **Writes** |
| `.\FL23.cmd verify ...` | Post-reload installed-file/parameter checks | Does not reinstall |
| `.\FL23.cmd restore ...` | Restore this FL23 operation using supported body backups | **Writes** |
| `python lut.py ...` | References/plans/calibration/fitting/offline manifests | None; existing commands do not install to devices |

Follow [FL23's complete procedure](fl23.md): successful preparation before install, I/O completion before power removal/reload. Custom import continues through [the acquisition-to-write workflow](custom-lut.md) and [AI implementation runbook](lut-ai.md). Missing device interfaces must be implemented; `lut.py install` is not an existing command.

## Six offline conversion commands

```text
python lut.py --help
python lut.py doctor
python lut.py inspect "D:/MyLook/references/look.dcp"
python lut.py plan "D:/MyLook/project.json"
python lut.py check-bindings "D:/MyLook/project.json" "D:/MyLook/bindings.json"
python lut.py calibrate "D:/MyLook/measurements/patches.npz" "D:/MyLook/measurements/response.json" "D:/MyLook/calibration-v1.json"
python lut.py fit "D:/MyLook/project.json" "D:/MyLook/candidate-v1"
python lut.py prepare-transition "D:/MyLook/candidate-v1" "D:/MyLook/source/appFw.so" "D:/MyLook/source/cpapp-b.bin" "D:/MyLook/bindings.json" "D:/MyLook/transition-v1" --layout full7-v4
```

Project-relative paths start beside that JSON. Calibration needs actual measurements, not a fictional identity response. Use new outputs and exact supported manifest sources. [The complete guide](custom-lut.md) explains every input/output and completion criterion.

Program-building commands need optional dependencies: run `python -m pip install -r src/looks/requirements-research.txt` with the same interpreter. Commands remain `python lut.py prepare-six-program ...` or `prepare-preview-retry ...`; there is no `--research` launcher flag. See `python lut.py --help` for actual parameters.

## Mac file checks and desktop DCP use

`.venv-lut/bin/python src/fl23/app.py check-package` checks tool bytes without a camera/USB driver. It does not validate USB flashing.

For Lightroom/Camera Raw only, use Finder's Go → Go to Folder: `~/Library/Application Support/Adobe/CameraRaw/CameraProfiles`. Copy original DCPs, restart the application and select an A7C II RAW. Windows uses `%APPDATA%\Adobe\CameraRaw\CameraProfiles`. These are desktop profiles, not camera installation.

## Common CLI problems

- Python not found: inspect installation; Windows may use `py -3`, Mac `python3`. Always use the same interpreter for pip and commands.
- Missing dependency: install the displayed requirements with that interpreter. The tool does not install, switch environments or retry device operations automatically.
- Spaces/non-ASCII paths: quote the complete argument.
- Timeout/disconnect/unknown outcome: retain the workspace/results and inspect existing transactions rather than repeating writes.
