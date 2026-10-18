# Choose the AI reproduction guide

[Home](../../README.md) · [简体中文](../zh-CN/ai.md)

Read [AGENTS](../../AGENTS.md), then use the guide matching the requested project:

| Project | AI guide | Delivery target |
|---|---|---|
| FL2 / FL3 | [FL23 installation and reproduction](fl23-ai.md) | Existing Windows CLI first, desktop alternative; backup/install/readback/reload/restore |
| LUT / DCP | [Independent LUT implementation and reproduction](lut-ai.md) | DCP/LUT acquisition through actual selected-slot installation and restoration, without requiring FL23 installation |

The [LUT user guide](custom-lut.md) follows eight stages; the [AI guide](lut-ai.md) maps the implemented device commands, exact sources and recovery evidence.

Keep a private phase log containing commands/exit codes, source/target hashes, backups, reports, unresolved outcomes and next action. Protect body calibration and unrelated recipes. Test before device work; distinguish offline reproduction, full readback, loaded state and physical behavior. Mac offline support does not establish Mac USB writing. No AI can guarantee first-attempt installation on arbitrary firmware.
