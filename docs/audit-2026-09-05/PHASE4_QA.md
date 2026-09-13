# Phase 4 targeted/adversarial QA (2026-09-12)

Current status after capacity-cleanup re-review on 2026-09-13: **PASS**. All findings in this document, including the final placement/remove interleaving, are resolved. Earlier FAIL sections are retained only as an archived record of defects found and fixed. No production files were modified by QA.

## Capacity-cleanup closure

- Remove during placement now transfers the stale host window into the existing retiring-window ownership set and connects its token-fenced destroyed callback before disposal.
- The engine retiring slot remains occupied until Qt processes the actual `DeferredDelete`, then `_retired()` calls `finish_retire()` for that exact generation.
- A stale destroyed callback from the old host generation cannot finish or mutate a replacement generation.
- The no-screen/remove interleaving remains a safe no-op.
- Exact final regression run: **3 passed** in Qt offscreen.

## Archived resolved placement concurrency finding

### P1 — remove during placement can permanently consume retiring capacity

- The placement hook can call `engine.remove(id)`, moving the snapshotted generation into `engine.retiring`.
- The stale-token branch in `OverlayService._place()` disposes and removes the host window directly, without `finish_retire()` or a destroyed callback to `_retired()`.
- The retiring snapshot used by the surrounding `_sync()` predates the interleaving, so it is not cleaned in that pass. With no later wake or clock, the retiring generation remains and counts against capacity.
- The new regression checks only absence from `visible` and `windows`. Adding `assert "race" not in overlays.engine.retiring` after the sync reproduces the defect.
- The replacement-during-placement and no-screen/remove interleavings are correctly token-fenced.

## Final six-finding closure (2026-09-13)

- Direct lifecycle: closed. The connected owner-thread read loop flushes before each read, and the regression invokes the real `_read_events()` path rather than the private flush helper.
- Same-ID retiring generation: closed. Promotion excludes IDs present in `retiring`; the limit-three regression verifies the replacement waits until `finish_retire()`.
- Stable pinned card entering fullscreen: closed. `computer_state.changed` is subscribed by the host and triggers the GUI policy recheck and controlled `fullscreen` terminal event.
- Atomic engine/GUI frame: closed. Engine read APIs take the engine lock, and `presentation_state(id, token)` returns one generation-fenced frame. Event-barrier concurrency coverage verifies replacement waits for the reader and makes the old token stale.
- No-screen admission: closed. Host sync defers visible work back to the bounded pending queue; fake-clock expiry produces `dropped/no_space` without a false `displayed`.
- Local index/default monitor disconnect: closed. Placement binds the resolved stable screen ID through the engine before display; removal then produces `display_removed`.

Final narrow command, using Qt offscreen and workspace basetemp: **103 passed**.

## Narrow re-review findings (2026-09-13)

### P1 — Direct lifecycle stays queued during a live session

- `communication/home_assistant.py:258-265` flushes before connect, while the socket is absent.
- The connected read loop at lines 284-315 never flushes; `lifecycle()` only appends.
- The test manually calls `_flush_lifecycle()`, so it does not exercise the owner loop. Lifecycle generated after connection waits for reconnect.

### P1 — same-ID work is promoted while its old generation retires

- Submit leaves the replacement pending, but `overlays/engine.py:265-274` does not exclude IDs in `retiring`.
- Repro with limit 3: remove visible `same`, submit parallel `same`, call `release_deferred()`; visible and retiring then contain different tokens under the same ID.

### P1 — fullscreen policy is not reevaluated for a stable pinned card

- Fullscreen is checked only in `_sync()`; context polling emits no overlay policy wake.
- `service.py:345-349` syncs on tick only when visible IDs change. A pinned card has no clock, so entering fullscreen does not suppress it.

### P1 — engine reads are not fully thread-safe at the GUI boundary

- `needs_clock`, `lifetime`, media methods, and `refresh_media` read mutable collections without the engine lock.
- `OverlayService._tick()` directly reads `engine.visible` after a separately locked tick while router-thread admission/removal may mutate it, allowing inconsistent data or KeyError.

### P2 — no-screen admission can remain accepted forever

- `_place()` returns with an undisplayed visible item, no deadline, and no staging-age clock when there are no screens.

### P2 — index/default UI cards miss display_removed

- Disconnect checks only stored `monitor_id`. UI/example cards use an empty ID and are resolved by index without persisting the actual resolved screen ID.

## Original finding resolution

- Token/source leak: closed; approved four-field public whitelist is used.
- Pending queue clock, hover deadline, close signal, reduced motion, lifecycle bounds, explicit-empty PATCH, and legacy regressions: closed.
- External lifecycle: MQTT/HA paths closed; Direct remains open as above.
- Monitor persistence/inventory: remote stable-ID path closed; local index-card disconnect gap remains.

## Re-review evidence

- Targeted Phase 4 and direct regression selection: **98 passed**.
- Handoff reports **185 targeted passed** plus Ruff/diff-check.
- The Direct test manually flushes and misses the live owner-loop defect.

## Implementation resolution pending narrow QA

