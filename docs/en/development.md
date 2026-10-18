# Development and repository layout

[Home](../../README.md) · [简体中文](../zh-CN/development.md)

Main currently stays at the FL23-only v1.0 baseline. Keep custom-LUT work on `feature/lut-device-import`; merging into main and publishing a LUT release require the owner's explicit approval. FL23 retains its Windows entry; LUT uses a separate Python CLI.

```text
README.md / README.zh-CN.md  English / Simplified Chinese homepages
FL23.cmd                   Original FL23 Windows GUI/device CLI
lut.py                     Portable LUT-only CLI
src/
  fl23/                     Installer, fixed native assets and transport
  looks/                    Conversion, exact-source adapters and tests
  launcher.py               Original Windows launcher for FL23
docs/
  en/                       English guides; technical/ holds implementation evidence
  zh-CN/                    Matching Simplified Chinese guides
  profiles/                 Original DCP manifest and license text
dev/                        Packaging and offline USB/CLI tests
```

## Offline checks

From the repository root, with dependencies installed:

```text
python -m unittest discover -s dev/usb/tests -v
python -m unittest discover -s src/fl23/tests -v
python dev/release/check_publication.py
python dev/release/build_release.py
python dev/release/verify_release.py
```

From `src/looks`, install `requirements.txt` and optional `requirements-research.txt`, then run `python -m unittest discover -s tests -v`. Private integration fixtures use `A7C2_RESEARCH_FIXTURES`; see [formats](technical/formats.md). Without them, those tests skip.

The LUT entry uses the current Python without Tkinter, shell wrappers, automatic pip installs or retries. FL23 retains its existing Windows launcher and GUI. No physical Mac test or macOS USB installation is claimed. Historical USB-fix source remains regression material only.

## Documentation and Releases

Every user or technical guide has the same path under `docs/en/` and `docs/zh-CN/`. Keep filenames and commands identical; retain original license/attribution text. `AGENTS.md` files are canonical machine instructions rather than additional user guides.

Release assets contain one current tools ZIP, a separate original-DCP ZIP and checksums. Keep build outputs in ignored `dist/`; do not commit ZIPs, firmware, camera backups, calibration, photos or private generated manifests. See [licenses](notices.md) and [validation](technical/validation.md).
