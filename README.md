# A7C II Tools

**English** · [简体中文](README.zh-CN.md)

Choose one entry for **Sony A7C II / ILCE-7CM2 firmware 2.01**:

| FL2 / FL3 | Custom LUT / DCP |
|---|---|
| [Open FL2/FL3 guide](docs/en/fl23.md) | [Open custom-look guide](docs/en/custom-lut.md) |
| Run **`FL23.cmd`** for backup, installation, verification and restore | Run **`Custom-LUT.cmd`** for the offline reference/table workflow |

**[Download latest tools — v2.0](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest/download/a7c2-tools-2.0.zip)** · [Release and checksums](https://github.com/QAQLeonard/a7c2-fl23-research/releases/latest)

The supplied launchers and FL23 device workflow use Windows and 64-bit Python 3.10+; no PowerShell upgrade is required. Mac users can run the [offline Python workflow](docs/en/manual.md#macos). Initial dependency setup needs Internet access; Windows FL23 camera access also needs USB-driver setup.

The custom-look entry checks DCP/CUBE files, plans ST-based slots, fits tables and prepares exact-source update manifests. It does not automatically flash six looks or replace the separate camera integration. DCPs are RAW profiles, not memory-card firmware.

This is experimental camera research, not a Sony-signed update. [AI entrypoint](docs/en/ai.md) · [Manual commands](docs/en/manual.md) · [Source](docs/en/development.md) · [Licenses](docs/en/notices.md).

[Technical evidence](docs/en/technical/validation.md) · [DCP downloads](docs/en/profiles.md).
