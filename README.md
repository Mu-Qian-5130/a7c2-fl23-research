# A7C II Tools

**English** · [简体中文](README.zh-CN.md)

For **Sony A7C II / ILCE-7CM2 firmware 2.01**, choose the workflow:

| FL2 / FL3 | Custom LUT / DCP |
|---|---|
| [Install and restore](docs/en/fl23.md) | [DCP acquisition to writing: full workflow and AI implementation](docs/en/custom-lut.md) |
| Prefer **`.\FL23.cmd --help`** for CLI; double-click `FL23.cmd` for desktop | Run **`python lut.py --help`** — portable offline CLI |

**[Download current tools v2.0](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest/download/a7c2-tools-2.0.zip?rev=20261018-project-guides)** · [Release and checksums](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest)

[Setup and Windows/macOS commands](docs/en/manual.md). FL23 retains its existing launcher, interface and installation flow. Only LUT/DCP is CLI-only, with 64-bit Python 3.10+ and no Tkinter/CMD dependency.

Existing `lut.py` commands convert references and prepare manifests. The full guide specifies AI implementation for device writes/readback/reload/restore and identifies missing components. Mac supports offline LUT work; USB installation remains unverified. Experimental research, not a Sony-signed update.

[AI entry](docs/en/ai.md) · [Development](docs/en/development.md) · [Validation](docs/en/technical/validation.md) · [DCP references](docs/en/profiles.md) · [Licenses](docs/en/notices.md)
