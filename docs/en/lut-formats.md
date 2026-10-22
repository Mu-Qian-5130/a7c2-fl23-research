# LUT / DCP formats and color spaces

[Home](../../README.md) · [简体中文](../zh-CN/lut-formats.md)

**The desktop converter accepts a standalone 3D `.cube` with Sony ST / sRGB input and sRGB output. It does not directly accept S-Log3 LUTs.** The camera import page takes `.a7look`; convert `.cube` or `.dcp` first. Conversion only processes computer files.

## Which files work?

| Source | Desktop converter |
|---|---|
| Sony ST / sRGB photo input → sRGB look output, standalone 3D CUBE | Direct conversion source |
| S-Log3 / S-Gamut3.Cine → Rec.709 | Wrong input; output transfer function may also differ |
| S-Log2, HLG, Rec.2020, ACES, DaVinci Wide Gamut | Requires the appropriate color transforms first |
| A CUBE labelled only “Sony”, “cinematic” or “Rec.709” | Ask its author for input/output primaries and transfer functions |
| Standalone Adobe `.dcp` camera profile | Built-in offline DCP evaluation; no Lightroom required |
| `.3dl`, `.look`, `.xmp` presets, images, 1D LUTs | Not direct inputs |
| A supported compiled `.a7look` | Select it directly on the import page |

ST means the camera's Standard Creative Look used as the fitting basis, described here in sRGB RGB values. It is not S-Log3. A Log-to-Rec.709 LUT still expects Log input, even when its output looks normal. Applied to ST it can produce incorrect exposure, contrast and colors.

The CUBE extension does not reliably declare color spaces. The program cannot infer them. Ordinary video Rec.709 and sRGB transfer functions are not interchangeable merely because their primaries match.

## If you only have a Log LUT

Prefer an sRGB photo version from its author. Alternatively, export a complete **Sony ST / sRGB → required input transform → original LUT / desired look → required output transform → sRGB** chain from grading software. Ensure the transforms are actually included in the exported 3D LUT; renaming a file, changing a header or relabelling the export does not convert its colors. Spatial, temporal and masking operations cannot be represented by an ordinary 3D LUT.

The advanced CLI compiler supports `--input-space "space name" --bridge "ST-to-input.cube"`. The bridge must actually map ST / sRGB values into the target LUT's input, and final output must remain sRGB. **The current GUI does not offer a Log bridge field.** A bridge does not guarantee reproduction of Sony's native Log processing or recovery of dynamic range already lost in a photo rendering.

## CUBE structure

- UTF-8 plain text, standalone 3D LUT. Optional `TITLE` and `#` comments.
- `LUT_3D_SIZE N`, **2–129**; common sizes are 17, 33 and 65. Start with 33. Exactly **N³ data rows**.
- Three finite `R G B` numbers per row, normally normalized to 0–1, not 0–255 integer colors. Red changes fastest, then green, then blue.
- Optional three-value `DOMAIN_MIN` / `DOMAIN_MAX`, defaulting to `0 0 0` / `1 1 1`. These set numerical ranges; they do not convert gamut or Log encoding.
- No 1D/shaper-plus-3D files, `LUT_1D_SIZE` or proprietary headers. Output outside 0–1 is clipped before fitting; export normalized output when possible.

A minimal 2-point identity file illustrates the format; it adds no filter effect:

```text
TITLE "Identity example"
LUT_3D_SIZE 2
DOMAIN_MIN 0 0 0
DOMAIN_MAX 1 1 1
0 0 0
1 0 0
0 1 0
1 1 0
0 0 1
1 0 1
0 1 1
1 1 1
```

## DCP, A7Look and RAW

DCP is an Adobe camera profile. The converter evaluates its LookTable / tone curve locally, then fits the camera tables. Both DCP and CUBE conversion work without Lightroom. The optional LrC automatic-recognition plugin is independent of conversion.

A7Look is this tool's compiled camera-look document, including supported tables, names and provenance. A DCP source may also carry its Lightroom profile for automatic matching. A standalone CUBE does not automatically create a Lightroom DCP. Other cameras' sensor calibration is not copied into your body, and DCP processing is not baked into RAW sensor samples.

After conversion: **Add operation → choose slot and Write A7Look → select file and name → Review and apply**. Multiple writes/resets can share one batch; unlisted slots stay unchanged. Follow the cold-reload dialog after readback and check live preview/photos. Standalone look imports have no mandatory separate verification button.

Camera color tables approximate the source. A 65-point CUBE does not mean the camera retains 65³ samples or every DCP/LUT operation; exact source-software or Fuji/Ricoh matching is not guaranteed.
