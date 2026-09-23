# Phase 5 — GUI and local UX

## Status

**PASS — Phase 5 gotowa do commit/push, 2026-09-23.** Final Astra supervisor
review confirms the Phase 5 Definition of Done against the independent closure
review and the completed full repository quality gate. All eleven original QA
groups and all four rereview groups are CLOSED in
[PHASE5_CLOSURE.md](PHASE5_CLOSURE.md).

Branch: `codex/phase-5-gui-ux`, based on completed Phase 4 HEAD `95fce8f`.
No staging, commit, push, reset, history rewrite, or Phase 6 work was performed.
The working changes remain ready for the user's explicit Git authorization.

[PHASE5_FINAL_QA.md](PHASE5_FINAL_QA.md) records the independent PASS and its
retained review history. PHASE5_QA.md and PHASE5_REREVIEW.md are historical FAIL
reports whose findings are now closed; they are not the current verdict.

## Delivered behavior

The seven-page shell keeps a local draft and submits a deep-copied candidate
through the existing preflight, stop, save, autostart, rebuild, start, and
rollback transaction. Import, defaults, disk/device selection, and application
editing update dirty state. Pending Apply blocks late inventory changes.
Correlated Apply progress and terminal results keep failure and manual-recovery
guidance durable in the footer and Overview while retaining the failed draft.

Application Start and Close actions use the applied slug, executable path, and
permissions through Application.command; unsaved edits cannot redirect them.
The current connection test also uses the applied configuration. It runs with an
unrelated or connection-related dirty draft, tells the user that new connection
values require Apply, waits through stopped/connecting states, and waits for all
enabled transports before completing.

Computer shows real provider values for balance, master volume, microphone,
output, selected disks and devices, with source, health, error, age, and retained
sample information. Navigation and timers refresh visible data without a second
Windows polling path. Diagnostics filters the latest 200 records and freezes the
exact displayed JSON before the file chooser.

Polish/English refresh covers required static descriptions, choices, actions,
accessible names, live resource/update/overlay outcomes, and newly constructed
dialogs while preserving user application names, paths, stable slugs, and
observed values. Newly added and inventory-discovered application cards localize
immediately; accepted Edit and EXE-selection dialogs use the card language. Local overlay actions correlate every terminal command.result;
command completion and show presentation remain separate, and unrelated remote
results do not overwrite the local result.

Theme application regenerates navigation icons during initial and system theme
changes. System refresh uses the active draft so an unsaved theme preview is
retained. The custom toggle draws keyboard focus with the semantic high-contrast
text/focus token rather than an unrestricted accent. Native activation routes a
bounded registered Windows message through WindowsEventBridge to the existing
Qt restore path. Deferred icon refresh returns after window disposal before
accessing deleted Qt children.

## Validation on the frozen diff

Automated UI runs used Windows with QT_QPA_PLATFORM=offscreen and
-p no:cacheprovider.

- Official tests/test_phase5_gui_ux.py contributes **44 passed** within the
  required selection.
- Required 15-file targeted selection: **194 passed**.
- Unchanged original reproduction
  build/phase5-qa/test_independent_phase5.py: **14 passed**.
- Unchanged RR reproduction
  build/phase5-rereview/test_rereview.py: **9 passed**.
- Current final-closure reproduction
  build/phase5-rereview/test_final_closure.py: **4 passed**.
- Targeted Ruff over every changed production/test Python file: **PASS**.
- git diff --check: **PASS**; Git reports only existing LF-to-CRLF
  working-copy notices.

The 15-file selection was:

tests/test_phase5_gui_ux.py, tests/test_v2_desktop.py,
tests/test_v2_ui_layout.py, tests/test_alpha2_polish.py,
tests/test_alpha3_visuals.py, tests/test_alpha4_repairs.py,
tests/test_alpha5_popup.py, tests/test_phase0_regressions.py,
tests/test_phase0_apply.py, tests/test_phase1_core.py,
tests/test_v2_application.py, tests/test_v2_configuration.py,
tests/test_v2_windows_commands.py, tests/test_theme.py, and
tests/test_i18n.py.

Supervisor evidence on the same current diff:

- build/phase5-rereview/keyboard-mouse-confirmed.log and
  keyboard-mouse-native-final.log: **3/3 passed** for real Qt keyboard/mouse field
  editing, navigation, Discard, fake-adapter Apply, keyboard Start, mouse Close,
  applied-slug preservation, and quiet-router rejection. The native run used
  QtWindows with controlled adapters and no real process/audio/profile effects.
