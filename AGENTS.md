# Repository entrypoint

This repository has one main branch and two workflows. Read `docs/en/ai.md`
before implementation. Do not switch branches to select a camera feature.

- `src/fl23/`: exact-source FL2/FL3 installation, backup, verification and restore.
- `src/looks/`: Independent DCP/LUT CLI, exact-source device jobs and offline research tools.
- `docs/en/` and `docs/zh-CN/`: matching English/Simplified Chinese guides.
- `docs/profiles/`: source inventory and original license text; original DCP bytes are Release assets.
- `FL23.cmd`: original Windows GUI/device CLI, unchanged.
- `lut.py`: portable LUT-only CLI with explicit device commands; no GUI/CMD or automatic dependency installation.

Follow `src/looks/AGENTS.md` for custom-look work. Run offline validation
before camera interaction. Never relax fingerprints or repeat a write with an
unknown outcome. Offline manifests alone are not an installation. The new
device importer is experimental and lacks physical acceptance.
Keep full firmware, body backups/calibration, photos and credentials private.
No Claude or additional agents without explicit user authorization.
