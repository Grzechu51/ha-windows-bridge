# Phase 5 independent re-review — FAIL

Date: 2026-09-20. Scope: current uncommitted Phase 5 diff on `codex/phase-5-gui-ux`, the eleven finding groups in `PHASE5_QA.md`, current `PHASE5.md`, and REPORT.md section 9 / Phase 5 DoD. Production and official tests were read-only. This review wrote only this report and scratch evidence under `build/phase5-rereview`. No staging, commit, reset, push, Phase 6 work, new agents, or full repository gate.

## Verdict

**FAIL — four concrete blocker groups remain.** Eight original QA groups have closure evidence; QA-06, QA-08 and QA-11 remain partially repaired. The additional current-connection workflow is also broken whenever any unsaved draft exists. Green targeted tests and the original fourteen reproductions do not cover these remaining paths. Do not proceed to the full gate as though independent QA passed.

## Independent execution and evidence

Scratch reproduction file: `build/phase5-rereview/test_rereview.py`.
Final output: `build/phase5-rereview/results-confirmed.txt`.

```powershell
$env:QT_QPA_PLATFORM='offscreen'
& .venv/Scripts/python.exe -m pytest build/phase5-rereview/test_rereview.py tests/test_phase5_gui_ux.py -k 'not compact and not scale' --basetemp build/phase5-rereview/pytest-confirm-new -p no:cacheprovider -rA --tb=short
```

Result: **7 failed, 25 passed, 5 deselected in 5.70 s**. Nine independent cases contribute seven failures and two passes; the twenty-three selected official Phase 5 runtime cases pass. The five layout cases were intentionally excluded because the supervisor was independently rendering the compact matrix. Tests use real DesktopWindow, Application, command router, state store and provider-domain dataclasses with controlled external adapters; no actual audio, process launching, profile, registry or live HA side effects are performed.

The supplied final targeted result is 178 passed, and the supplied rerun of unchanged original QA is 14 passed. Those counts are implementation evidence, not executions attributed to this reviewer. Their relevant code paths and original positive invariants were inspected; the entire old QA or full targeted gate was not repeated.

Supervisor evidence inspected: `native-activation.log` records actual second `desktop.main` process exit 0 and both hidden/minimized first windows Qt-visible, active, non-minimized, OS-visible, non-iconic and foreground. `native_activation.py` isolates the mutex/title and avoids the user profile. The supervisor reports 112 compact renders: seven pages x PL/EN x dark/light x simulated scales 100/125/150/200%, 700x520 DIP, no horizontal overflow. Evidence is in `visuals`, `visuals-125`, `visuals-150`, `visuals-200` and `render-*.log`. The supervisor visually identified untranslated Computer descriptions; `visuals/texts.json` independently exposes those strings. This reviewer could not open image files through view_image because the Windows sandbox helper failed; no independent visual inspection is claimed. Early light screenshots omitted bridgeIcon in their harness; that omission is not used as proof of a production defect. The separate initialization-order reproduction below proves the runtime defect.

## Remaining actionable findings

### RR-01 — P2: current connection test is a no-op with any unsaved setting

Location: `ha_windows_bridge/ui/shell.py:336`–338.

Change only theme, or change the broker host, then activate Test connection. `_test_connection` returns before `start`/`reconnect`, shows “The test uses the previously applied server and credentials. Apply changes to test the new ones.”, and never starts a test. The wording implies a current-connection test has occurred. Both independent parametrized cases fail with `calls == []`, where the applied broker is configured and the requested start should run. A language preview also makes the entire config unequal.

Run the current/applied connection test despite an unrelated or connection-related draft, preserving an explicit note that new server/credentials require Apply. Keep pending-Apply exclusion, stopped/connecting transitions, both enabled channels, and the distinction between transport connection and HA receipt. The existing clean-draft multichannel regression passes; it does not exercise this condition.

### RR-02 / QA-06 — P2: English UI still exposes Polish descriptions, accessibility and live results

Locations: `ha_windows_bridge/ui/shell.py:429`, `:436`, `:451`, `:791`, `:1305`, `:1311`; untranslated dialogs also at `:1025`, `:1034`, `:1057`, `:1073`, `:1108`, `:1431` and `:1504`.

