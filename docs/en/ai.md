# AI-assisted work

[Home](../../README.md) · [简体中文](../zh-CN/ai.md)

Use the current `main` branch. Feature selection is a workflow/command choice,
not a branch switch. A new or unknown camera source must stop at a useful
diagnostic result; no AI can guarantee a first-attempt firmware installation.

## Paste into your coding assistant

> Read AGENTS.md and docs/en/ai.md. Determine whether I want FL2/FL3 or a
> DCP/LUT custom-look import. Use the existing tool, exact source guards and
> tested inverse; do not invent offsets or transplant another body's settings.
> Run offline checks first. Keep an on-disk work log containing source hashes,
> intended slots, backups, current stage, output artifacts, errors and next action.
> Preserve unrelated recipes and FL/FL2/FL3. Never replay an unknown USB write.
> Do not claim installation from a manifest, title, emulator or disk readback.
> Show the physical test still required and report unsupported inputs honestly.

## Workflow map

| Request | Entry | Completion evidence |
|---|---|---|
| Install FL2/FL3 on a supported original2.01 body | `FL23.cmd` | Complete native/host file and settings verification, cold-load check, actual new photos/playback |
| Convert a DCP/LUT | `Custom-LUT.cmd inspect` → `plan` → measured `calibrate` → `fit` | Candidate manifest, source/calibration/table hashes, convergence/error report; no camera writes |
| Update selected tables on exact full7-v4 | `prepare-transition --layout full7-v4` | Forward/reverse manifests, selected table/checksum changes only; actual installation remains a separate device transaction |
| Reproduce guarded six programs from the exact historical three-look source | `prepare-six-program` | Reproducible program manifests plus `integration-required.json`; not a stock-to-six installer |
| Unsupported hashes, missing calibration/resources or unknown transaction outcome | Stop before mutation | Saved diagnostic and exact missing prerequisite; do not delete guards to proceed |

Start with `FL23.cmd --check` or `Custom-LUT.cmd --check`, then run the selected entry with `--setup-only`.
For assembler-dependent look commands use `Custom-LUT.cmd --research ...`.
Use [the manual commands](manual.md); they invoke the same code as AI work.

For custom looks, read `src/looks/AGENTS.md` and the [integration](technical/integration.md), [formats](technical/formats.md), [validation](technical/validation.md) and [failures](technical/failures.md) guides. The public six-program builder has exact
reproduction tests. A portable installer from stock firmware,68 name-resource
transaction, live settings provisioning and device installation are not yet
provided as one public command. Do not misrepresent the owner's private
successful workflow as an arbitrary user's automated upgrade.

Before a device write: fresh complete camera files/settings, two verified
backups, exact source hash, slot ownership/ST bindings, native preflight and
tested restore. After writing: complete readback, saved-state preservation,
retained-image state, mount/cleanup checks, cold reload and actual preview/photo
tests. The known restart-loop and stale-preview mistakes are in [the failure record](technical/failures.md).

For reproducibility, retain commands, their exit codes and resulting hashes.
If a task fails, resume the known stage after inspecting results; rerunning the
whole sequence is not a recovery method. Keep all private inputs outside Git.
