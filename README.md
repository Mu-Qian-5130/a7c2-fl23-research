# A7C II Tools

**English** · [简体中文](README.zh-CN.md)

For **Sony A7C II / ILCE-7CM2 firmware 2.01**, choose the workflow:

| FL2 / FL3 | Custom LUT / DCP |
|---|---|
| [Install and restore](docs/en/fl23.md) | [Eight steps: reference file to camera](docs/en/custom-lut.md) |
| Prefer **`.\FL23.cmd --help`** for CLI; double-click `FL23.cmd` for desktop | **`python lut.py import "look.dcp" --name "Classic Neg." --slot 1`** |

**[Download standalone LUT importer](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1-preview.1/lut.py)** · [Complete tools ZIP](https://github.com/QAQLeonard/a7c2-fl23-research/releases/download/v2.1-preview.1/a7c2-tools-2.1.zip) · [Release and checksums](https://github.com/QAQLeonard/a7c2-fl23-research/releases/tag/v2.1-preview.1)

[Setup and Windows/macOS commands](docs/en/manual.md). FL23 retains its existing launcher, interface and installation flow. Only LUT/DCP is CLI-only, with 64-bit Python 3.10+ and no Tkinter/CMD dependency.

LUT conversion, backups, actual writing/full readback, reload checks and restoration are implemented; no AI or prior FL23 installation is needed. **Experimental:** this new importer/first-install adapter and Mac USB writing lack physical acceptance. The default color bridge is a shared one-scene approximation, not full DCP fidelity or a Sony-signed update.

[AI entry](docs/en/ai.md) · [Development](docs/en/development.md) · [Validation](docs/en/technical/validation.md) · [DCP references](docs/en/profiles.md) · [Licenses](docs/en/notices.md)
