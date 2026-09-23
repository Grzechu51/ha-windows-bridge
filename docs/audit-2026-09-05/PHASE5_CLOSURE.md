# Phase 5 authoritative QA closure matrix

Date: **2026-09-23**. Branch: `codex/phase-5-gui-ux`. Baseline: `95fce8f`.

**Independent verdict: PASS.** This is the single current matrix. CLOSED means independently supported by source inspection and the cited runtime evidence, including preservation of earlier verified behavior. See [PHASE5_FINAL_QA.md](PHASE5_FINAL_QA.md) for the dated final verdict and retained review history. PHASE5_QA.md and PHASE5_REREVIEW.md remain historical FAIL records.

| Finding | Independent status | Behavior and exact closure evidence |
| --- | --- | --- |
| QA-01 | CLOSED | Correlated Apply progress/terminal; durable recovery in footer and Overview; failed draft and preflight/stop/rollback boundaries retained. `test_phase5_apply_terminal_failure_preserves_original_preflight_boundaries`, `test_phase5_recovery_required_remains_in_footer_and_overview`, `test_phase5_apply_progress_is_correlated_to_pending_request`; prior independent closure preserved by final localized-card/disposal-only changes. |
| QA-02 | CLOSED | Import/defaults/disk/device paths recompute dirty state after mutation; shared inventory acceptance path inspected. `test_phase5_non_field_draft_mutations_enable_apply`; current accepted Add/Edit tests also verify draft values and enabled Apply. |
| QA-03 | CLOSED | Pending Apply rejects late discovery/inventory and rechecks after modal return; snapshot refresh does not mutate draft or redirect authorized EXE. `test_phase5_pending_apply_rejects_late_inventory`, `test_phase5_runtime_snapshots_do_not_dirty_configuration`; prior independent closure retained. |
| QA-04 | CLOSED | Diagnostics captures exact reviewed privacy-safe JSON before nested file chooser. `test_phase5_diagnostic_export_freezes_before_file_dialog`, `test_phase5_diagnostic_export_is_exact_preview_and_private`; source unchanged by final repairs. |
| QA-05 | CLOSED | Navigation/timers show real selected provider values, age, source/error and retained sample. `test_phase5_computer_navigation_refreshes_sample_and_age`, `test_phase5_computer_capabilities_show_values_not_app_counts`, `test_phase5_real_computer_shapes_retain_values_across_failure`; independent real-dataclass age/error case in test_rereview.py previously passed. |
| QA-06 | CLOSED | Static/dynamic/accessibility/dialog repairs retained; accepted Add, discovery and Edit now localize immediately and survive PL/EN round trips without altering names/paths/slugs/values. Final independent Add/Edit cases plus `test_phase5_added_and_discovered_cards_follow_language_and_preserve_identity` and `test_phase5_application_edit_dialog_accepts_localized_values_without_identity_loss` PASS on 2026-09-23; helper and dialog construction inspected. |
| QA-07 | CLOSED | Initial and refreshed monitor choices resolve stable ID and preserve editor choice through reorder, with deterministic absence fallback. `test_phase5_monitor_refresh_keeps_editor_identity`; prior independent closure retained. |
| QA-08 | CLOSED | All local actions consume correlated command terminals; quiet rejection reaches editor/onboarding; show presentation remains separate and remote results do not replace it. `test_phase5_quiet_overlay_terminal_result_reaches_both_surfaces`, `test_phase5_real_router_terminal_overlay_actions_are_correlated`, `test_phase5_onboarding_lifecycle_is_correlated`; independent displayed-before-success case PASS again 2026-09-23. |
| QA-09 | CLOSED | Diagnostics/tray share actual service-derived stopped/running/paused/error state. `test_phase5_stopped_sensor_status_and_activation`, `test_phase5_sensor_lifecycle_and_app_identity_survive_language_roundtrip`; prior independent state matrix retained. |
| QA-10 | CLOSED | Bounded registered message reaches queued Qt restore. `native-activation-20260922.log`: actual second desktop.main process passes hidden/minimized, Qt visible/active/non-minimized and OS visible/non-iconic/foreground; event path inspected and unaffected by final patch. |
| QA-11 | CLOSED | Contrast-safe badge text, initial/system light icons, semantic custom-toggle focus; initial theme and system changes preserve draft preview. `test_phase5_badge_text_contrast_ignores_unsafe_system_accent`, `test_phase5_initial_light_style_recolours_navigation_icons`, `test_phase5_toggle_keyboard_focus_uses_contrast_safe_theme_text`; final deferred-refresh guard independently passes too. |
| RR-01 | CLOSED | Current saved connection test runs despite theme/host draft edits and explains Apply for new connection values. `test_phase5_current_connection_runs_against_applied_config_with_dirty_draft` and multichannel transition regression independently passed; source unchanged by final patch. |
| RR-02 / FQA-01 | CLOSED | Final accepted Add/Edit independent reproductions PASS; official accepted Add/Discovery/Edit/round-trip tests PASS; creation helper, per-card language and dialog translation preserve user data and authorization boundaries. `final-20260923-independent.txt` records final execution. |
| RR-03 | CLOSED | Quiet/action terminal routing and presentation ordering independently verified; matched displayed-before-success result persists on both surfaces and ignores remote result. Existing runtime router regressions and final independent ordering case PASS. |
| RR-04 / FQA-02 | CLOSED | Theme/icon/focus/draft repairs retained; disposed guard prevents delayed style callback from accessing deleted Qt child. Independent `test_queued_theme_icon_refresh_is_safe_after_window_disposal` and official `test_phase5_queued_icon_refresh_is_safe_after_window_disposal` PASS on final source with no captured exception. |

## Validation ledger on the frozen source

| Check | Result and provenance |
| --- | --- |
| Final independent closure selection | **7 passed, 41 deselected in 4.78 s**; `build/phase5-rereview/final-20260923-independent.txt` |
| Official Phase 5 | **44 passed**, supplied current targeted ledger |
| Required fifteen-file targeted selection | **194 passed**, supplied ledger |
| Original unchanged QA / earlier RR reproductions | **14 passed / 9 passed**, supplied ledger |
| Targeted Ruff / git diff check | **PASS / PASS**, supplied ledger |
| Latest native Qt keyboard/mouse workflows | **3/3 passed**; supervisor `keyboard-mouse-native-final.log` |
| Actual second desktop.main process | **PASS**, hidden and minimized; supervisor `native-activation-20260922.log` |
| Current compact scale render matrix | **112 variants**, no horizontal overflow; supervisor `visuals-current*` / `render-current-*.log` |

No current finding remains unresolved. The subsequent full repository gate and final Astra supervisor review passed on 2026-09-23: 519 full tests, Ruff, dependency/security checks, clean build and all four source/EXE offscreen/native smoke runs. See [PHASE5.md](PHASE5.md) for the authoritative final gate and validation limits. No staging, commit or push was performed.
