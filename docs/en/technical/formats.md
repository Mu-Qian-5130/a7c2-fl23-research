# Data contracts

[Home](../../../README.md) · [简体中文](../../zh-CN/technical/formats.md)

## Calibration samples and JSON

Prepare aligned, unclipped multi-scene Sony ST samples and matching linear ProPhoto RGB/D50 RAW developments. The NPZ fields `st_rgb` and `linear_prophoto` are normalized Nx3 arrays; `split` uses 0 for training and 1 for held-out samples. `calibrate` does not decode RAW or register images. Use independent scenes for validation; spatial holdout from one scene is diagnostic only.

Measure native ISP response separately. The response JSON needs a finite, invertible `response_matrix` and an `evidence` description. An identity matrix is a synthetic fixture, not a measured universal camera response.

All profiles need:

```json
{
  "schema": "a7c2-look-calibration/1",
  "coordinate_model": "bt601-limited-provisional",
  "response_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  "evidence": "SYNTHETIC EXAMPLE ONLY; replace with measured camera response"
}
```

The identity above is explanatory, not a measured response. Row-vector convention: `delta_rgb = delta_ycc @ response_matrix`; native corrections are divided by 256 before that multiplication.

DCP rendering additionally requires `inverse_axis`, `inverse_curve`, `inverse_matrix`. Axis/curve lengths match, span [0,1] and are monotone; the finite matrix has shape 3×3. Conversion is:

1. Interpolate each encoded Sony ST channel through the inverse curve.
2. Multiply by `inverse_matrix.T` to get provisional linear sRGB/D65.
3. Convert with Bradford adaptation into linear ProPhoto RGB/D50.
4. Apply the DCP LookTable (HSV, hue wrapped, value-axis encoding 0 or 1), then the hue-preserving tone spline.
5. Convert to encoded sRGB/D65 output.

The implementation omits the complete Adobe RAW/HueSat/baseline-exposure/default rendering machinery. It inventories those camera tags but does not transplant them. Unsupported or malformed curves/tables are rejected. The DCP TIFF header may use 42 or DCP magic `0x4352`, with either byte order; BigTIFF is unsupported.

## Project JSON

`schema=a7c2-look-project/1`, `model=ILCE-7CM2`, `firmware=2.01`, a relative `calibration` path, and `slots` (1–6 unique IDs). Each slot has `name`, `base=ST`, and a source with attribution.

DCP source: `type=dcp`, `path`, optional `exposure_stops` with a documented neutral anchor. This parameter is a rendering convention, not an exposure change applied to the camera.

Cube source: `type=cube`, `path`, `input_space=sony-st-srgb`, `output_space=srgb`. A cube using another input space requires a `bridge` object with `path`, `input_space=sony-st-srgb`, `output_space` matching the look cube's input space, and `evidence`. For example, F-Log2-to-film LUTs need an explicit calibrated Sony-ST-to-F-Log2/F-Gamut bridge. WDR-709 resemblance is not such a calibration.

Cube values may be outside [0,1]; sampling obeys its declared domain and the final native fitting target must be normalized into [0,1]. Combined 1D+3D/shaper files are rejected.

## Candidate and native data

`candidate.json` records per-source and calibration SHA-256, attribution, assigned slots, ST requirements, synthetic fit error, convergence and coefficient limits. `slotN.raw-s8.bin` is exactly 1,215 bytes: 405 Y corrections, then 405 C1 corrections, then 405 C2 corrections. Within each plane, the node index is `Y*81+C1*9+C2`.

Each signed coefficient must be -64..63. The hardware bank is a separate 1,620-byte representation with a firmware-specific permutation. Do not write raw correction planes into a hardware-bank destination.

## Exact transition

A private manifest contains complete component sizes/hashes and non-overlapping windows with `offset`, `bytes`, `before_hex`, `after_hex`. Applying the forward then the inverse must reproduce both complete originals byte for byte. No manifest accepts unknown sources. A candidate name does not update menu assets, and a slot plan does not change any camera settings.

### Six full7-v4 storage

At CP file `0x8000` / VA `0x110000`, eight little-endian u32 words contain magic `0x364c3741`, version `0x00010006`, then six FNV-1a32 checksums. Concatenated raw tables start at file `0x8020` / VA `0x110020`, each 1,215 bytes. FNV-1a uses initial value 2166136261 and multiplier 16777619, reduced modulo 2^32 after each byte. It is a corruption guard, not a cryptographic authenticity claim.

`--layout full7-v4` changes only selected table ranges and their own four-byte checksums. Complete AP/CP SHA-256 preconditions still apply. An updated table set yields a new CP source identity; the adapter rejects an unreviewed subsequent source. No camera settings, labels or reload are performed by a data manifest.

### Optional private fixture index

Set `A7C2_RESEARCH_FIXTURES` to a JSON file outside the checkout. File paths are relative to that JSON (absolute paths also work locally):

```json
{
  "three_ap": "three/appFw.so",
  "three_cp": "three/cpapp-b.bin",
  "native_fl23_cp": "fl23/cpapp-b.bin",
  "six_ap": "six/appFw.so",
  "switch_cp": "switch-v2/cpapp-b.bin",
  "v4_cp": "upload-v4/cpapp-b.bin",
  "tables": ["slot1.bin", "slot2.bin", "slot3.bin", "slot4.bin", "slot5.bin", "slot6.bin"]
}
```

The test checks complete known hashes and exact reconstruction using those local inputs. No firmware, DCP-derived tables, private index or generated transitions are part of the release. Without that environment variable these integration tests skip, rather than report a fabricated reconstruction result. Optional native tests use the same private component files in controlled memory, never USB.
