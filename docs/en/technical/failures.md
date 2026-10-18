# Earlier failures and required safeguards

[Home](../../../README.md) · [简体中文](../../zh-CN/technical/failures.md)

This records observed errors, not hypothetical warnings. Preserve these lessons when extending the import workflow.

| Incident | What is established | Required behavior |
|---|---|---|
| Display experiment caused restart loops | Offline checks and full file readback passed; entering shooting still restarted the camera. Exact crashing operation remains unproven. AUTO plus immediate MENU allowed restoration on this body. | Do not reuse the failed display trampoline/segment/icon-bank approach. Isolate UI, preview and table changes; keep exact original and known-working backups. AUTO is not guaranteed recovery. |
| Titles became blank | Two early string/display attempts produced blank right-hand titles | Validate the actual resource/native-reader path and runtime load; do not equate written strings with visible names. |
| Unimported4–6 displayed ST | Old three-look static naming also affected native slots whose base could still change | Limit static names to imported slots; preserve dynamic native getter/recipes elsewhere. All six intentionally assigned is a different scope. |
| Photo correct, preview stale | Owner repeatedly confirmed photos correct while live preview sometimes kept the prior look | Test live preview without shutter separately from photos. Do not refit/rewrite working color tables to diagnose a preview transport/cache issue. |
| Branch entered middle of B.W | Controlled nonzero root+3 snapshot path reached the second half of a replaced wide instruction | Preserve the switch-v2 repair and audit all incoming targets/ABI, not only the most common path. Root+3 product semantics remain unestablished. |
|4 B notification experiment withdrawn | Consumer tracing did not establish a pure preview-update flag; external routine had been stubbed in tests | Restore it before requesting cold-load testing; do not re-enable registry word 0xff2f04=0 as a preview fix. |
| Old image remained loaded after disk write | Earlier RAM checks showed old AP flags despite new disk data | Read actual loaded state; end I/O and fully remove all power when required. Do not repeatedly flash to solve retained-state loading. |
| USB not-ready/busy/timeout | Initial identity query can see explicit readiness/busy responses; unknown results also occurred | Bound retries only for known initial read-only readiness/busy states. Transport timeout/disconnect or unknown write outcome stops; inspect/recover existing results before any retry. |
| Unsafe memory-placement assumptions | A prior helper candidate lay in non-executable/overlapping BSS; zero-filled rodata also had references | Prove loading, translation, executable/readable extents, references and lifetime. Page permission alone is not actual content loading. |

V4's re-upload strategy adds repeated work; its current positive observation does not establish long-term performance or eliminate all causes. Keep the exact reverse manifest, report physical observations separately, and do not combine an optimization with unrelated name/color changes.

Never copy someone else's calibration or complete backup to another body. Do not roll back unrelated user settings from stale snapshots. A full firmware/parameter readback validates bytes, not real boot or color equivalence. Preserve private failure reports without publishing camera serials, pictures or calibration.
