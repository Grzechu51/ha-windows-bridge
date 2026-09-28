# Phase 6 — Home Assistant quality, registry and migrations

Status: **PASS — final Astra review, 2026-09-28.** Independent QA and gate-fix review are CLOSED. The final full gate is complete after targeted closure and continuation; the original failed pytest run remains historical evidence. Diff is ready for user review before staging or commit.

## Current product decision and Definition of Done — 2026-09-25 evening

This decision supersedes all earlier registry-preservation requirements below.
The user explicitly accepts a breaking registry migration: old entity_id,
unique_id, device.id, device/entity automations and history continuity do NOT
need to survive. Do not retain compatibility devices or popup aliases merely
to keep old entities working.

Phase 6 must finish with:

- Exactly one config entry per persisted Bridge device_id.
- Exactly one HA device per computer and one canonical set of entities.
- No parallel Direct/MQTT devices and no compatibility-only legacy device.
- Useful entry configuration copied where possible and unambiguous; conflicts
  must be handled explicitly rather than silently discarding unknown settings.
- Deterministic, idempotent migration that can resume after interruption.
- Canonical setup and registry verification BEFORE legacy entry/device/entity
  cleanup; failed canonical setup must leave recoverable source configuration.
- No orphan registry records or new duplicates after reload/restart.
- Stable target identities after migration, including display-name changes and
  temporary capability disappearance; dynamic registry deletion stays removed.
- Correct lifecycle, translated services/errors/Repairs, private diagnostics,
  supported minimum/current real HA tests, independent QA closure and one final
  full repository gate, with no open findings.

The previously implemented preservation prototype and its two passing migration
checks are historical evidence only, not acceptance evidence for this new model.
The same implementation Sol continues from the current working tree. Valid
lifecycle evidence remains applicable unless affected behavior changes.
No staging, commit, push, history rewrite, branch change or Phase 7 is authorized.

## Baseline and scope

Verified 2026-09-23: branch `codex/phase-6-ha-quality`, clean working tree,
HEAD `4e529a8 chore: add project agent workflow`, immediate parent
`6556800 refactor: complete phase 5 GUI and local UX`. `git diff --check` passed.
Only Phase 6 is active. No staging, commits, pushes, branch changes or Phase 7.

## Baseline model and initial risks (historical)

- MQTT announcements (schema 1/2/3) populate one entry containing device metadata,
  entity definitions, media player settings and optional protocol routes.
- Entity unique IDs come from the persisted Windows profile/discovery contract;
  the active media player uses `<device_id>_media_player`. Device identifiers are
  `(ha_windows_bridge, device_id)`. Names must remain presentation only.
- Manual Direct configuration currently uses entry unique ID `<device_id>_direct`
  and popup ID `<device_id>_overlay`; MQTT uses entry ID `<device_id>` and popup
  ID `<device_id>_windows_overlay`. Both can exist for the same Bridge.
- Setup currently deletes registry entities absent from the announcement. A
  temporary provider/inventory failure can therefore destroy user customization.
- Config flow version is 1 with no explicit config-entry migration. Discovery
  updates/reloads existing entries but does not unify Direct/MQTT identity.
- Runtime owns command futures, MQTT subscriptions and Direct availability timer;
  WebSocket connection subscriptions can retain runtime references after unload.
- Setup failure closes runtime but does not explicitly roll back all forwarded
  platforms or clear runtime_data; unload leaves a closed runtime reference.
- Protocol session mutation currently shares the entry data dictionary.
- Diagnostics already uses an allowlist; services still contain untranslated
  errors. No Repairs module is present at baseline.
- HACS minimum is 2026.9.0; CI tests 2026.9.0/2026.9.1. Current stable release
  verified against the official release page is 2026.9.3.

## Implementation packages

1. Lifecycle/registry retention: partial setup rollback, unload ownership,
   pending command and WebSocket cleanup, late callback rejection, immutable
   config data, retention of absent registry entities.
2. Identity/migrations: one canonical entry/device/entity model, deterministic legacy
   cleanup after verified setup, useful configuration transfer, safe conflict
   handling through Repairs, representative upgrade/idempotency/failure tests.
3. HA quality: translated actionable errors and services, Repairs lifecycle,
   private diagnostics, documented compatibility boundary and minimum/current
   real-runtime tests. Independent QA precedes one full repository gate.

## Validation ledger

