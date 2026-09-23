# Phase 5 independent QA — FAIL

Date: 2026-09-14. Reviewed the uncommitted Phase 5 working diff on `codex/phase-5-gui-ux`, based on Phase 4 HEAD `95fce8f`, against REPORT.md section 9 and Phase 5 Definition of Done. This is an independent review, not implementation approval. No production files or official tests were modified; nothing was staged, committed, reset, or pushed. No Phase 6 work and no full quality gate were run.

## Verdict

**FAIL.** The handoff's 161 green targeted tests do not cover several broken user workflows. The independent suite reproduces **12 failures and 2 positive passes**. Fix the findings below and repeat targeted tests and independent QA before the full gate or final approval.

## Reproduction and evidence

QA-only cases: `build/phase5-qa/test_independent_phase5.py`.
Full confirmed output: `build/phase5-qa/results.txt`.

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .venv/Scripts/python.exe -m pytest build/phase5-qa/test_independent_phase5.py --basetemp build/phase5-qa/pytest-confirmed -p no:cacheprovider -rA --tb=short
```

Confirmed result: **12 failed, 2 passed in 2.78 s**. An earlier exploratory execution of the same 14 cases also produced 12 failures and 2 passes; the final run tightened the pending-inventory assertion to identify the newly discovered process rather than assuming the default application list was empty. Tests use real DesktopWindow/Application/state classes and controlled external adapters; they do not manipulate the user's audio, executable processes, profile, startup registry, or application instance.

The handoff's separate targeted selection result is **161 passed in 20.85 s**, as supplied by the supervisor and PHASE5.md. This reviewer did not rerun that unchanged selection or claim it as independent execution.

## Prioritized actionable findings

### QA-01 — P1: recovery-required result is immediately overwritten

Locations: `ha_windows_bridge/application/application.py:675`, `:682`, `:496`; `ha_windows_bridge/ui/shell.py:1114`, `:1130`.

Trigger a registry apply failure followed by a failure to restore the persisted configuration. Application emits `configuration_rollback_failed`, then the correlated failed terminal event, then `_run_operation` emits generic `application.error = operation_failed`. The GUI ultimately displays **operation_failed**, losing the explicit recovery-required instruction and replacing the overview error too. The failed draft is retained, but the essential result is not truthful/actionable at rest.

Reproduction: `test_rollback_recovery_message_survives_operation_error`. Final status is `operation_failed`; expected the recovery instruction. Preserve the correlated terminal outcome against the subsequent generic wrapper error, and use the real lifecycle outcome for a stop failure rather than claiming the previous runtime remains active after a partial stop. Keep original preflight/rollback boundaries intact.

### QA-02 — P2: import, reset, and device selection leave Apply disabled

Locations: `ha_windows_bridge/ui/shell.py:818`, `:838`, `:867`, `:878`, `:900`.

Starting from a clean draft, import a changed profile, restore defaults, or select a disk/device. The draft changes but the footer continues to say no unsaved changes and Apply/Discard remain disabled. `_refresh_fields` calls `_update_dirty` while `_refreshing` is true, causing an immediate return; import/reset never perform the update after that flag clears. The inventory selection path does not call it at all.

Reproductions: `test_import_marks_draft_dirty_and_enables_apply`, `test_reset_marks_draft_dirty_and_enables_apply`, `test_disk_selection_marks_draft_dirty_and_enables_apply`. All fail with `Brak niezapisanych zmian` and disabled Apply. Recompute dirty state once after every completed draft mutation; refresh theme/language previews consistently when imports/defaults replace them.

### QA-03 — P2: pending Apply does not freeze asynchronous draft mutations

Locations: `ha_windows_bridge/ui/shell.py:791`, `:1056`, `:1111`.

Disabling `pages` blocks direct clicks but an outstanding inventory result still enters `_update_applications(..., discover=True)` and adds cards/draft configuration while Apply is pending. A success terminal then replaces the draft with `applied`, discarding those late changes. Outstanding disk/device inventory can similarly invoke a modal selection after submission. This violates the promised frozen submitted draft / no lost pending edits behavior.

Reproduction: `test_apply_pending_inventory_cannot_add_discarded_draft_edits`. A `new.exe` card is added after `_pending_apply` is set. Defer/reject draft-mutating inventory results during Apply, or preserve them explicitly in a subsequent draft; do not silently overwrite them.

### QA-04 — P2: diagnostics can export data the user did not review

Location: `ha_windows_bridge/ui/shell.py:910`.

The preview is read after `QFileDialog.getSaveFileName` returns. Its nested event loop can process state/connection/quiet events and update the underlying preview while the save dialog covers it. Export therefore differs from the text reviewed before pressing Export. The inline comment claiming that after-dialog text was reviewed is incorrect.

Reproduction: `test_diagnostics_exports_preview_reviewed_before_modal`. A quiet-state event during the dialog changes exported `quiet: false` to `true`. Freeze the exact approved preview before opening the file dialog, or present a fresh preview for review afterward. The examined allowlist itself omits profile host/user/secrets, application/window content, paths and log payloads; this finding is about exact preview/export identity, not a demonstrated secret leak.

### QA-05 — P2: Computer can show an obsolete/no-sample snapshot after navigation

Locations: `ha_windows_bridge/ui/shell.py:518`, `:972`, `:1076`, `:125`.

Provider events refresh Computer only while it is the visible page. Activating Computer never refreshes its values; the one-second state timer refreshes only master audio. A sample received on Overview is therefore absent from Computer until another provider event. The labels' displayed ages also stop advancing between events, making freshness misleading for slow/stalled providers.

Reproduction: `test_computer_page_refreshes_snapshot_received_on_other_page`. State has CPU 23.5%, but Computer still says `cpu_ram: unavailable · brak próbki`. Refresh the current snapshot when activating/showing Computer and update freshness independently of new observations. Include source health/error detail and distinct no-sample handling; current labels expose quality but omit available failure detail.

### QA-06 — P2: language refresh corrupts dynamic content and is incomplete

Locations: `ha_windows_bridge/ui/shell.py:732`, `:749`, `:759`; `ha_windows_bridge/i18n.py:471`.

`_translate_static` scans essentially every QLabel/QPushButton and caches its initial text, including feature values and application name/percentage labels. Feature labels were empty when first cached, so switching to English clears real telemetry. Other changing labels can revert to old values/names. Meanwhile combo-box entries, new descriptions, dynamic status and dirty text remain Polish; `_update_dirty` overwrites the footer in Polish immediately. The bidirectional dictionary also maps the Polish source `Start` back to `Uruchom` through the English reverse map.

Reproductions: `test_language_switch_preserves_dynamic_telemetry` (23.5% becomes empty), `test_english_switch_translates_controls_and_dirty_state` (dirty text stays Polish). The supervisor independently inspected all 28 dark/light × PL/EN × page screenshots at 700×520 and confirmed Polish onboarding/channel/editor/footer content in English mode. Use explicit translatable static widgets and regenerate dynamic display text from state. Translate combo items, actions, accessibility labels and result messages without changing data values or user-entered app names.

### QA-07 — P2: hotplug replaces the current local monitor choice with the saved one

Locations: `ha_windows_bridge/ui/shell.py:587`, `:646`.

With saved monitor ID A, choose B in the editor and reorder the monitor inventory. `_refresh_overlay_monitors` always prefers `draft.overlay_monitor_id` A over the editor's selected B. The next preview is routed to A. Initial selection also uses only the saved index rather than resolving its stable ID.

Reproduction: `test_monitor_hotplug_preserves_current_editor_selection` (B becomes A). Preserve the selected editor ID through inventory changes and resolve the configured ID on first load; define a stable fallback when the selected monitor actually disappears.

### QA-08 — P2: onboarding never receives displayed/failed lifecycle results

Locations: `ha_windows_bridge/ui/shell.py:672`, `:1140`.

The local test sets both result labels to the synchronous command's accepted status. Later `overlay.lifecycle` updates only `overlay_result`, leaving onboarding indefinitely at accepted/awaiting presentation. Events are also not correlated to the local test before they overwrite its editor result, so unrelated remote notification activity can replace the displayed local outcome.

Reproduction: `test_onboarding_receives_displayed_lifecycle_result`. A displayed lifecycle event for the local ID does not update onboarding. Correlate local notification/command results and update both relevant surfaces; preserve accepted versus displayed, suppression, rejection and presentation failure distinctions. Quiet overlay shows are rejected by the command adapter; quiet Windows tray messages are suppressed in the GUI, but no independent end-to-end quiet/result test exists in the handoff.

### QA-09 — P2: diagnostics says sensors are running while services are stopped

Location: `ha_windows_bridge/ui/shell.py:949`.

Diagnostic text chooses only paused versus running from the pause flag. With no active services it reports `Sensory: działają`. Tray already computes running/stopped using service state, demonstrating the missing state distinction.

Reproduction: `test_stopped_diagnostics_does_not_claim_sensors_running`. Derive diagnostics and tray text from the same real lifecycle state, including stopped/error/paused.

### QA-10 — P2: second-instance restore reveals HWND but leaves Qt hidden

Locations: `ha_windows_bridge/single_instance.py:14`, `ha_windows_bridge/desktop.py:48`; visibility gates at `ha_windows_bridge/ui/shell.py:512`, `:519`, `:1076`.

Supervisor's independent native Windows evidence: an isolated uniquely titled DesktopWindow restored from minimized correctly (`IsWindowVisible=True`, `IsIconic=False`, foreground true). After `window.hide()`, however, `activate_existing(title)` reveals and foregrounds the HWND while `window.isVisible()` remains **False**, even after 150 ms and event processing. Calling the tray `_restore_window()` restores Qt visibility and activity correctly. Raw Win32 ShowWindow therefore bypasses the Qt state used to gate page updates/timers; the common hidden-to-tray path is incomplete.

Route second-instance activation into the first application's Qt restore method via a bounded instance activation message/IPC mechanism. Verify the actual `desktop.main` second-launch flow for both hidden and minimized cases, not only a native helper call. Do not target the user's running instance/profile in tests.

### QA-11 — P2: arbitrary system accent can make normal status text unreadable

Location: `ha_windows_bridge/ui/theme.py:129`, `:149`.

Supervisor's concrete token check: statusBadge uses `$accent` text on fixed `$selection`. Accent `#0078d4` gives contrast **2.34:1** on dark `#294439` and **3.78:1** on light `#e0eee6`, below the section 9 target 4.5:1 for normal text. `tokens_for_theme` adjusts only text on accent backgrounds; it does not protect accent-colored text or focus visibility on the other surfaces. Use a contrast-safe semantic text token for status badges and inspect representative system accents in real renders.

