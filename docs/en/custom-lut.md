# Custom LUT / DCP: the complete path from download to camera installation

[Home](../../README.md) · [简体中文](../zh-CN/custom-lut.md)

This guide covers obtaining a DCP/LUT, conversion, body backups, writing, readback, reloading, photographic acceptance and restoration. It is for users and their implementing AI: steps 1–6 have offline tools; steps 7–13 specify device work the AI must implement and verify. **The current public interface is not a one-click installer; missing functionality is not presented as an existing command.**

To use these DCPs in Lightroom/Camera Raw, see [profile downloads](profiles.md) and [desktop instructions](manual.md); you do not need this six-step process. For the ready-made FL2/FL3 installer, use [the separate installation guide](fl23.md).

## What the names mean

| Name | Plain meaning | Where it comes from |
|---|---|---|
| DCP/CUBE | The color reference you want to approximate | Your own or legitimately obtained files; [the reference download](profiles.md) contains 18 original DCPs |
| ST | Sony's Standard Creative Look | An existing camera look; this implementation uses it as the input basis |
| Custom slot 1–6 | Which custom position should use which reference | Assigned in a project file; viewing the plan does not change the camera |
| JSON | A text configuration with named fields | Edit with a text editor; keep the `.json` extension, not `.json.txt` |
| Calibration | How Sony ST colors and native-table changes relate to target colors | Actual measurements, not a renamed DCP |
| Fitting | Approximating a reference with the camera's limited grid and coefficients | Computed by the tool, with error |
| Candidate | Calculated tables and a report awaiting review | Produced by step 5, not installed yet |
| Forward/reverse manifest | Exactly which bytes to change in a particular source, and how to undo that change | Produced by step 6; execution needs separate device integration |

A DCP is intended for RAW development. It is not inherently a Sony-ST-photo-to-Fuji-look transformation: the starting color models differ. Calibration establishes a correspondence before fitting. Only look/tone stages are extracted; Sony's existing body calibration is retained rather than replaced with another camera's sensor calibration.

## Open a terminal and check what is implemented

Extract the complete tool and open a terminal in the directory containing `lut.py`. Install dependencies for this Python using [the Windows/Mac manual](manual.md), then run:

```text
python lut.py doctor
python lut.py --help
```

`doctor` inspects the host only; existing `lut.py` commands do not connect to the camera. The LUT entry has no GUI/CMD layer. The six conversion steps below correspond directly to six commands.

- Only a DCP/CUBE: inspect it, edit a project and view its plan.
- Verified slot records: check binding JSON; this is still not a camera read.
- Real calibration/measurements: prerequisite for fitting.
- Exact supported AP/CP: prerequisite for manifests; device implementation still needs the AI steps below.

## Prepare a project for one Classic Neg. slot

Create your own working folder, for example `D:/MyLook`. This is an example organization:

```text
MyLook/
  project.json              Edit the import plan
  bindings.json             Record separately verified camera state
  references/
    Sony_ILCE-7CM2_Classic_Negative_MTriton.dcp
  measurements/
    patches.npz             Prepared from measured/aligned samples
    response.json           Prepared from measured ISP response
  calibration-v1.json       Step 4 output, or existing valid calibration
  candidate-v1/             Step 5 output
  transition-v1/            Step 6 output
```

Do not create the last three outputs in advance: the tool requires a new output file/directory. Put the corresponding reference DCP in `references`, then create `project.json` in a text editor:

```json
{
  "schema": "a7c2-look-project/1",
  "model": "ILCE-7CM2",
  "firmware": "2.01",
  "calibration": "calibration-v1.json",
  "slots": [
    {
      "slot": 1,
      "name": "Classic Neg.",
      "base": "ST",
      "source": {
        "type": "dcp",
        "path": "references/Sony_ILCE-7CM2_Classic_Negative_MTriton.dcp",
        "exposure_stops": 0,
        "attribution": "MTriton / abpy; CC BY-NC-SA 4.0"
      }
    }
  ]
}
```

This means “prepare only custom slot 1 for Classic Neg., with ST as its base.” `slot` selects a position, `name` records the planned name, `source.path` locates the reference, and `calibration` locates the calibration. A name in this file does not itself change a camera title.

Relative paths start at **the directory containing `project.json`**, not the tool's installation directory. Add entries to `slots` for other looks; slot IDs must be unique within 1–6 and each entry must use `base: "ST"`. Do not select all six merely to copy an example. [The six-look template](../../src/looks/examples/six-looks.json) illustrates the format; its reference paths need editing.

## The six conversion commands

