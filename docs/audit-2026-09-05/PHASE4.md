# Phase 4 — overlay subsystem

## Architecture

Phase 4 separates notification admission from Qt presentation. `Application` owns one
thread-safe `NotificationEngine`; command handlers synchronously validate and admit a
typed request before returning success. `OverlayService` is the GUI host. Every Qt
callback is fenced by the private notification token and window motion generation.

The engine bounds visible, pending, retiring, and lifecycle work. Admission reserves
space for `displayed` and one terminal event before returning `accepted`. A PATCH keeps
the logical card token, exposure deadline, hover state, and media timeline anchor.
A SHOW with the same ID replaces the old generation and emits its terminal result.
Stale placement snapshots transfer their window to the existing retirement owner;
the generation-fenced destruction callback releases capacity only after Qt destroys it.

Lifecycle states are `accepted`, `displayed`, `rejected`, `closed`, and `dropped`.
Terminal reasons are controlled enum values such as `user`, `expired`, `replaced`,
`locked`, `suspended`, `display_removed`, `render_error`, `stopping`, and `no_space`.
The public payload contains only `notification_id`, `disposition`, `reason`, and the
opaque public `command_id`. Private tokens, routing source, content, URLs, images, and
exceptions never cross the process boundary.

MQTT and Direct reuse their existing protocol-v3 result channels with
`code=notification_lifecycle`. MQTT keeps lifecycle in a separate bounded outbox so a
flood cannot consume command-result capacity. Direct enqueues lifecycle and writes it
from the existing transport owner thread. The Home Assistant runtime validates the
four-field payload and controlled enums before publishing a separate local lifecycle
event; it handles lifecycle before the command-future resolver.

Monitor selection stores a preferred stable ID. A serial-backed manufacturer/model ID
is used when available, otherwise the Windows screen name is retained. Reordering does
not change the selected physical display. A missing preferred display falls back to the
primary display for new work, while a card on a removed display terminates with
`display_removed`. Hotplug wakes the existing telemetry worker, which republishes the
existing select inventory and state topics.

## Validation

Deterministic tests cover queue overflow and age, lifecycle reservation floods,
replacement and PATCH semantics, stale callbacks, reduced motion, lock/fullscreen/
suspend, shutdown, invalid and oversized images, monitor reorder/disconnect/primary/
no-screen fallback, mixed work areas, and fake MQTT/Direct/HA routing. Tests use fake
clocks, fake transports, and Qt events; no wall-clock sleeps or live network are used.

The final independent QA and Astra review passed. The final quality gate below was
run after the last production change; no commit or push was performed.

## Requirement matrix