The implementation now bounds lifecycle storage with admission reservations, keeps
PATCH as a revision of one logical card, and emits distinct accepted/displayed/rejected
and closed/dropped records with controlled reasons. Public MQTT/Direct lifecycle reuses
the existing result channels and exposes only notification ID, disposition,
reason, and public command ID. Direct delivery is queued off the Qt thread; MQTT uses a
separate bounded lifecycle outbox; Home Assistant handles lifecycle before command
future resolution. Stable monitor IDs, hotplug inventory wakeup, removed-display
terminal handling, reduced-motion completion, stale callback fencing, and image
fallback coverage were added. This section records implementation work only; status
remains FAIL until independent narrow QA reruns the findings.

## Findings

### P0 — internal token/source leak across the public result boundary

- `application/windows_commands.py:220-229` returns the engine generation token to MQTT/Direct command callers.
- `overlays/service.py:138-146` publishes both `token` and internal `source` on `overlay.lifecycle`.
- Reproduction: executing one `overlay.show` command returns `{'delivery': 'accepted', 'notification_id': 'x', 'reason': 'queued', 'token': 1}`.
- Required result projection is limited to public correlation plus `notification_id`, disposition and reason. Internal host generations and internal source labels must stay inside the process.

### P1 — queue expiry stops when a pinned card occupies the host

- `overlays/engine.py:233-235` sets `needs_clock` only from visible deadlines/media. It ignores pending `queue_max_age` deadlines.
- Deterministic reproduction: limit=1, visible pinned card, one pending card => `engine.needs_clock is False`; the Qt timer stops, so `tick()` never drops the pending card and the bounded waiting-age contract is not enforced.

### P1 — PATCH can make a hovered notification immortal

- `overlays/engine.py:111-120` preserves `remaining` but does not restore a deadline when PATCH changes `pause_on_hover` from true to false.
- Reproduction with fake clock: display duration=10, hover at t=4, PATCH `pause_on_hover=False` => `remaining` remains non-null, `deadline=None`, `needs_clock=False`.

### P1 — close button cannot emit its declared signal

- `overlays/presentation.py:52-54` declares `dismissed(str, int)`, but line 98 emits only the ID.
- Clicking the explicit close route raises a Qt/Python signal arity error instead of reaching `OverlayService._dismiss(id, token)`.

### P1 — reduced motion can strand retiring windows and skip delivery acknowledgement

- `overlays/service.py:100-102` applies `reduce_motion()` equally to live and retiring windows.
- `overlays/presentation.py:559-567` stops any animation and restores a visible window, but it neither emits `displayed` for an interrupted enter nor calls `dispose` for an interrupted exit.
- Consequences: an entering notification can remain accepted without displayed lifecycle; a retiring window can stay alive and occupy engine capacity indefinitely.

### P1 — lifecycle backlog is unbounded

- `overlays/engine.py:49`, `138-142`, `208-221`, and `317-326` append lifecycle records to an unbounded list until the Qt host drains it.
- Deterministic reproduction: repeated submit + suppress without a host creates 400 records after 200 iterations. The admission queue is bounded, but the end-to-end pre-Qt/lifecycle backlog is not.

### P1 — lifecycle/results are incomplete outside the local Qt event bus

- `overlay.lifecycle` has no consumer outside `OverlayService`; repository search finds no MQTT/Direct/HA projection.
- User/replaced/display_removed/render_error lifecycle is not consistently produced. For example, same-ID replacement returns `REPLACED` to the immediate caller but does not enqueue a terminal event for the replaced generation; rendering fallback has no `render_error` result.
- This does not meet the requested transport-visible accepted/displayed/rejected and closed/dropped lifecycle contract.

### P1 — monitor inventory changes do not update discovery/state consumers

- `overlays/service.py:171-182` mutates the local monitor list and emits `overlay.monitors_changed`, but repository search finds no subscriber.
- Existing cards use stable `QScreen.name()` and primary fallback, but hotplug/reorder does not republish the HA select catalog/state. A stored config index can therefore select a different physical display after reorder.

### P2 — explicit empty PATCH cannot clear a normal title

- Omission is modeled correctly, but `validated_request()` at `overlays/models.py:247` converts explicit `title=""` to `Home Assistant` for non-badge layouts.
- Reproduction: show title A, PATCH title empty => title becomes `Home Assistant`, while message empty clears correctly.

### P2 — targeted legacy regressions remain

- `tests/test_alpha5_popup.py::test_glass_is_ready_before_first_animated_frame` fails because the test/acceptance key lacks the new token component.
- Three live-media animation variants restart the enter animation on refresh instead of preserving the in-flight transition.
- The `none` variant calls the old one-argument `_dismiss` helper and fails after the signature change.

## Test evidence

- `tests/test_phase4_adversarial.py`: **7 passed**.
- Direct Phase 4 regression set (`test_v2_notifications`, `test_overlay_models`, `test_alpha5_popup`, `test_v2_windows_commands`): **5 failed, 47 passed**.
- The earlier combined run also hit environment-only `tmp_path` permission errors under the default user temp directory; rerun with a workspace `--basetemp` removed those setup errors.
- No `sleep()` was used for race/lifecycle checks.

## Coverage gaps before PASS

Add deterministic host-level tests for close button, interrupted enter/exit reduced motion, stale displayed/destroyed callbacks after replacement and shutdown, fullscreen/lock/suspend recheck immediately before show, monitor reorder/disconnect/primary/mixed-DPI placement, image data limits/corruption/URL fallback, and external lifecycle projection without source/token leakage.