## Positive findings and preservation of earlier phases

- Independently passed `test_audio_uses_applied_slug_and_permission_despite_unsaved_edits`: keyboard volume and mouse mute target the applied application slug after unsaved slug/permission changes. The router still owns authorization from applied configuration.
- Independently passed `test_snapshot_refresh_emits_no_audio_commands`: programmatic audio updates emit no local commands and do not dirty the configuration.
- Apply candidates are deep-copied, terminal events are correlated by request ID, a failed draft is retained, and direct page editing is disabled while pending. The defects above concern asynchronous mutations and durable result presentation.
- Static diff inspection finds the previous transaction boundaries preserved: startup read precedes stop, initial stop failure does not write profile/autostart, failures after stop compensate save/autostart/config/build/start, rollback failure is explicit. Existing Phase 0 tests still exercise save/autostart/build/start and rollback failures; they were not weakened by this diff.
- Computer is fed by ComputerState rather than a new UI-owned Windows poller. Command/provider ownership and protocol v3 remain intact; the overlay editor uses the existing Phase 4 command path. The only overlay service change emits monitor inventory to the shell.
- The four modified adjacent test files adjust page placement/count and description-aware layout assertions. No removed behavioral transaction/security assertions were found. However, the new Phase 5 language test explicitly accepts a Polish dirty label even after selecting English, masking incomplete translation; the scale tests assert horizontal scrollbar range only and do not prove full keyboard workflows or readable unclipped content.