| Requirement | Deterministic evidence |
| --- | --- |
| Unknown/retiring PATCH | `test_patch_unknown_retiring_and_omitted_fields` |
| Pinned, hover, PATCH deadline, expiry | `test_hover_expiry_and_pinned_patch_preserve_clock`, `test_patch_restores_hover_deadline_clears_title_and_preserves_media_anchor` |
| Replacement, retiring same-ID, stale callbacks, coherent frames | `test_replacement_and_shutdown_reject_stale_callbacks`, `test_same_id_waits_for_retiring_generation_before_promotion`, `test_stale_tokens_cannot_dismiss_or_hover_replacement_atomically`, `test_placement_remove_interleave_is_token_fenced_and_does_not_raise`, `test_stale_placement_cannot_defer_replacement_generation`, `test_presentation_state_is_atomic_and_rejects_stale_generation`, `test_presentation_frame_serializes_concurrent_replacement_without_sleep`, `test_stale_static_callback_after_dispose_is_silent` |
| Lifecycle and command-buffer overload | `test_lifecycle_backlog_reserves_future_events_and_stays_bounded_under_flood`, `test_rejection_flood_cannot_consume_reserved_display_and_terminal_slots`, `test_mqtt_lifecycle_flood_does_not_consume_command_result_capacity` |
| Invalid, oversized, corrupt, and URL images | `test_invalid_oversized_corrupt_and_url_images_use_empty_fallback` |
| Reorder, disconnect, primary, no screens, mixed DPI/work areas | `test_stable_monitor_identity_survives_reorder_and_has_os_name_fallback`, `test_monitor_disconnect_falls_back_to_primary_and_no_screen_is_safe`, `test_no_screens_stages_then_drops_without_false_display`, `test_no_screen_snapshot_remove_interleave_is_a_noop`, `test_local_card_binds_actual_monitor_then_reports_removal`, `test_mixed_dpi_work_areas_are_positioned_in_each_screen_coordinates` |
| Lock/unlock, fullscreen, suspend/resume | `test_lock_suspend_and_fullscreen_policy_emit_controlled_terminal_reasons`, `test_context_change_rechecks_fullscreen_for_stable_pinned_card` |
| Shutdown and stale Qt callbacks | `test_shutdown_emits_terminal_before_fencing_stale_generation`, `test_stale_static_callback_after_dispose_is_silent` |
| Reduced motion during enter/exit | `test_reduced_motion_finishes_enter_once_and_disposes_exit` |
| Public whitelist, session fence, HA future separation | `test_mqtt_lifecycle_reuses_result_topic_without_overwriting_command_result`, `test_direct_lifecycle_reuses_result_endpoint_and_is_session_fenced`, `test_notification_lifecycle_uses_separate_bus_and_never_resolves_command_future` |


## Final supervisor decision — 2026-09-13

**PASS — Phase 4 spełnia Definition of Done i jest gotowa do finalnego commit/push.**

Before: raw notification payloads crossed EventBus into Qt before admission; command
success preceded engine policy and queue decisions. The Qt host owned the engine,
and monitor selection primarily depended on array indices.

After: MQTT / Direct / UI → typed command → application-owned NotificationEngine →
bounded queue and policy → Qt host → presentation → distinct lifecycle/delivery.
Placement and stable priority algorithms are retained. Public lifecycle uses only the
four approved fields on existing result channels and never resolves the original
command future. Private generations remain inside engine/host ownership.

### Delegation and findings

GPT-5.6 Sol implementation/fixes agents completed the subsystem and corrective work.
The existing independent Sol QA agent verified the findings sequentially. At most one
Sol was active at a time during the resumed work; no rendering agent was restarted.
Astra supervised, reproduced the final concurrency issue, ran the final quality gate,
and performed final review.

All six resumed findings are closed: Direct owner-loop flush, retiring identity
promotion, pinned/fullscreen policy, coherent engine/GUI reads, bounded no-screen
staging, and stable monitor binding for local cards. Final Astra review additionally
reproduced remove/replacement during placement: generation-fenced defer and stale
window disposal fixed the exception/ghost risk. QA then caught incomplete retiring
capacity cleanup; the old token now releases its slot only after real Qt destruction.
The final three interleaving regressions pass. Earlier PATCH/lifetime/reduced-motion,
public whitelist and bounded lifecycle findings remain closed; see PHASE4_QA.md.

### Final quality gate

| Check | Final result |
| --- | --- |
| Phase 4 targeted + adjacent overlay tests | PASS — 103 passed, 8.04 s |
| Full pytest | PASS — 475 passed, 19.47 s |
| Ruff (`ruff check .`) | PASS |
| `git diff --check` | PASS |
| `pip check` | PASS — no broken requirements |
| Bandit (`-r ha_windows_bridge custom_components -ll -ii`, repository CI thresholds) | PASS — no findings at those thresholds |
| `pip-audit --progress-spinner off` | PASS — no known dependency vulnerabilities |
| PyInstaller (`--clean --noconfirm HAWindowsBridge.spec`, clean PATH) | PASS |
| Source Qt/offscreen smoke | PASS — exit 0 |
| Source native Windows overlay smoke | PASS — exit 0 |
| Clean EXE offscreen smoke | PASS — exit 0 |
| Clean EXE native Windows overlay smoke | PASS — exit 0 |
| Independent final capacity-cleanup QA | PASS — 3 regressions |
| Astra final review | PASS — no open findings |

