# AI implementation contract

Before camera work read [the workflow](../../docs/en/custom-lut.md), [integration](../../docs/en/technical/integration.md), [formats](../../docs/en/technical/formats.md), [validation](../../docs/en/technical/validation.md) and [failures](../../docs/en/technical/failures.md).

- All public commands are offline. Run tests first; a candidate, USB transfer, title, emulation result or full disk readback is not a successful boot or physical test.
- Preserve Sony per-body calibration; extract DCP look/tone only. Do not equate native-grid precision with full DCP fidelity.
- Every imported slot requires ST in actual saved/runtime bindings. The base picker is editable; do not claim a hard lock. Preserve fresh unselected recipes and native titles.
- Keep FL/FL2/FL3 working. Names, preview, photo output and metadata are separate paths. Photos were correct during the intermittent preview failure.
- Use exact adapter source hashes. Three-preview-v2 supports 1–3; full7-v4 supports 1–6 table/checksum replacement. Six-program preparation still needs separate resource/settings/retained-image transactions. Retired bootstrap6 is prohibited.
- V4 retries uploads of validated cached live-view tables. It can add work on every eligible update; do not promise no timing/power cost or claim the offline dropped-submission model is a real trace.
- Do not reuse the failed display/segment/icon approach or withdrawn 0xff2f04 notification change. Preserve the corrected incoming wide-branch target. Audit ABI and every entry boundary.
- Never treat zero-filled storage as proof of ownership. Check exact mapped and loaded extents, references, lifetime and BSS boundaries.
- Before writing: fresh source identity/settings, two verified independent backups, tested inverse, native preflight and adequate continuous power. One service session at a time.
- Retry only known initial read-only readiness/busy states. Unknown result, timeout or disconnect stops. Recover existing transaction results; never blindly repeat a firmware write.
- After writing: full readback, size/inode/mount/cleanup checks, fresh saved/runtime preservation and retained-image inspection. Do not rerun mode 2→0 while already0. A kernel boot is not direct CP RAM proof.
- Request only necessary physical actions once all I/O ends. Confirm unpressed-shutter preview, photos/playback and original looks separately. No broad stability claim from one camera.
- No public full firmware, body backup/calibration, photos, credentials, private paths or private derived manifests. Owner-authorized original DCP inputs are distributed only as a separate Release attachment with unchanged bytes and original attribution; do not apply the code's MIT license to them.
- No Claude or subagents without current explicit user authorization. User instructions take precedence.
