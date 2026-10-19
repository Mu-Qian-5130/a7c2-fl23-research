# Development and repository layout

[Home](../../README.md) · [简体中文](../zh-CN/development.md)

The owner approved the Recovery, slot-restoration and service-first USB fixes for `main` on October 20, 2026, including updating the existing v2.2-preview.1 commit/release. Main contains FL23's Windows CLI/desktop tool, the Python LUT CLI and independent Recovery. Develop future changes on feature branches; further release rewrites need authorization.

```text
README.md / README.zh-CN.md  English / Simplified Chinese homepages
FL23.cmd                   Original FL23 Windows GUI/device CLI
lut.py                     Portable LUT import / single-slot restore CLI
recovery.py                Independent complete rollback CLI
vertical.py                Branch-only vertical shooting display preview
src/
  fl23/                     Installer, fixed native assets and transport
  looks/                    Conversion, exact-source adapters and tests
  vertical/                 RAM switch and reversible native-resource aliases
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
python -m unittest discover -s dev/vertical -v
python dev/release/check_publication.py
python dev/release/build_release.py
python dev/release/verify_release.py
```

From `src/looks`, install `requirements.txt` and optional `requirements-research.txt`, then run `python -m unittest discover -s tests -v`. Private integration fixtures use `A7C2_RESEARCH_FIXTURES`; see [formats](technical/formats.md). Without them, those tests skip.

The LUT entry uses the current Python without Tkinter, shell wrappers, automatic pip installs or retries. FL23 retains its existing Windows launcher and GUI. No physical Mac test or macOS USB installation is claimed. Historical USB-fix source remains regression material only.

## Documentation and Releases

Every user or technical guide has the same path under `docs/en/` and `docs/zh-CN/`. Keep filenames and commands identical; retain original license/attribution text. `AGENTS.md` files are canonical machine instructions rather than additional user guides.

Preview assets contain one tools ZIP, standalone LUT and Recovery Python files, and checksums. Link the unchanged original-DCP ZIP from v2.1. Record changes in [the changelog](changelog.md); this preview's fixes are also in main. Keep build outputs in ignored `dist/`; do not commit ZIPs, firmware, camera backups, calibration, photos or private generated manifests. See [licenses](notices.md) and [validation](technical/validation.md).
