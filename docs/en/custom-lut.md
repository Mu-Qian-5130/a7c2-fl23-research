# Custom LUT / DCP

[Home](../../README.md) · [简体中文](../zh-CN/custom-lut.md)

Open **Custom-LUT.cmd**. Its independent offline interface provides:

- DCP/CUBE inspection and viewing an existing project's ST slot plan.
- ST binding-file checks, calibration from previously measured data and native-table fitting.
- Exact-source selected-table update manifests and inverse manifests.

Choose an operation and fill its required paths. Calibration outputs a new JSON file; fitting and transition preparation output new directories. The interface does not contact USB or install camera firmware. Names, live settings, device transaction and cold-load acceptance remain separate engineering work.

[18 DCP references](profiles.md) · [Toolkit details](technical/integration.md) · [Manual commands](manual.md) · [AI handoff](ai.md)

The owner's camera uses Classic Neg., Classic Chrome, Nostalgic Neg., Eterna, GR Positive Film and GR Negative Film in custom 1–6, based on ST. Photos and latest v4 preview switching are owner-reported normal on one body. This does not make the offline interface a universal six-look flasher.

## Workflow

The menu uses these labels, in the same order:

| Menu operation | Command | Inputs prepared beforehand | Output |
|---|---|---|---|
| 1. 检查 DCP / CUBE | `inspect` | DCP/CUBE file | Specifications and hashes in the log |
| 2. 查看 ST 栏位计划 | `plan` | Edited project JSON | Slot plan in the log; no project editing |
| 3. 核对 ST 绑定文件 | `check-bindings` | Project JSON and binding JSON | File consistency check; no camera query |
| 4. 根据量测生成校准 | `calibrate` | Aligned patch NPZ and measured ISP response JSON | New calibration JSON file |
| 5. 拟合机内色表 | `fit` | Project JSON referencing actual calibration and source files | New directory: `candidate.json` and selected slot tables |
| 6. 生成更新与还原清单 | `prepare-transition` | Candidate directory, exact-source AP/CP, binding JSON and layout | New directory: `forward.private.json` and `reverse.private.json` |

First copy and edit [the project example](../../src/looks/examples/six-looks.json) to assign slots, names, references and the calibration path. Step 2 only views that file. Binding JSON is a host assertion; saved/runtime camera values need separate verification. An example file is not camera evidence.

Step 4 processes existing measurements; it does not capture photos, decode RAW, align images or measure ISP response. Set the project's `calibration` field to the output path. Existing valid measured calibration can be reused. See [manual commands](manual.md) and [data requirements](technical/formats.md).

A DCP is a RAW rendering reference. Extract look/tone while preserving Sony body calibration; video Log LUTs need a measured input-space bridge. Fitting onto the native 5×9×9×3 signed 7-bit grid retains native precision, but cannot preserve every entry of a larger DCP. The base picker remains editable: non-ST disables the imported effect; this is not a menu lock.

[Integration details](technical/integration.md) · [Validation limits](technical/validation.md) · [Known failures](technical/failures.md)
