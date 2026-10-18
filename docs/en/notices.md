# Sources and licenses

[Home](../../README.md) · [简体中文](../zh-CN/notices.md)

Newly authored code is [MIT licensed](../../LICENSE). This independent research is not affiliated with Sony, Fujifilm, Ricoh or Adobe; look names imply neither endorsement nor exact color equivalence.

## Code and research sources

- [Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE), pinned commit `a82f5baaa8e9c3d9f28f94699e860fb2e48cc8e0`: vendored Python service/USB code under `src/fl23/vendor/pmca`; [original MIT text](../../src/fl23/licenses/Sony-PMCA-RE-MIT.txt).
- [A7CR FL2/FL3 research](https://github.com/lzh2016zzz/a7cr-fl23-research/tree/43ba74441c8f10459ade41e84a379ad8005e6ef4): parameter, labels and WBI methodology. A7C II offsets were located independently; A7CR offsets are not directly flashed.
- [A7C II service-mode research](https://github.com/YuuLuo/a7c2-service-preload/tree/1619f938663a36d41e72302a8cfee89a0f6acd1a), documentation CC BY-SA 4.0. This tool uses native `libJit.so` loading, not the preload configuration or clock-changing DEBUG command.
- Adobe DNG specification/SDK documents the DCP format. The toolkit implements limited look/tone stages, not the complete Adobe renderer.

## Reference profiles

The [18 original DCPs](profiles.md) are separate Release assets; the code's MIT license does not cover them.

- Fuji Film Look source: [abpy/FujifilmCameraProfiles](https://github.com/abpy/FujifilmCameraProfiles); A7C II adaptation/testing: **门萨特里顿 / MTriton**, [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Original DCPs, pack README and attribution remain unchanged.
- Sony-adapted Ricoh DCPs retain `Copyright 2022 Adobe Systems, Inc.`. No separate redistribution license was supplied; this repository neither asserts one nor relicenses these files as MIT. Original metadata and provenance are in the [manifest](../profiles/manifest.json).
- Official Fuji video LUTs used in earlier research are not included. The current six-look examples use owner-supplied DCPs.

Sony A7C II 2.01 and Alpha 1 II 4.00 firmware were analysis sources. Sony firmware, trademarks and data remain their owners' material. No complete firmware, signed update container, body backup/calibration, photos, credentials or private derived payloads are distributed. See [validation](technical/validation.md) for what was actually tested.
