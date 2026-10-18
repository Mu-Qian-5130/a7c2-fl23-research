# Custom LUT / DCP: from a reference file to candidate tables

[Home](../../README.md) · [简体中文](../zh-CN/custom-lut.md)

This tool helps convert a color reference into candidate tables for the camera's processing programs. **The current interface handles conversion and checks on your computer; it cannot yet install a selected DCP into a camera in one click.** This guide explains all six menu operations without assuming firmware-development knowledge.

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

## Open the tool and identify your starting point

On Windows, extract the complete tools download and double-click **`Custom-LUT.cmd`** at its root. First launch needs Internet access for Python dependencies; use 64-bit Python 3.10+. Once you see six numbered operations, follow the sections below. On Mac, use [the macOS section of the same manual](manual.md#macos), not the `.cmd` launcher.

- **Only a DCP/CUBE:** inspect it, then edit a project and view its slot plan.
- **Verified slot records:** check whether the binding JSON satisfies the project.
- **Actual calibration or complete measured inputs:** you can meet the prerequisites for fitting.
- **Exact supported AP/CP program files:** you may be able to prepare manifests. Not every A7C II file is a supported source.

When an input is missing, stop at that step. The sections below explain the inputs; this interface neither invents missing measurements nor reads the camera for you.

## Prepare a project for one Classic Neg. slot

Create your own working folder, for example `D:MyLook`. This is an example organization:

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

## The six menu operations

| Menu operation | Command | Inputs prepared beforehand | Output |
|---|---|---|---|
| 1. 检查 DCP / CUBE | `inspect` | Reference file | Specifications and hashes in the log |
| 2. 查看 ST 栏位计划 | `plan` | Project JSON | Selected slots and slots to preserve |
| 3. 核对 ST 绑定文件 | `check-bindings` | Project JSON and binding JSON | Whether the files satisfy ST requirements |
| 4. 根据量测生成校准 | `calibrate` | Patch NPZ and ISP response JSON | New calibration JSON file |
| 5. 拟合机内色表 | `fit` | Project referencing actual calibration and source files | Candidate directory, tables and fit report |
| 6. 生成更新与还原清单 | `prepare-transition` | Candidate, exact AP/CP, bindings and layout | Forward/reverse manifest directory |

### 1. Inspect the DCP / CUBE

Select the reference, click “执行离线操作” (Run offline operation), and read the log. This checks parsing and reports specifications and SHA-256, a fingerprint of the file contents. DCP inspection lists parsed profile/table/curve information; CUBE inspection lists the grid size and input domain.

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

This is a format example. **The button checks declarations in files; it does not connect to the camera or read saved/runtime values.** Do not fill every slot with ST just to pass. Device integration still requires separate verification of actual camera state.

**Done when:** the log contains `bindings_match: true`. That means the two files satisfy the selected-slot requirements, not that the camera has passed a live check.

### 4. Generate calibration from measurements

This relates the model's Sony ST colors to the measured images, and relates native-table adjustments to color changes. It needs two inputs prepared beforehand:

- **Patch NPZ:** a container of paired numerical colors, not a photo. It holds Sony ST values and matching linear ProPhoto RGB/D50 RAW-development values from the same image locations, with training/holdout assignments.
- **ISP response JSON:** the measured matrix relating native-table adjustments to RGB changes, plus evidence of that measurement. ISP means the camera's image-processing pipeline.

Preparing them requires matched RAW+ST captures with fixed exposure/white balance, RAW development, image alignment, patch extraction and separately verified ISP-response measurements. **The interface does not capture, decode, align or perform those device measurements; it has no automatic photo-to-calibration operation.** If these inputs are unavailable, someone with color/device research experience must prepare them. A downloaded DCP alone is insufficient.

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

## What remains after the six operations

Separate device integration must handle fresh state and two verified backups, name resources, actual ST provisioning, guarded writes/readbacks, reloading, unpressed-shutter preview switching and new-photo/playback checks. Developers continue with [implementation and integration](technical/integration.md); there is no public button that automates all of this.

The owner's slots currently use NC, CC, NN, Eterna, GR Positive Film and GR Negative Film, with positive single-body photo/latest-v4-preview reports. This demonstrates that integration was performed on that body; it does not mean any user can install a DCP in one click.

## Common stopping points

| Symptom | Meaning and next action |
|---|---|
| Five operations, no calibration entry | Older tool; obtain current source and reopen rather than relying on an old window |
| Project rejected | Check JSON commas/quotes, model/version, unique slots, `base: "ST"` and attribution |
| Step 2 succeeds, step 5 cannot find files | Viewing a plan does not require all files to exist; check paths relative to the project |
| No NPZ/response JSON | Measurement prerequisites are missing; prepare them rather than inventing defaults |
| Output already exists | Retain it and select a new file/directory; existing outputs are protected |
| Source hash differs or fit did not converge | Review the source version or fit; do not remove guards |
| Files generated, camera unchanged | Expected: all six operations run only on the computer |

[Windows/Mac commands](manual.md) · [Formats](technical/formats.md) · [Validation](technical/validation.md) · [Earlier failures](technical/failures.md) · [Licenses](notices.md)