| Evidence | Result | Boundary |
| --- | --- | --- |
| Baseline local HA lifecycle/v2 runtime/authorization/entity/protocol selection | 41 passed | Python 3.13 Windows; HA doubles/contract tests, not real HA |
| Baseline cache warning | pytest cache permission warning | Tests passed; use dedicated cache or disable cache for subsequent runs |
| Real HA minimum/current | Final full suites: 35/35 each | HA 2026.9.0 and 2026.9.3; isolated Ubuntu-24.04 venvs, Python 3.14.7 |
| Independent QA | CLOSED / PASS | PHASE6_QA_FINAL.md and PHASE6_QA_GATE_ADDENDUM.md; initial FAIL retained |
| Full repository quality gate | PASS after targeted closure and continuation | 527 Windows cases covered cumulatively; all remaining checks passed; see final evidence below |

Required targeted evidence includes setup/unload/reload and partial failure,
config/entity/device migration to one model, useful settings and stable target IDs,
repeated/interrupted migration, v2/v3 compatibility, missing/reappearing
capabilities, services/selectors/errors/translations, Repairs create/remove,
diagnostics redaction, and no entry-owned work after unload.

## Authoritative external references checked

- [HA 2026.9 release and patches](https://www.home-assistant.io/blog/2026/09/02/release-20269/)
- [Config-entry lifecycle](https://developers.home-assistant.io/docs/config_entries_index/)
- [Single-entry device ownership since HA 2026.8](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)

The new HA device registry scopes identifiers per config entry. Duplicate entry
migration must account for existing device IDs and device-targeted automations;
matching an identifier alone is insufficient proof that deleting a device is safe.

## Checkpoint requested by user — WSL hardware blocker

The user authorized WSL installation, then explicitly requested a checkpoint
before restarting/configuring firmware. Do not continue into a second package
until this checkpoint is resumed. Preserve the current uncommitted work.

Environment changes completed:

- Microsoft WSL 2.7.13 installed from the official Microsoft.WSL winget package.
- VirtualMachinePlatform verified Enabled with the Windows optional-feature API.
- Boot configuration verified `hypervisorlaunchtype Auto`.
- Ubuntu installation attempted, but no runnable distribution was registered.
- Both attempts returned `HCS_E_HYPERV_NOT_INSTALLED`.
- Windows reports `VirtualizationFirmwareEnabled=False` and
  `HypervisorPresent=False` on the AMD Ryzen 5 5600 host.
- No restart was initiated. The user must restart and, if necessary, enable AMD
  SVM/virtualization in UEFI/BIOS. This cannot be completed by a repository change.

Commands after the system change:

```powershell
wsl --status
wsl --install --distribution Ubuntu --no-launch --web-download
wsl --list --verbose
```

Then provision Linux Python 3.14 and separate HA 2026.9.0 / 2026.9.3 environments,
using the dependencies and invocation in `.github/workflows/validate.yml`.
The workflow matrix now names those two versions; this is configuration only,
not evidence that either run passed. Do not run test doubles and call them a
real HA runtime result.

Resume sequence:

1. Read Git status/diff and this checkpoint; retain the existing implementation
   agent if still available, rather than repeating discovery.
2. Finish/verify the first lifecycle package against real HA. Specifically test
   errors swallowed by HA's forwarded platform setup, all platform subscriptions,
   runtime_data cleanup, pending commands and WebSocket disconnect iteration.
3. Continue identity/config-entry migrations with representative old fixtures;
   preserve entity_id, customized registry attributes and device automation IDs.
   Existing Direct/MQTT duplicate conflicts must not be solved by silently deleting
   a device. Validate safe cases and provide an actionable Repair for ambiguity.
4. Complete errors/translations/Repairs/diagnostics and compatibility documentation.
5. Independent QA with historical findings preserved; targeted closure; one full
   repository gate; final supervisor assessment. No staging/commit/push without
   explicit user authorization.

Targeted inspection notes retained for continuation:

- Windows discovery uses persisted device_id and app/device slugs. Name changes
  must not regenerate those IDs. Direct and MQTT popup IDs differ at baseline.
- Legacy schema 1/2 and protocol v2 still have explicit parsing/adaptation paths;
  retain them until tested migration makes removal safe.
- EN/PL translation key sets match at baseline, but `exceptions` and `issues`
  sections are absent. Existing service handlers raise untranslated errors.
- Official HA 2026.9.0 API sources used during review are cached under ignored
  `build/phase6-reference/`. They are supporting evidence, not project source.
- `async_forward_entry_setups` can return after HA internally handles a platform
  failure; a mocked forwarding exception alone does not prove atomic setup.
- WebSocket `ActiveConnection.async_handle_close` iterates subscriptions.values();
  an unsubscribe callback must not mutate that mapping during its iteration.
## Supervisor checkpoint review — not final QA

The first package removes dynamic entity-registry deletion, adds rollback for
propagated setup failures, drains runtime-owned command tasks on successful
unload, detaches WebSocket subscriptions, ignores late runtime callbacks, and
copies protocol state before mutating the active session. Code review also
identified and corrected accidental encoding drift and caller-task ownership.

OPEN P6-LIFECYCLE-01: Home Assistant can swallow individual platform setup or
entity-add failures and return normally from `async_forward_entry_setups`.
Current exception rollback alone does not establish atomic setup for that path.
Exercise and close this finding with real HA before the first package can be
accepted as complete. The existing partial media-player subscription test is
not evidence that the entire config entry was rolled back.

OPEN P6-VALIDATION-01: Neither HA 2026.9.0 nor 2026.9.3 was executed locally in
this session. WSL hardware virtualization blocks Linux bootstrap. New real-HA
regressions must be executed after resumption; source inspection and Windows
API doubles are not substitutes.

Identity/config-entry/entity/device migrations, Repairs, translated exceptions,
expanded diagnostics and the complete Phase 6 QA remain pending. The checkpoint
is intentionally not a Phase 6 PASS and not ready for commit approval.
## Resumed 2026-09-24 — environment unblocked

User resumed the existing work after enabling WSL2. Verified Ubuntu-24.04 VERSION 2
and Linux 6.18.33.2-microsoft-standard-WSL2 x86_64. Sandbox process initialization
still fails; authorized commands run outside that broken sandbox.

Isolated environments are under `/home/grzeg/.local/share/ha-windows-bridge-phase6/`:
`ha-2026.9.0` and `ha-2026.9.3`, both Python 3.14.7. Direct PyPI metadata confirms
2026.9.3 is current stable and both HA versions require >=3.14.2. Both initial
pip checks passed. Ubuntu-only build-essential, ffmpeg and libturbojpeg were
installed for genuine HA bootstrap; no Windows global packages were installed.
CI now installs those Linux system prerequisites, retaining 2026.9.0/2026.9.3.

Historical first real runtime FAIL is retained in `PHASE6_RUNTIME_INITIAL.md`.
The subsequent lifecycle minimum-version selection passes 8 tests in
`build/phase6-runtime/lifecycle-min-final.xml`; further whole-platform failure,
disabled-entity and recovery cases are being added before accepting the package.

SUPERSEDED by the 2026-09-25 evening decision: preserve BOTH existing registry device IDs
and BOTH popup entities under ONE config entry. The old device remains for
compatibility with device-targeted automations. Do not replace this with deleting
one device or asking users to recreate entity references.

Migration must preserve registry device.id/entity_id as well as user labels,
areas, disabled flags and names. HA identifiers collide when the legacy devices
move into one entry, so use an explicit deterministic compatibility identifier
for the legacy device while preserving its registry ID and entity assignments.
Document that narrow identifier migration; never regenerate IDs from names.

Supervisor review follow-up: `EntityComponent` retains an incomplete platform in
its per-entry map. Destroying only the platform object is insufficient for retry;
rollback/recovery tests must verify the component map is also cleaned.
## Resumed 2026-09-25 — lifecycle package accepted for migration work

Current Git/diff was inspected before continuation; existing changes were retained.
The implementation agent was reused. No repository-wide discovery or full gate ran.

P6-LIFECYCLE-01 is closed at supervisor package review: real HA swallowed platform
and entity-add failures are detected, instantiated platforms are unloaded and
removed from both component maps and global registrations, and retry succeeds.
A failed entity add also releases HA's reserved entity ID. Three consecutive
reloads then unload verify no accumulation of old platform objects.

Evidence (ignored local artifacts under `build/phase6-runtime/`):

- Windows focused lifecycle/runtime/authorization selection: 28 passed.
- HA 2026.9.0 affected file: 9 passed / 1 failed historically; the failed recovery
  was fixed and passed in `lifecycle-reservation-retry.xml` and supervisor's exact
  interrupted-test check `lifecycle-resume-recovery.xml` (1 passed).
- HA 2026.9.3 affected file: 10 passed (`lifecycle-current-final.xml`).
- New repeated reload regression: passed on minimum/current in
  `lifecycle-reloads-min.xml` and `lifecycle-reloads-current.xml`.
- Targeted Ruff and git diff --check passed. The workflow CRLF warning is not a
  whitespace error.

P6-VALIDATION-01's environment blocker is resolved; both genuine HA versions now
execute locally. This does not close the remaining migration/quality validation.
PyPI current stable was rechecked on 2026-09-25: 2026.9.3.

The narrow private HA dependency `EntityPlatform._setup_complete` is used alongside
actual loaded entity/registry checks because HA swallows setup failures. Its
behavior is verified on both supported versions. Keep compatibility tests when
updating the supported HA matrix.

Next active work: identity/config-entry/device/entity migration by the same Sol.
Canonical ownership, persisted replay journal, compatibility device identifiers,
popup aliases, disabled/custom registry attributes and authorization require real
HA migration tests. The preservation policy was superseded by the later breaking-registry decision.
HA quality, independent QA and the single final full gate remain pending.
## Supervisor quality finding — P6-QUALITY-01 (open)

Production show_overlay schema accepts non-finite progress_min values ('nan',
'inf') under real HA 2026.9.0 validation. The following range calculation raises
an untranslated ValueError. Reproduced with isolated production schema in
`build/phase6-runtime/check_service_numbers.py` while migration wiring changed.
Close with finite bounds validation, translated user error, and service-level
regression in the HA quality package. No unrelated runtime tests repeated.
## Supervisor migration review under revised decision

First canonical-model minimum-HA selection passed 4 cases
(`migration-canonical-first.xml`): new Direct identity, pair cleanup, v1 Direct
conversion and duplicate Direct-flow rejection. Further fallback/source-survival
selection passed (`migration-fallback.xml`). These are intermediate targeted
results; migration package and independent QA are not complete.

Review requirements being closed by the implementation agent:

- Seed an actual pre-existing v1 device/entity registry for upgrade tests.
- Preserve configured Direct delivery if MQTT temporarily omits its popup,
  using one canonical popup/device; retain intent across later rediscovery.
- Resume ownership-checked cleanup if source removal left journaled orphans.
- Do not roll back a verified canonical runtime because cleanup failed.
- Preserve unambiguous user settings and disabled intent.

OPEN P6-MIGRATION-02: shared runtime with MQTT protocol v2 rejects Direct protocol
v3 results because `_result` selects the v2 branch from entry.protocol regardless
of the receiving transport. Select result decoding by transport and test Direct
acknowledgement alongside MQTT v2 delivery. MQTT replies must not resolve pending
Direct commands. This is part of the one-entry transport model and compatibility
boundary, not a new project phase.
## Resumed 2026-09-27 — migration accepted, HA quality active

The prior limit interrupted the supervisor's checkpoint append, not migration
validation. Git/diff were checked before resuming. The same implementation Sol
continues; do not redesign migration without a new concrete finding.

Migration package accepted at supervisor review under the breaking-registry
product decision: entry unique_id=device_id, one ordinary device identifier
(ha_windows_bridge, device_id), one popup `<device_id>_windows_overlay`.
Legacy cleanup happens after canonical platform/entity/device readiness.
Exact-ID journal replay handles failed setup, interrupted removal and orphans;
cleanup failure keeps the verified canonical runtime online. No compatibility
legacy devices or aliases remain solely for old identities.

Evidence in `build/phase6-runtime/`:

- HA 2026.9.0: 25 passed (`migration-min-full.xml`).
- HA 2026.9.3: 25 passed (`migration-current-full.xml`).
- Later orderly restart and manual Direct-intent cases: 2 passed each on
  minimum/current (`migration-restart-min.xml`, `migration-restart-current.xml`).
- Multiple-source ambiguity preflight: 1 passed (`migration-ambiguous.xml`).
- Final source-removal/restart selection: 2 passed (`migration-final-smoke.xml`).
- Windows lifecycle/runtime/authorization doubles: 29 passed, including mixed
  MQTT v2 / Direct v3 acknowledgement isolation.
- Scoped Ruff and git diff --check passed.

The orderly restart test stops HA, flushes stores, bootstraps a new HA instance
from the same directory and verifies one entry/device/popup without old records.
This does not claim atomic multi-store recovery from hard power loss; HA owns
scheduled store writes. P6-MIGRATION-02 is CLOSED by the transport-aware result
handling and regression. No unchanged migration tests are repeated on resume.

Direct intent survives MQTT omission via direct_popup_enabled. Manual Direct
reuses an existing MQTT entry. Canonical MQTT names/areas/labels take precedence;
missing values can be filled from Direct. Direct-only retains title/options and
disabled intent. Existing target IDs remain stable on later reload/discovery.

Remaining: services validation (P6-QUALITY-01), translated user/runtime errors,
Repairs create/clear, private useful diagnostics, min/current targeted quality
validation, independent QA of all Phase 6, finding closure, then the prepared
single final full gate and final supervisor review. No staging/commit/push/Phase7.
## Resumed 2026-09-27 afternoon — quality validation continuation

Current Git status, diff --check, diff --stat and diff --name-status were reviewed.
Git retains the error-helper name-collision fix (failed_count), translated error
metadata, finite progress validation and the initial Repairs/diagnostics changes.
No migration work was reverted or repeated. Its accepted evidence above remains
valid. The same implementation Sol continues the quality package.

Remaining quality validation covers actual service calls, source-attribute
conversion (including overflowing integers), non-finite numeric values,
authorization and disabled targets, EN/PL loading and selector consistency,
Repairs creation/retry/removal, and populated/unloaded diagnostic redaction.
No independent QA or final full gate has run yet. Initial whitespace defects in
the unfinished quality diff are being removed before package acceptance.
## HA quality package accepted — 2026-09-27

P6-QUALITY-01 CLOSED: actual HA service calls reject non-finite progress bounds,
overflowing source attributes and non-normalizable progress ranges with translated
validation errors. Optional malformed media numbers are sanitized before payload
serialization. The command-failure count path no longer shadows the error helper.

Six new repository regressions in tests_ha/test_runtime.py passed on both real HA
versions (`quality-final-min.xml`, `quality-final-current.xml`, 6/6 each).
The later precise native-schema missing-notification_id assertion was rechecked
on both (`quality-actions-min.xml`, `quality-actions-current.xml`, 1/1 each).
Windows affected selection: 27/27 passed. Scoped Ruff and git diff --check passed.

Coverage includes services numeric validation, CONTROL/READ checks and disabled
targets, update/remove/clear schemas and payloads, HA EN/PL translation loading
for config/errors/Repairs/services/selectors, Repairs creation/retry/removal, and
loaded/unloaded diagnostic allowlist. Selected cases stub authorization policy
and outbound send results; failure tests inject exceptions. The HA service bus,
loader, registries and config-entry lifecycle are real. These are not a physical
broker or complete end-to-end Windows deployment test.

Repairs identify the affected entry by title and clear after successful retry or
entry removal. Diagnostics export structural allowlisted values only. User-facing
compatibility documentation records breaking registry migration and these limits.

Independent QA of the complete Phase 6 diff is now active. No full gate has run.
## Independent QA finding — resumed after usage limit

Git/status/diff and this checkpoint were checked again before continuation.
The account limit interrupted independent QA before its report file was written;
the historical reproductions remain under build/phase6-runtime:
`qa-direct-capability-min-valid.xml` and
`qa-direct-capability-current-handshake.xml`.

OPEN: a retained MQTT capability manifest without overlay.show can block a popup
on an active, separately authenticated Direct session. Windows can legitimately
leave such a manifest retained from an older configuration. The shared runtime
must not use MQTT capabilities to veto the approved Direct handshake.

The existing implementation Sol is fixing only this transport separation, with
permanent regression and targeted minimum/current validation. The same independent
reviewer continues its report and will re-review the fix. Completed migration and
HA quality packages are retained. Full gate remains NOT RUN until QA is CLOSED.
## Independent QA CLOSED — final gate authorized to start

P6-QA-01 is CLOSED by transport-specific capability validation: Direct uses the
accepted websocket handshake; MQTT retains its own manifest/route guard. Direct
capability state clears with its session. No registry migration redesign.

Historical FAIL: PHASE6_QA_INITIAL.md. Independent closure: PHASE6_QA_FINAL.md.
The reviewer found no other actionable findings. Independent replay passed on
both real HA versions (qa-direct-capability-closure-min.xml and
qa-direct-capability-closure-current-isolated.xml). A parallel reviewer bootstrap
port collision was retried in isolation and is recorded in the closure report.
Durable regression direct-manifest-min/current.xml passed each, including invalid
Direct handshake and negative MQTT guard. Affected Windows selection: 26 passed.

Starting the prepared final full gate once, after QA closure. Its HA runs are
sequential. Results will be recorded below; this entry does not claim gate PASS.
## Gate interruption and independently reviewed closure — 2026-09-28

The first final-gate pytest step recorded 468 passed, 19 failed and 40 setup errors.
Its original pytest.log/xml and failing result remain intact. The setup errors
came from inaccessible Windows pytest temp storage; exactly those 40 cases passed
with a fresh isolated basetemp under build (environment-retry.xml).

The 19 failures came from incomplete test doubles after the Phase 6 runtime and
registry changes. Only tests/test_overlay_service.py and
tests/test_phase0_ha_entities.py changed: registry attributes, translated error
helpers and platform constants were supplied, and partial-setup assertions gained
setup_failed and released-ID checks. No production code changed.

Independent review PHASE6_QA_GATE_ADDENDUM.md is CLOSED/PASS. All 19 failed case IDs
are contained in the 24-pass targeted XML; the 40 error IDs exactly match the
40-pass environment retry. All 527 Windows cases therefore have current passing
evidence cumulatively (468 + 19 + 40), not a single clean initial pytest run.
Historical failures and initial QA FAIL are retained. No tests were weakened.

The prepared resume_final_gate.py continues only the remaining gate steps. It does
not rerun the 468 already-passing Windows tests. Full HA runs remain sequential.
## Final full gate and Astra supervisor verdict — 2026-09-28

**PASS.** All Phase 6 findings are closed. The supervisor reviewed the final diff,
the independent initial/closure/addendum reports, the transport-specific fix,
the test-only fixture corrections, the exact JUnit coverage reconciliation and
the completed build/smoke/security results. No further actionable finding remains.
The approved one-entry/device/entity model and breaking migration decision are
satisfied within the documented validation boundary. Phase 7 was not started.

The gate began once after independent QA closure. Its first Windows pytest failure
was retained and resolved with targeted retries and independent review. The gate
then continued from the not-yet-run checks, without repeating the 468 initial
passing Windows cases. This is not described as one clean full pytest invocation.

| Final evidence | Result |
| --- | --- |
| Windows repository tests | All 527 original case IDs have passing evidence: 468 initial, 19 fixed fixture cases within 24 targeted passes, and 40 isolated environment retries |
| HA 2026.9.0 full tests_ha | 35 passed; zero failures, errors or skips |
| HA 2026.9.3 full tests_ha | 35 passed; zero failures, errors or skips |
| Ruff, git diff --check | PASS |
| Windows and both HA pip check | PASS |
| Bandit, configured -ll -ii gate | PASS; no findings meeting the configured severity/confidence threshold |
| pip-audit | PASS; no known vulnerabilities in audited dependencies; the unpublished local project itself is not a PyPI audit target |
| Clean PyInstaller build | PASS; dist/phase6-qa-clean/HA Windows Bridge/HA Windows Bridge.exe |
| Source smoke: offscreen and windows | Both PASS |
| Built EXE smoke: offscreen and windows | Both PASS |

Local evidence is under build/phase6-final-gate: results.json retains the initial
pytest failure and later closure, completion-summary.json reconciles the final
results, and individual logs/XML preserve all steps. Real HA final XML and exact
Python/HA versions are under build/phase6-runtime/final-2026.9.0* and
final-2026.9.3*. These ignored local artifacts are not staged deliverables.

Independent reports: PHASE6_QA_INITIAL.md (historical FAIL), PHASE6_QA_FINAL.md
(transport-finding closure) and PHASE6_QA_GATE_ADDENDUM.md (fixture/environment
closure). Historical PHASE6_RUNTIME_INITIAL.md is also retained unchanged.
Earlier checkpoint statuses and superseded product decisions below the current
Definition of Done are a chronological record, not current open findings.

Validation limits remain explicit: actual HA runs use controlled network and
selected authorization/send boundaries; no physical MQTT broker or long-running
complete Windows deployment soak is claimed. Orderly restart/store reload is
covered, not atomic multi-store hard-power-loss recovery. No remote GitHub CI,
Hassfest or HACS action execution is claimed by these local results.

Final repository boundary: branch codex/phase-6-ha-quality; HEAD remains
4e529a8, with 6556800 immediately before it. No staging, commit, push, history
rewrite or branch change occurred. The uncommitted Phase 6 diff is ready for
user inspection. Commit/push remains the user's separate decision.