| Conversion step | Command | Inputs prepared beforehand | Output |
|---|---|---|---|
| 1. 检查 DCP / CUBE | `inspect` | Reference file | Specifications and hashes in the log |
| 2. 查看 ST 栏位计划 | `plan` | Project JSON | Selected slots and slots to preserve |
| 3. 核对 ST 绑定文件 | `check-bindings` | Project JSON and binding JSON | Whether the files satisfy ST requirements |
| 4. 根据量测生成校准 | `calibrate` | Patch NPZ and ISP response JSON | New calibration JSON file |
| 5. 拟合机内色表 | `fit` | Project referencing actual calibration and source files | Candidate directory, tables and fit report |
| 6. 生成更新与还原清单 | `prepare-transition` | Candidate, exact AP/CP, bindings and layout | Forward/reverse manifest directory |

### 1. Inspect the DCP / CUBE

Run `python lut.py inspect "reference-path"` and read the terminal output. This checks parsing and reports specifications and SHA-256, a fingerprint of the file contents. DCP inspection lists parsed profile/table/curve information; CUBE inspection lists the grid size and input domain.

**Done when:** the operation finishes successfully without a format error. It does not produce native tables or establish compatibility with Sony ST. A video LUT intended for F-Log or S-Log starts in a different input space and needs a measured bridge. A `.cube` extension alone does not establish suitability.

### 2. View the ST slot plan

Select your `project.json`. This reads and displays the plan. **It is not a project editor and does not choose or change camera slots.** Edit the JSON in your text editor, then run the operation again to change the plan.

For the single-slot example, `selected_slots` should be `[1]`, `preserve_slots` should be `[2, 3, 4, 5, 6]`, and the required base should be ST. You can view a plan before reference/calibration files are available. A valid plan does not establish fitting or installation readiness.

**Done when:** the intended slots, names and ST requirements are correct, without selecting positions you want to retain.

### 3. Check the ST binding file

A binding records which base Creative Look a custom slot uses. Imported tables apply only when the selected slot uses ST. Changing the base to another look disables the imported effect; the base picker is not hard-locked.

Supply the project and `bindings.json`. If custom slot 1 was actually verified to use ST, the format can be:

```json
{"1": "ST"}
```

This is a format example. **The command checks declarations in files; it does not connect to the camera or read saved/runtime values.** Do not fill every slot with ST just to pass. Device integration still requires separate verification of actual camera state.

**Done when:** the log contains `bindings_match: true`. That means the two files satisfy the selected-slot requirements, not that the camera has passed a live check.

### 4. Generate calibration from measurements

This relates the model's Sony ST colors to the measured images, and relates native-table adjustments to color changes. It needs two inputs prepared beforehand:

- **Patch NPZ:** a container of paired numerical colors, not a photo. It holds Sony ST values and matching linear ProPhoto RGB/D50 RAW-development values from the same image locations, with training/holdout assignments.
- **ISP response JSON:** the measured matrix relating native-table adjustments to RGB changes, plus evidence of that measurement. ISP means the camera's image-processing pipeline.

Preparing them requires matched RAW+ST captures with fixed exposure/white balance, RAW development, image alignment, patch extraction and separately verified ISP-response measurements. **The command does not capture, decode, align or perform those device measurements; it has no automatic photo-to-calibration operation.** If these inputs are unavailable, someone with color/device research experience must prepare them. A downloaded DCP alone is insufficient.

Select `measurements/patches.npz` and `measurements/response.json`, then choose the new output file `calibration-v1.json`. Existing valid measured calibration can be reused. Renaming a photo to NPZ or substituting an identity matrix does not create measurements.

**Done when:** calibration JSON is produced and you can identify the source of its samples and response measurements. Set the project's `calibration` field to this file. The report also contains holdout error; fitting one scene well does not establish accuracy in every scene. See [the data contract](technical/formats.md) for required fields.

### 5. Fit native tables

Select the project that now references real calibration and reference files. Choose the new output directory `candidate-v1`. The tool approximates the reference using the grid and coefficient ranges the camera can store.

For slot 1 only, the result should contain:

```text
candidate-v1/
  candidate.json
  slot1.raw-s8.bin
```

`candidate.json` reports source/calibration fingerprints, the slot plan and fitting errors. The `.bin` contains table data. Each native table is 5×9×9×3 signed 7-bit corrections, 1,215 bytes. Six tables do not reduce that native precision further; fitting a larger DCP onto this smaller grid still cannot preserve all original entries.

**Done when:** every selected slot has a table, `looks[].fit.convergence.converged` is `true`, and errors have been reviewed. Lower `synthetic_holdout.rgb_mae` means closer agreement within this computational model; it is not a photographic color-match score and has no universal pass threshold. `actual_photos_or_live_preview_verified: false` is expected because no installation or photo validation has happened.

### 6. Prepare update and reverse manifests