Runtime reproductions confirm that English mode contains the Polish generic feature description, `Udostępniaj: Procesor` accessible name, `Wątki: 5` in live resource output, and `show: accepted · oczekuje na prezentację` after local preview. Feature value accessible names are excluded with the dynamic widgets and also remain Polish. Source inspection confirms update-result and newly constructed import/defaults/device/export/exit dialogs bypass localization. Mapping entries alone do not translate a fresh dialog's literals. These are required settings, diagnostics, notification, and keyboard/accessibility flows, rather than arbitrary user data or protocol identifiers.

Complete explicit localization of all required static descriptions/accessibility names and construct dynamic messages/dialogs in the active language. Retain identities and live values: the official 23.5% translation regression passes, and the independent round-trip verifies a user-edited application display label and stable slug remain intact. Avoid fixing this by translating user-entered application names or observed values.

### RR-03 / QA-08 — P2: asynchronous overlay rejection leaves the local result permanently accepted

Locations: `ha_windows_bridge/ui/shell.py:789`–794, `:1403`–1412, `:1417`.

Independent reproduction uses the real Application command router: enable quiet notifications, then run the local overlay test. The command is synchronously accepted, subsequently fails with `notifications_quiet`, and the footer correctly changes to `Command failed: notifications_quiet`. Both onboarding and editor continue showing `show: accepted · oczekuje na prezentację`. The command is rejected before an overlay lifecycle event exists, so the lifecycle-only repair cannot complete the displayed test result.

The same gap applies to queued failures such as policy/context rejection. Code inspection also finds update/remove/clear set `_local_overlay_command_id` to None and only receive generic footer command results, leaving their editor outcome accepted/awaiting presentation. Track correlated command terminal outcomes for every local action, and keep show/presentation lifecycle and command completion distinct. A later unrelated remote result must not overwrite the local result. The repaired matching displayed-lifecycle case and mismatched remote command-ID rejection both pass, but do not cover router rejection or other editor actions.

### RR-04 / QA-11 — P2: initial light theme retains white navigation icons; toggle focus remains unsafe under arbitrary accents

Locations: `ha_windows_bridge/desktop.py:63`–85, `ha_windows_bridge/ui/shell.py:958`–963; related custom focus rendering `ha_windows_bridge/ui_components.py:146`–149.

`desktop.main` constructs DesktopWindow before applying theme tokens. The constructor generates navigation icons using fallback `#f4f4f4`; `apply_theme` sets bridgeIcon later but does not regenerate the icons. The independent case replicates this exact order, processes the event loop and inspects opaque icon pixels: they remain **#f4f4f4** under the light palette. A later theme-preview event schedules a refresh, but initial light/system-light startup does not. `colorSchemeChanged` similarly calls only apply_theme, so system theme changes lack an icon refresh too.

Regenerate theme-dependent icons when applying the initial/current theme, including system scheme changes. The fixed badge token and standard QSS focus borders pass the official contrast case. However, custom ToggleSwitch still draws its keyboard focus outline with unrestricted system accent rather than a contrast-safe focus token; an accent equal to its surrounding surface makes that outline invisible. Include custom toggles when closing the original focus requirement, not only QSS buttons/fields.

## Closure matrix for all eleven original groups