The executable reports version 2.0.0-alpha.8. Build logs and test output are in
`build/phase4-final-*.log`; build artifacts remain under the ignored `dist` directory.
Bandit used the existing CI severity/confidence thresholds. pip-audit skipped the local
project package (not published on PyPI); its installed dependencies were audited.

Windows smoke used real Qt/native windows and shutdown with a non-connecting test
configuration. Lock/fullscreen/suspend/resume, monitor disconnect/reorder and mixed DPI
were exercised deterministically, without physically locking/suspending this desktop
or disconnecting its displays. No live HA delivery was required for the transport tests.

### Git at final review

Branch: `codex/phase-4-overlay`. No commit, push, staging, or Phase 5 work.
`git diff --stat` counts tracked changes; the untracked additions are listed separately
by `git status` below.

```text
 M custom_components/ha_windows_bridge/runtime.py
 M custom_components/ha_windows_bridge/websocket.py
 M ha_windows_bridge/application/application.py
 M ha_windows_bridge/application/telemetry.py
 M ha_windows_bridge/application/windows_commands.py
 M ha_windows_bridge/communication/gateway.py
 M ha_windows_bridge/communication/home_assistant.py
 M ha_windows_bridge/communication/protocol.py
 M ha_windows_bridge/config.py
 M ha_windows_bridge/core/commands.py
 M ha_windows_bridge/overlays/engine.py
 M ha_windows_bridge/overlays/glass.py
 M ha_windows_bridge/overlays/models.py
 M ha_windows_bridge/overlays/presentation.py
 M ha_windows_bridge/overlays/service.py
 M ha_windows_bridge/ui/motion.py
 M ha_windows_bridge/ui/shell.py
 M tests/test_alpha5_popup.py
 M tests/test_phase0_regressions.py
 M tests/test_v2_ha_runtime.py
 M tests/test_v2_notifications.py
?? docs/audit-2026-09-05/PHASE4.md
?? docs/audit-2026-09-05/PHASE4_QA.md
?? ha_windows_bridge/overlays/monitors.py
?? tests/test_phase4_adversarial.py
?? tests/test_phase4_delivery.py
?? tests/test_phase4_monitors.py
?? tests/test_phase4_overlay_subsystem.py
```

```text
 custom_components/ha_windows_bridge/runtime.py    |  37 +-
 custom_components/ha_windows_bridge/websocket.py  |   2 +-
 ha_windows_bridge/application/application.py      |  23 +-
 ha_windows_bridge/application/telemetry.py        |  11 +-
 ha_windows_bridge/application/windows_commands.py |  65 ++-
 ha_windows_bridge/communication/gateway.py        |  57 ++-
 ha_windows_bridge/communication/home_assistant.py |  58 ++-
 ha_windows_bridge/communication/protocol.py       |   3 +-
 ha_windows_bridge/config.py                       |   3 +
 ha_windows_bridge/core/commands.py                |   1 +
 ha_windows_bridge/overlays/engine.py              | 471 ++++++++++++++++++----
 ha_windows_bridge/overlays/glass.py               |   8 +-
 ha_windows_bridge/overlays/models.py              | 151 +++++++
 ha_windows_bridge/overlays/presentation.py        |  95 ++++-
 ha_windows_bridge/overlays/service.py             | 257 ++++++++++--
 ha_windows_bridge/ui/motion.py                    |   2 +-
 ha_windows_bridge/ui/shell.py                     |  18 +-
 tests/test_alpha5_popup.py                        |   6 +-
 tests/test_phase0_regressions.py                  |   2 +-
 tests/test_v2_ha_runtime.py                       |  35 ++
 tests/test_v2_notifications.py                    |  19 +-
 21 files changed, 1145 insertions(+), 179 deletions(-)
```