## Remaining Definition-of-Done coverage and scope gaps

These must be resolved or explicitly left unverified; a green test count is not a Phase 5 completion claim.

- REPORT.md section 9 calls for separate local application start/close tasks and a reliable executable target. The shell/card exposes remote permission toggles and immediate volume/mute, but no local start/close action or result workflow. The underlying command routes exist. No Phase 5 start/close GUI test exists.
- Onboarding provides links to Settings/Computer and a local overlay test, but no staged connection test/result or explanation of credential consequences when changing servers. Overview's last-error panel lacks a concrete recovery action. Diagnostics has a bounded raw log view, not the specified filtered log workflow.
- Computer displays aggregate device/volume counts, basic CPU/RAM/GPU/context values and provider quality/age, but does not show all selected device/disk values or provider error details; channel balance/audio-enhancement rows currently display application counts rather than those capabilities' actual state. Explicitly align the delivered scope with section 9 rather than claim all Computer values are complete.
- `configuration.apply_started` is subscribed to and documented in PHASE5.md but never emitted/handled as an apply-stage status. The new terminal event is real; claimed per-stage apply feedback is not implemented. Correct the documentation or complete the intended stage reporting without changing transaction semantics.
- Deterministic compact layout evidence: handoff tests at 700×520 and simulated Qt 100/125/150/200%. Supervisor independently generated 28 dark/light × PL/EN × page renders at 700×520 with horizontal overflow 0. This is useful evidence, but not physical mixed-DPI monitor transfer, clipping/accessibility validation, or native Snap interaction.
- Native environment is Windows, Qt 6.11.2, one physical 1920×1080 display at DPR 1. Real heterogeneous-monitor transfer/hotplug, moving a window during animation, and 100/125/150/200% physical monitor conditions remain unverified. The native activation defect above prevents a successful existing-instance claim.
- Main window retains the native QMainWindow frame. Broad mouse/keyboard completion, focus/tab order across every new flow, Narrator, Windows high contrast, and native resize/Snap verification are not established by the handoff. The independent tests verify only the specific keyboard volume/mouse mute actions described above.
- No full gate, real HA/MQTT acceptance, packaged application smoke, installation, or soak run was performed by this QA. They are not substituted by mocks/offscreen renders, and this review does not reopen completed Phase 0–4 work or request Phase 6 expansion.

## Required next step

Sole implementer fixes the actionable Phase 5 issues and adds focused official regression coverage. Re-run the targeted selection after the final production edit, then repeat independent QA on that exact diff. Keep native/mixed-DPI limitations explicit. Only after QA passes should the supervisor proceed with the full quality gate and final independent review.