| Original group | Re-review status | Evidence and limit |
| --- | --- | --- |
| QA-01 durable correlated Apply failure | PASS | Application emits correlated progress/terminal and returns after failure rather than invoking the generic wrapper error; official recovery-required case passes for footer and Overview and after EN switch. Preflight read and stop failures preserve original no-write boundaries in two passing tests. Failed draft retained. |
| QA-02 import/reset/device dirty state | PASS | `_refresh_fields` updates dirty after clearing `_refreshing`; import/reset refresh previews; inventory acceptance calls dirty update. All three official mutation cases pass. Device selection shares the checked acceptance/dirty path with disk selection. |
| QA-03 frozen pending draft | PASS | Inventory event handlers and discover path reject while pending; modal inventory acceptance rechecks pending after nested exec. Official late-discovery regression passes. Snapshot-only refresh uses discover=False and cannot alter configured EXE path. |
| QA-04 exact reviewed diagnostics | PASS | `_diagnostics` captures text before the file chooser and writes exactly it. Official nested-dialog mutation and privacy-allowlist tests pass. |
| QA-05 Computer navigation/freshness/source/values | PASS | Navigation and visible timers refresh Computer; no UI Windows poller. Official navigation test plus independent real-dataclass case pass: selected disk usage/free GB, selected device absent state, master/balance/output, advancing sample age and retained CPU value with error/read_failed. StateStore.fail_provider updates both sample and health quality, so the suspected retained-good mismatch is not present. |
| QA-06 complete PL/EN with preserved identity | FAIL / partial | Numeric telemetry and app identity preservation pass, as do footer and combo basics. RR-02 reproduces remaining description, accessible-name and live-result failures. |
| QA-07 stable monitor choice | PASS | Initial configuration resolves stable ID; refresh preserves current editor ID through inventory reorder and falls back to first available if absent. Official reorder case passes. |
| QA-08 truthful local overlay/onboarding outcomes | FAIL / partial | Matched displayed lifecycle reaches both surfaces and unrelated command IDs are excluded. RR-03 proves real asynchronous quiet rejection never reaches either local surface; other editor action terminal results are likewise unhandled. |
| QA-09 real sensor lifecycle | PASS | Diagnostics and tray share `_sensor_state_text`, derived from owned provider/audio/media/sensor services. Independent running/paused/error/stopped matrix passes; stopped+pause flag stays stopped. |
| QA-10 actual second-process activation | PASS | Inspected bounded registered Windows message -> WindowsEventBridge -> queued Qt restore path. Official event restoration passes; supervisor native actual-second-process log covers hidden and minimized with Qt and OS visibility/activity/foreground true. |
| QA-11 readable badges/icons/focus | FAIL / partial | Semantic badge text contrast passes. RR-04 independently proves light startup icon color remains white and identifies unchanged unsafe custom toggle focus rendering. |

## Additional Phase 5 workflows and regression boundaries

- Local application Start/Close now exist as separate card-menu actions. Applied enabled app, applied slug, applied start/close permissions and applied EXE path govern them; the existing command router remains authoritative. Official applied-identity and correlated terminal-result case passes. Unsaved slug/permission edits cannot redirect the action. Mouse/keyboard audio still use applied identity; snapshots programmatically update volume/mute without command emission or dirtying, consistent with the preserved original positive tests and passing official snapshot test.
- Current connection tests correctly wait through stopped/connecting and both enabled transports on a clean draft. They reset test-local transport state; no HA delivery is claimed. Dirty-draft behavior remains RR-01.
- Overview includes concrete Settings and Diagnostics recovery navigation; the official button-navigation test passes. Logs filter only the latest 200 entries, with matching bounded regression passing. Diagnostics export still excludes secret/host/user/path/log payload data.
- Apply progress is now real and request-correlated. Passing progress test rejects other request IDs. Stop/save/start/rollback transaction and ownership boundaries were inspected; no weakening of previous authorization or rollback invariants was found in this bounded re-review.
- Main window retains native framing. Native hidden/minimized restoration has real evidence. Compact page overflow and simulated DPI have supervisor evidence; these do not establish physical heterogeneous-monitor movement/hotplug, animation crossing screens, Narrator, high-contrast traversal, or native Snap. Only one physical 1920x1080 DPR1 screen is available. These remain explicit established validation limits, not new Phase 6/7 demands.
- Full keyboard completion across every new workflow is not proved by green layout tests. Standard button/menu activation uses the same callbacks, but the identified untranslated accessible labels and unsafe custom focus outline prevent an unqualified accessibility/DoD completion claim.

## Required next step

The sole implementer should fix RR-01 through RR-04, add focused official regressions for their actual failing paths, and update the handoff. Re-run the bounded targeted checks after the final production edit, then independently re-review that exact diff. Preserve this FAIL record as historical evidence if a later pass is written. Full repository gate remains blocked on independent PASS.
