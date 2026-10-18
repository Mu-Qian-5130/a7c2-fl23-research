# Custom LUT / DCP

[Home](../../README.md) · [简体中文](../zh-CN/custom-lut.md)

Open **Custom-LUT.cmd**. Its independent offline interface provides:

- DCP/CUBE inspection and project-slot planning.
- ST binding-file checks and native-table fitting from a calibrated project.
- Exact-source selected-table update manifests and inverse manifests.

Choose an operation, fill the required file paths and use a new output directory. Fitting requires the project's measured calibration first. The interface does not contact USB or install camera firmware. Names, live settings, device transaction and cold-load acceptance remain separate engineering work.

[18 DCP references](profiles.md) · [Toolkit details](technical/integration.md) · [Manual commands](manual.md) · [AI handoff](ai.md)

The owner's camera uses Classic Neg., Classic Chrome, Nostalgic Neg., Eterna, GR Positive Film and GR Negative Film in custom 1–6, based on ST. Photos and latest v4 preview switching are owner-reported normal on one body. This does not make the offline interface a universal six-look flasher.

## Workflow

Inspect → plan selected ST-based slots → check binding evidence → measure calibration → fit → prepare exact-source forward/reverse manifests. See [manual commands](manual.md) and [data formats](technical/formats.md).

A DCP is a RAW rendering reference. Extract look/tone while preserving Sony body calibration; video Log LUTs need a measured input-space bridge. Fitting onto the native 5×9×9×3 signed 7-bit grid retains native precision, but cannot preserve every entry of a larger DCP. The base picker remains editable: non-ST disables the imported effect; this is not a menu lock.

[Integration details](technical/integration.md) · [Validation limits](technical/validation.md) · [Known failures](technical/failures.md)