- build/phase5-rereview/native-activation-20260922.log: hidden and minimized
  actual second desktop.main processes both exited 0; the first window became
  visible, non-minimized, active, native-visible, non-iconic, and foreground.
- Current supervisor render evidence covers **112 variants** at 700×520
  across all seven pages, PL/EN, dark/light and simulated 100/125/150/200%;
  all showed no overflow; the English text inventory contained no
  Polish-diacritic labels, and inspected light/dark pages showed readable icons
  and translated feature descriptions.
- Earlier deterministic scale coverage remains green at simulated
  100/125/150/200%, alongside monitor identity reorder/hotplug regressions.

Detailed per-finding evidence is in
[PHASE5_CLOSURE.md](PHASE5_CLOSURE.md).

## Final full quality gate — 2026-09-23

The full gate ran only after independent PASS and the authoritative all-CLOSED
matrix. No production or test changes were made after this gate; final edits are
documentation only.

| Check | Result |
| --- | --- |
| Official Phase 5 tests | PASS — 44 passed |
| Complete targeted selection | PASS — 194 passed |
| Original QA / RR / final closure reproductions | PASS — 14 / 9 / 4 passed |
| Final independent closure selection | PASS — 7 passed, no deferred Qt exceptions |
| Full repository pytest | PASS — 519 passed in 65.04 s |
| Ruff (`ruff check .`) | PASS |
| `git diff --check` | PASS; only existing LF/CRLF notices |
| `pip check` | PASS — no broken requirements |
| Bandit (`-r ha_windows_bridge custom_components -ll -ii`) | PASS at repository CI severity/confidence thresholds |
| `pip-audit --progress-spinner off` | PASS — no known dependency vulnerabilities |
| Clean PyInstaller build with restricted PATH | PASS |
| Source smoke: offscreen / native Windows | PASS — exit 0 / 0 |
| Clean EXE smoke: offscreen / native Windows | PASS — exit 0 / 0 |
| Native Qt keyboard/mouse workflows on final fixes | PASS — 3 scenarios |
| Actual second-process activation/restoration | PASS — hidden and minimized |
| Final Astra supervisor review | PASS — no open findings |

Full gate logs are under `build/phase5-final-gate/`. The clean artifact is
`dist/phase5-qa-clean/HA Windows Bridge/HA Windows Bridge.exe`; isolated packaging
work files are under `build/phase5-pyinstaller-clean/`. Build used
`python -m PyInstaller --clean --noconfirm --distpath dist/phase5-qa-clean
--workpath build/phase5-pyinstaller-clean HAWindowsBridge.spec`. Source and EXE
smokes used `--smoke-test` for both Qt backends with a non-connecting test
configuration. pip-audit skipped the unpublished local `ha-windows-bridge`
project package, as in Phase 4; its installed dependencies were audited.

## Final Astra assessment against Phase 5 Definition of Done

| DoD requirement | Acceptance evidence |
| --- | --- |
| Main tasks with mouse and keyboard | Actual Qt input in offscreen and native Windows: draft editing, navigation, Apply/Discard, local Start/Close using applied identity, quiet rejection; permanent focus and command regressions. |
| Dark/light/system accent and readable focus | Semantic badge/icon/focus tests, real initial/system theme paths, draft appearance preservation, inspected current dark/light renders and safe callback disposal. |
| Compact height and DPI | All seven pages at 700x520 DIP, PL/EN and dark/light, simulated 100/125/150/200%: 112 renders without horizontal overflow; stable monitor/fault regressions retained. |
| Statuses from actual runtime state | Correlated Apply/rollback and command outcomes, distinct overlay presentation, real provider values/age/error/no-sample, actual service/connection states, safe reviewed diagnostic snapshot. |
| Existing architecture and phase boundaries | Application core, ComputerState/provider ownership, Protocol v3 and Phase 4 overlay path retained; all 519 repository tests pass. No new UI framework or Phase 6 changes. |

The final source scope, independent all-CLOSED matrix, runtime evidence and full
gate support PASS. The implementation remains uncommitted pending explicit user
approval for any future staging/commit/push.

## Validation limits

Native checks used one physical 1920x1080 DPR 1 screen. Mixed-DPI movement,
monitor faults and scale coverage are deterministic/simulated; physical mixed-DPI
transfer/hotplug, Narrator/high-contrast traversal and native Snap walkthrough
are not claimed. Source and clean EXE smoke are verified; live HA/MQTT acceptance,
installer upgrade/uninstall and long soak were not part of this Phase 5 gate.
