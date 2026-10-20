# Continuous lifecycle controller

`capture_workflow.c/h` now implements a continuous asynchronous transaction:

```text
configure → refresh → start → retain frames → S2/half-release → stop
    → terminal fence → save eligible frames / release references
    → restore policy → refresh original parameters → done
```

The implementation runs on both Thumb and AArch64. `verify_capture_workflow.py`
executes it against explicit virtual sensor/storage actors, using immutable
16-bit pixel buffers and actual fsynced PGM test files. It checks exact saved
pixels against the generated exposures and compares both ISA event journals.
There are 73 scenarios per ISA, including continuous save/cancel transactions,
buffer pressure, queued frames, races, stale/duplicate acknowledgements,
ambiguous outcomes and restoration. Files are synthetic fixtures, not camera
photographs. Original firmware services are never stubbed as successful.

```text
python dev/precapture/verify_capture_workflow.py --zig PATH_TO_ZIG --output NEW_PRIVATE_FOLDER
```

## Implemented ownership and ordering

- Fresh zero storage, nonwrapping action tickets and a caller-qualified capture
  generation identify the transaction. An action is issued once; another call
  while awaiting its completion cannot submit it again.
- Parameter refresh must complete with the expected new epoch and derived
  flag before readout starts. S2/cancel before a start request prevents that
  request. If start is already in flight, completion leads to stop and fence.
- Only an already-retained reference with eligible native frame metadata can
  transfer to the controller. It reads the existing admission guard; it never
  forces a frame class. A rejected offer stays with its caller.
- Capacity is bounded by 32 ledger entries. Full capacity rejects a new offer
  and reports the rejection; it does not overwrite a live reference. This is a
  structural bound, not a claim about available camera pixel memory.
- Saved exposures must end strictly before S2 and within the requested window.
  Save completion identifies the exact lease as retained or consumed. A retained
  lease needs a distinct release; a consumed lease must never be released again.
  Consumption means durable storage and completed release, not accepted enqueue.
  S1 release after S2 cannot cancel those saves.
- Sensor stop alone does not grant a terminal fence. Frames queued before
  stop may finish ingress while the fence is pending; a matched completion
  covers their final ingress serial. Later same-generation ingress faults.
- Unknown service outcomes retain the pending transaction and ownership.
  No automatic replay, rollback, unmap, close or speculative release follows.
  The caller must preserve controller/adapter/context storage while unresolved.
- Completion requires zero held references and confirmation of the original
  queue policy/limit and regenerated original parameter flag. No pre-trigger
  frame yields a distinct result, never a successful saved-frame claim.
- A completed state can rearm under the same qualified baseline with a newer
  generation and fresh parameter epochs. Save → cancel → save is tested on
  the same state; rearm cannot erase a live or uncertain transaction.

## Native integration still required

The controller is **not connected to a camera**. It has no native calls,
firmware hooks, source admission, placement or installer. Its 920-byte state
is separate from the existing 96-byte CP runtime; never place it there or
assume the older two-page layout accommodates this code.

| Action | Required native binding |
|---|---|
| Configure | Serialized cancellation/idle/retention-owner flow from `cp_backend` and `cp_retention_lease`; not a naked queue store |
| Refresh | Original parameter acquisition/producer in its real owner, followed by evidence of the newly derived parameters |
| Start/stop | Qualified `4038`/`4039` request13 paths; enqueue acceptance is not operation completion |
| Terminal fence | All relevant native owners and late ingress settled; CAP observations, state0 or count0 alone are insufficient |
| Save/release | Real retained-pixel lease, native recording writer and eventual frame/holder destructor completion |
| Restore | Matched original-policy restoration and regenerated baseline parameters, with all image ownership resolved |

The adapter must provide normalized monotonic exposure timestamps, order
ingress by exposure end, and deliver the real S2 edge before post-edge ingress.
Generation/epoch/serial fields only enforce a supplied contract; they do not
prove native source identity, clock meaning, task ownership or quiescence.
An adapter that invents those completions would invalidate the test's meaning.
The stock full-press/AF/AE path must continue separately; this test does not
establish normal camera shooting, FL2/FL3/six-look preservation or boot safety.
Those requirements and physical pre-capture remain unfinished.

### Original frame versus holder lifetime

`audit_frame_reference.py` runs 15 original-reference/holder contracts on the
pinned stock 2.01 CP, stopping before native locking, callbacks and pool returns.
Its independent post-lock slices reproduce frame count at `frame+4`, vtable
add/drop methods, and a `1 → 2 → 1 → 0` count sequence. The original holder can
return to its pool while the independently referenced frame remains at count1.
A holder handle and an extra frame reference are therefore different leases.

The native later-stage path invokes holder release after its completion job.
An adapter must identify which exact lease that consumes. It must not report
a surviving extra frame reference as consumed merely because a holder was
returned; nor report an already destroyed holder as retained. The controller
now supports both kinds of completion and tests mixed behavior per frame.
The original reference methods do not guard counter resurrection/wrap on
invalid inputs. These slices do not authorize retaining an arbitrary pointer
or calling a native destructor, and zero reference count is not proof of SD
durability or an all-stage terminal fence.

```text
python dev/precapture/audit_frame_reference.py --cp PRIVATE_STOCK_CP --output NEW_PRIVATE_JSON
```

## 简体中文

这一版已写出连续生命周期控制器，覆盖准备、参数刷新、半按读出、帧保留、全按
选择保存、逐项释放和原参数还原。两种目标架构各运行 73 个场景，并逐字节核对
虚拟曝光生成的像素与实际写出的测试文件，两个架构的动作顺序也完全一致。

这补齐了控制逻辑和虚拟设备上的连续测试。它尚未绑定相机的传感器、RAW 所有权、
跨任务结束屏障及写卡接口，没有修改或验证实机预拍摄。不能把虚拟服务的回执
直接当作原生服务成功，更不能据此直接往旧运行时或六款外观占用区域塞入代码。

原指令核对还区分了“图像帧引用”和“流程容器”的寿命：容器返回池后，额外持有
的帧引用可能仍存在。保存回执现已区分“该引用仍保留”和“该引用已经完成释放”，
后者不会再发第二次释放。不能把容器销毁、引用归零或任务入队当成照片已经落盘。