Provide the candidate, bindings and two complete camera program files: `appFw.so` (AP) and `cpapp-b.bin` (CP). These must come from a separately verified device workflow on the target body. They are not in the DCP pack, and another body's backups are not substitutes.

For the exact-source layout, `full7-v4` identifies the explicitly supported six-look source; `three-preview-v2` identifies the supported historical three-look source. **The camera displaying 2.01 is not enough to choose either layout. Stock 2.01 is not either modified source.** Whole-file fingerprints are checked, and unsupported sources are rejected.

With the right candidate and source files, choose the new directory `transition-v1`. It contains:

```text
transition-v1/
  forward.private.json
  reverse.private.json
```

The forward manifest describes changing this exact source to the new tables; the reverse manifest describes undoing that matching result. Neither is a Sony SD-card updater or a recovery package for arbitrary damage. Retain the candidate, sources and manifests; keep body files and private derived manifests private.

**Done when:** both manifests exist and the selected slots, source and before/after fingerprints are correct. Titles, actual slot settings, device writing, reloading and photographic acceptance remain undone. Do not copy the files to the camera as an installer or use the FL23 installer to write custom-look data.

## From converted files to camera installation: steps 7–13

This is the device half of the complete workflow. **Operations 1–6 exist in the current public tool; steps 7–13 are not a universal installer yet. An AI developer must implement and verify the missing device modules below.** There is no fictional Install button here, and copying body-specific research scripts to another camera is not a valid procedure.

You can give an AI this task:

> Read this page, AGENTS.md and the implementation runbook. Install my selected DCP/CUBE into the chosen custom slots, including actual writing, readback, cold-load, preview/new-photo acceptance and restoration. Reuse existing conversion, USB transport and native-worker source. Create a fresh workspace, two verified backups and phase journal for my body. Identify the source before choosing existing-six-table update or first installation. Implement/test missing device modules and deliver evidence at each phase. Do not declare completion at candidate/manifest generation. Recover existing evidence before any replay of an unknown operation.

### 7. Identify the body and choose first installation or update

