# Phase 5 final independent QA — PASS

**Authoritative verdict: PASS, 2026-09-23.** The final two findings FQA-01/RR-02 and FQA-02/RR-04 are independently CLOSED on the frozen Phase 5 working diff. All QA-01–QA-11 and RR-01–RR-04 entries are CLOSED in [PHASE5_CLOSURE.md](PHASE5_CLOSURE.md). No remaining actionable finding was identified in this bounded closure review. The supervisor may now run the full repository quality gate and its subsequent final review; this PASS does not claim that gate has already run.

## Final independent closure evidence

Reviewed the small final changes in shell.py, ui_components.py, i18n.py and the three permanent regression tests. Ran the four unchanged final-closure reproductions plus the three new official cases:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .venv/Scripts/python.exe -m pytest build/phase5-rereview/test_final_closure.py tests/test_phase5_gui_ux.py -k 'new_application_card or application_edit_dialog or display_before or queued_theme or added_and_discovered or edit_dialog_accepts or queued_icon_refresh' --basetemp build/phase5-rereview/pytest-final-20260923-independent -p no:cacheprovider -rA --tb=short
```

**7 passed, 41 deselected in 4.78 s**, with no deferred callback errors. Exact output: `build/phase5-rereview/final-20260923-independent.txt`. This is independent execution, distinct from the supplied full targeted ledger.

- **FQA-01 / RR-02 / QA-06 CLOSED:** `_add_card` now calls the same `_translate_card` helper used for language refresh, so accepted Add and inventory discovery receive current-language actions, result text and accessible name at creation. The helper assigns the card's language without translating user labels/identity. AppCard Edit and EXE-selection dialogs use that language when built. Independent accepted Add/Edit cases pass; official Add/Discovery and accepted Edit regressions verify EN→PL→EN, process/name/slug/path preservation, intentional name/slug edits, draft contents and enabled Apply. Existing audio/app permission routing is unchanged.
- **FQA-02 / RR-04 CLOSED:** `_refresh_navigation_icons` checks `_disposed` before reaching Qt children. `dispose` sets it before releasing window resources. Both independent and official cases schedule the actual style-change callback, close/delete the window, deliver DeferredDelete, then process the timer and capture exceptions; neither now receives an exception. Initial/system icon refresh, semantic focus token and draft-theme behavior remain as previously verified.
- **RR-01 and RR-03 remain CLOSED:** no final changes to applied-connection execution, overlay request correlation or result ordering. The independent displayed-before-success case was included and again preserves the displayed lifecycle result against a later success and unrelated remote result.
- **Previously closed groups remain supported:** final changes do not alter Apply/rollback transaction ordering, pending-inventory freeze, exact pre-dialog diagnostics export, Computer source/value/age/error handling, stable monitor choices, service-derived sensor lifecycle, or native second-instance restore. No production or official test files were edited by this reviewer; only review documents were updated.

## Current validation and DoD boundary

The implementer/supervisor ledger on the frozen source is official Phase 5 **44 PASS**, required fifteen-file targeted selection **194 PASS**, original QA reproductions **14 PASS**, earlier RR reproductions **9 PASS**, targeted Ruff and diff check PASS. These unchanged broad selections were not repeated by this reviewer. The latest native QTest mouse/keyboard run is **3/3 PASS** in `keyboard-mouse-native-final.log`; it covers Apply/Discard/navigation, keyboard Start and mouse Close through applied identity, and real quiet-router rejection. Existing actual desktop.main second-process evidence passes hidden/minimized restoration, including Qt and OS foreground state, in `native-activation-20260922.log`.

Current compact evidence remains **112 rendered variants**, seven pages × PL/EN × dark/light × simulated 100/125/150/200% scale, with no horizontal overflow and supervisor visual inspection of repaired icons/descriptions. No layout structure changed in the final patch. The main Phase 5 workflows now have source and runtime evidence, including truthful command/presentation status, local actions, draft/apply, selected provider values, diagnostics and native restore.

The established limits remain explicit: one physical 1920×1080 DPR1 display; physical mixed-DPI transfer/hotplug, Narrator/high-contrast walkthrough and real Snap were not demonstrated. No live HA acceptance, packaged installer/smoke or soak result is claimed. These are not substituted by simulated checks, and no new Phase 6/7 work is requested. Full repository gate and its subsequent final review remain the next authorized steps.

## Preserved history

The following 2026-09-22 findings are retained for audit history only. Their historical statuses are superseded by the 2026-09-23 PASS and the single current closure matrix above. PHASE5_QA.md and PHASE5_REREVIEW.md remain separate historical FAIL reports.

---
# Historical independent review — 2026-09-22 (FAIL, superseded)

Date: 2026-09-22. Reviewed the frozen Phase 5 repair diff only for closure of RR-01 through RR-04 and preservation of the eight previously closed original QA groups. Historical PHASE5_QA.md and PHASE5_REREVIEW.md remain unchanged. No production or official test edits, Git mutations, full gate, Phase 6, or agents were performed.

## Verdict

**FAIL. RR-02 still has two reproducible application localization gaps. RR-04 fixes theme visibility but introduces a reproducible deferred callback after widget disposal.** RR-01 and RR-03 are independently supported as CLOSED. Full gate remains blocked until these bounded corrections are reviewed.

## Evidence and executed checks

The supplied exact-diff ledger is official Phase 5 41 PASS, targeted 191 PASS, original unchanged QA 14 PASS and unchanged RR reproductions 9 PASS. Those full selections were not repeated or attributed to this reviewer. Source and the new official regression assertions were inspected rather than treating those counts as proof of complete workflows.

New review-only cases: `build/phase5-rereview/test_final_closure.py`.

- Focused official RR selection plus initial three independent cases: **2 failed, 12 passed, 30 deselected**; `final-closure-results.txt`. The combined run also exposed deferred widget callback errors despite green assertions; it is not represented as clean execution.
- Independent three-case confirmation alone: **2 failed, 1 passed**, `final-only-results.txt`. No deferred callback noise in that isolated run. The failures create an application card and complete its edit dialogs in English. The pass delivers matching displayed lifecycle before successful command completion, then an unrelated remote result, and verifies both local surfaces retain displayed.
- Independent isolated callback-lifetime confirmation: **1 failed, 3 deselected**, `disposal-confirmed.txt`. The fixture explicitly permits intentional deletion, avoiding double-delete teardown noise. Captured sys.excepthook receives RuntimeError for the deleted QListWidget.

All use Windows Qt offscreen, `.venv/Scripts/python.exe`, `-p no:cacheprovider`, and unique basetemp directories. The new cases use real shell/Application/state with controlled adapters and have no profile, registry, actual process-launch or audio side effects.

Supervisor current evidence was inspected: `keyboard-mouse-confirmed.log`, `keyboard-mouse-native.log`, and `native-activation-20260922.log`. Keyboard/mouse work covers editing, Apply/Discard/navigation, keyboard application Start and mouse Close using applied identity, and real quiet-router failure. Actual second desktop.main activation passes hidden/minimized with Qt and OS visibility/activity/foreground true. Supervisor current render evidence now covers 112 variants (all seven pages x PL/EN x dark/light x 100/125/150/200% simulated scale) at 700x520 DIP with no horizontal overflow; existing-card light visuals and English Computer descriptions were inspected by the supervisor. These fixed-page renders do not exercise newly added cards or their edit dialogs.

## Remaining findings

### FQA-01 / RR-02 / QA-06 — P2: newly added English application card and application editor still use Polish

Locations: `ha_windows_bridge/ui/shell.py:558`, `:567`–571, `:607`–614; `ha_windows_bridge/ui_components.py:507`–521.

In an English window, accept Add application with a new EXE. `_add_card` creates Polish actions, result, accessible name and AppCard controls. Neither `_add_app` nor inventory discovery localizes the newly created card. The exact runtime output is:

- `Brak lokalnego polecenia.`
- `Uruchom lokalnie`
- `Zamknij lokalnie`
- `Wynik lokalnego polecenia aplikacji`

The Add-file dialog itself is correctly English. The official English-dialog test cancels that dialog and therefore never sees the created card. Configured cards receive the initial bulk translation, explaining the successful current renders.

The existing card's Edit action also creates untranslated QInputDialogs: `Nazwa aplikacji` / `Przyjazna nazwa:` and `Identyfikator topicu` / `Identyfikator MQTT:`. The independent test accepts both dialogs, recording titles/prompts and checking the original name/slug passed through untouched. The handoff's claim that application dialogs localize is premature.

Localize new card UI at creation (cover Add and asynchronous discovery), and localize AppCard's edit/EXE-selection dialogs when constructed. Preserve user names, paths, slugs and observed values. Add official coverage that accepts Add and opens/completes Edit rather than only cancelling the file chooser. Existing static/feature/resource/update/overlay/dialog repairs otherwise pass the inspected focused tests.

### FQA-02 / RR-04 — P2: queued icon refresh survives deletion of its window

Locations: `ha_windows_bridge/ui/shell.py:1570`–1573 and `:1001`–1006; disposal at `:1558`.

The new style/palette change handler schedules a zero-delay `_refresh_navigation_icons` callback without a lifetime/disposal guard. Reproduction: deliver StyleChange, close/deleteLater the window before the timer runs, deliver DeferredDelete, then process events. The callback accesses the deleted navigation QListWidget and raises `RuntimeError: libshiboken: Internal C++ object (PySide6.QtWidgets.QListWidget) already deleted.` This is also the error observed during the combined focused test run. The isolated confirmation captures exactly one exception and no fixture cleanup error.

Guard the callback against disposal/invalid widget lifetime, or use a cancellable timer owned by the window and stopped during dispose. Preserve the successful initial/system-theme icon and draft-preview fixes. This finding is a bounded lifetime regression in the new RR-04 repair; it does not claim a native process crash was reproduced.

## RR dispositions

| Finding | Independent disposition | Basis |
| --- | --- | --- |
| RR-01 current saved connection with dirty draft | CLOSED | Source no longer returns for any draft inequality; it tests applied state via start/reconnect and adds the Apply note only for connection-related differences. Both theme/host focused official cases pass. Pending-Apply exclusion and fresh multichannel status tracking remain. No HA-delivery claim added. |
| RR-02 meaningful localization | OPEN | Static descriptions, feature accessibility, live resource/update/overlay output and shell dialogs pass focused tests. Accepted Add and actual AppCard Edit still fail as FQA-01. |
| RR-03 every overlay command terminal and presentation | CLOSED | Matching pending command ID/action now consumes success/failure/rejection/cancellation. Real quiet rejection and update/remove/clear tests pass. Code excludes remote IDs from local surfaces. Independent displayed-before-success ordering case passes and preserves presentation after the command terminal. |
| RR-04 theme/icons/focus/draft preview | OPEN — lifetime regression | Initial theme applies tokens and explicitly refreshes icons; system changes use window.draft; custom toggle focus uses bridgeFocus/semantic text. Pixel/icon and focus tests pass. Deferred style refresh still runs after disposal (FQA-02). |

## Preservation of original QA groups

QA-01 through QA-05, QA-07, QA-09 and QA-10 retain the prior independent closure. The latest bounded repair does not alter transaction/rollback ownership, pending inventory acceptance guards, diagnostic pre-dialog capture, provider sample values/freshness, stable monitor identity, or service-derived sensor state. Applied application identity/permission routing and snapshot side-effect invariants remain intact. Current supervisor mouse/keyboard and native activation evidence reinforces those conclusions.

QA-06 remains OPEN because of FQA-01. QA-08 is now CLOSED with RR-03 runtime evidence. QA-11's original icon/contrast/focus defect is repaired, but RR-04's new lifetime regression must be corrected before overall acceptance. No broader rediscovery or old-QA replay was undertaken.

## Scope and next step

The sole implementer should make the two focused corrections, add durable regressions, and rerun the affected selection after the last code edit. Repeat only their independent closure before proceeding to the full repository gate. Physical mixed-DPI transfer, real hotplug/Snap, Narrator/high-contrast, live HA acceptance, packaging and soak retain the explicit established verification boundaries; no expansion to those tasks is requested here.
