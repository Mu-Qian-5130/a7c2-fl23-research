# Repository entrypoint

This repository has one main branch and two workflows. Read `docs/en/ai.md`
before implementation. Do not switch branches to select a camera feature.

- `src/fl23/`: exact-source FL2/FL3 installation, backup, verification and restore.
- `src/looks/`: DCP/LUT conversion and exact-source offline program/data manifests.
- `docs/en/` and `docs/zh-CN/`: matching English/Simplified Chinese guides.
- `docs/profiles/`: source inventory and original license text; original DCP bytes are Release assets.
- `FL23.cmd`: original Windows GUI/device CLI, unchanged.
- `lut.py`: portable LUT-only CLI, no GUI/CMD or automatic dependency installation. Device implementation is described in the complete custom-look guide.

Follow `src/looks/AGENTS.md` for custom-look work. Run offline validation
before camera interaction. Never relax fingerprints or repeat a write with an
unknown outcome. Offline manifests are not a complete six-look installer.
Keep full firmware, body backups/calibration, photos and credentials private.
No Claude or additional agents without explicit user authorization.