On Windows, prepare the cable, Mass Storage and drivers using [the USB section](fl23.md#3-connect-the-camera-and-prepare-usb-drivers). The custom installer should reuse `src/fl23/transport.py` to read model/body identity, complete AP/CP, actual settings, name resources and retained-image state. **Reuse its transport source; do not use FL23 install to flash custom-look data.**

Two different routes are required:

| Starting state | Required work | Existing implementation |
|---|---|---|
| Exact supported full7-v4 six-look source | Update selected tables; normally retain instructions, names, recipes and unselected slots | `six.replace_tables` and `worker.prepare_table_worker` prepare guarded native compiler inputs offline; USB orchestration is still missing |
| Stock 2.01, FL23-only or another custom build | Implement the matching first-install adapter, then tables/runtime paths, resources and settings | `sixbuild.build` accepts only the historical three-look source, not stock/FL23; a first-install adapter remains to be implemented |

**Check:** select adapters by complete SHA-256, not version text, names or apparent model similarity. New adapters need explicit source identities and offline reproduction/inverse tests. Do not delete existing fingerprint checks. See [the AI device implementation runbook](lut-ai.md) for hashes and source entrypoints.

### 8. Save two body-specific backups and an installation plan

Before the first device mutation, save complete AP/CP, every resource to be modified, RAM and saved-settings views, original custom recipes, protected CP units and per-file sizes/hashes. Put the second copy at an independent location and verify each file. A historical recipe snapshot cannot replace fresh target-body evidence.

Bind the plan to identity, source/target hashes, selected slots, every program/resource/settings change, required battery level, inverse artifacts and current phase. The user reviews which slots change, which remain and whether names change. Before actual writing, require at least 50% actual battery, continuous connection and a successful native check-only operation.

**Done when:** both copies match, current files/fields satisfy the plan and each phase has an inverse. Missing backups/inverses or changed sources leave the job unwritten.

### 9. Build and test actual installation materials offline

For table-only updates on existing full7-v4, finish step 6 and call public `looktool.worker.prepare_table_worker` to validate forward/reverse manifests and produce a C header/report contract. Compile it with `src/fl23/native/installer.c` into a worker bound to this source/target. Do not use the existing FL23-specific compiled `installer.so` for custom manifests.

First installation also requires its source adapter, name-resource conversion and selected-settings plan. The historical three-to-six builder and complete six-look reproduction tests are references. Stock installation still requires implementing/reviewing the appropriate program differences, loaded extents and every entry boundary. Retired `bootstrap6` is not a shortcut.

**Done when:** artifacts are source-bound, forward then reverse reproduces originals byte-for-byte, and native check/write/failure/restore tests pass. Compilation/result ABI details are in the runbook. Compilation/emulation is not a camera installation.

### 10. Write resources, programs and settings as separate transactions

This requires the AI developer to implement device execution. Users should not manually copy firmware into `/usr` or `/cp`. Reuse the reviewed service session to stage and read back **this job's compiled, hash-pinned worker** and mode request, persist invocation intent, then execute once.

- **Existing six-look table update:** write only reviewed table/checksum windows. Do not rewrite names or reset all recipes merely to replace tables.
- **First installation with new names:** install/read back matching resources as an independent atomic transaction, install referencing AP/CP, then save selected ST/adjustment fields from a fresh plan. Advance only after each transaction succeeds.
- **Settings:** write only selected, independently located fields, read each back, save and verify the saved view. ST gating is not a menu lock. Preserve unselected recipes and original FL/FL2/FL3.

Native modes are 0=check, 1=install and 2=restore. Validate the complete native report against this job's source/target. A timeout/disconnect may happen after device execution: inspect existing results rather than sending installation again because the host did not receive completion.

**Done when:** every transaction has verified results, a complete journal and independent readback. Upload completion or a finished progress bar is insufficient.

### 11. Read back everything and check preservation

Independently read **complete** AP/CP on the host and compare target sizes/SHA-256. If resources changed, read all complete resources too. Check size/inode, restoration of read-only mounts and known temporary-file cleanup.

Compare fresh before/after RAM and saved settings. Selected fields must match the plan; unselected recipes and protected CP units must remain. Explain any additional variation using independent read-only evidence, rather than ignoring all differences.

**Done when:** native hashes, complete host readback and preservation checks pass, with no unknown transaction outstanding. Updated storage and a newly loaded runtime are separate facts.

### 12. Reload and test preview/new photos

Inspect retained-image state read-only first. Known mode2 may use one guarded invalidation only after its preconditions hold; mode0 is inspected without replaying mode2→0. Unknown states stop for inspection.

After all I/O ends, disconnect USB/other power, shut down normally, wait for the access lamp and remove the battery for at least one minute. Separately test names, unpressed-shutter preview switching, new captures/playback for each selected look and original ST/FL/FL2/FL3. If photos are correct but preview is stale, investigate preview paths rather than refitting working tables.

After reconnection, record fresh boot evidence, AP runtime spans, complete CP disk file and actual recipes. A new kernel boot plus matching CP file is not a direct running-CP-instruction dump. Preserve unperformed checks explicitly.

**Done when:** write/readback/load evidence and user observations are recorded, with preview and new-photo checks passed separately. Names alone do not establish completion; a single success does not promise long-term or universal stability.

### 13. Restore this transaction if requested

The AI must also implement/test restoration. For a completed table-only transaction, first require complete current programs to equal this job's target. Mode2 of the same fixed worker returns them to this job's source, followed by complete readback/reload acceptance. The reverse manifest is evidence, not an uploadable updater.

First-install restoration follows the verified inverse dependency order: restore selected settings changed by this job, restore compatible referencing programs, then restore name resources. Do not delete resources while programs still reference them. Check current values at every stage and restore this job's targets only, not an entire stale settings snapshot.

For partial writes, unknown outcomes or unavailable service access, recover transaction evidence and assess capabilities before choosing recovery. Missing acknowledgment is not proof that nothing was written; arbitrary damage is not guaranteed recoverable.

## What a complete AI delivery must contain

1. Actual device commands/interface whose help/tests agree, not only a converter.
2. Fresh verified body-specific duplicate backups and hashes for installation/inverse artifacts.
3. Execution/full-readback evidence for resource, program and setting transactions, with unnecessary transactions explicitly omitted for table-only updates.
4. Load checks, user preview/new-photo results and remaining unverified items.
5. Unknown-result recovery that resumes known stages, plus a tested restore path.

[The device implementation runbook](lut-ai.md) specifies public sources, native ABI, resource format, setting discovery and tests. It distinguishes existing functions from interfaces to build, rather than claiming the research-body workflow is already a universal installer.

## Common stopping points

| Symptom | Meaning and next action |
|---|---|
| Project rejected | Check JSON commas/quotes, model/version, unique slots, `base: "ST"` and attribution |
| Step 2 succeeds, step 5 cannot find files | Viewing a plan does not require all files to exist; check paths relative to the project |
| No NPZ/response JSON | Measurement prerequisites are missing; prepare them rather than inventing defaults |
| Output already exists | Retain it and select a new file/directory; existing outputs are protected |
| Source hash differs or fit did not converge | Review the source version or fit; do not remove guards |
| Files generated, camera unchanged | Expected: all six operations run only on the computer |

[Windows/Mac commands](manual.md) · [Formats](technical/formats.md) · [Validation](technical/validation.md) · [Earlier failures](technical/failures.md) · [Licenses](notices.md)
