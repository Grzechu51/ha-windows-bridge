# Phase 6 independent QA — full-gate finding closure addendum

Date: 2026-09-28. Status: **CLOSED / PASS for independent review of gate fixes**.
This adds to PHASE6_QA_FINAL.md. PHASE6_QA_INITIAL.md and the first full-gate
pytest failure artifacts remain unchanged historical evidence. The remaining
full-gate checks and final supervisor verdict are still separate requirements.

## Initial gate result and classification

The first full-gate pytest run recorded 468 passed, 19 failed and 40 errors
(527 collected cases), in build/phase6-final-gate/pytest.xml and pytest.log.
It was not a clean single-run PASS. Review identified two causes:

| Gate finding | Classification and correction | Evidence | Status |
| --- | --- | --- | --- |
| P6-GATE-01: 19 failures in overlay services, media partial setup and the shared progress-service regression | Outdated Windows test doubles lacked the Phase 6 HA registry/runtime contract. Only tests/test_overlay_service.py and tests/test_phase0_ha_entities.py changed. | impl-targeted-24.xml: 24 passed, no failures/errors/skips; all 19 originally failing case IDs are included. | CLOSED |
| P6-GATE-02: 40 tmp_path setup errors | pytest could not access the existing Windows temporary root (PermissionError, WinError 5). The targeted retry uses a new dedicated basetemp under build. No production change or test assertion change was needed. | environment-retry.xml: exactly the same 40 case IDs as the initial errors, all passed. | CLOSED |

## Independent review of corrections

The service harness now supplies the real registry attributes domain, platform
and disabled_by, the Platform.NOTIFY value, and translated-error helper doubles
with the existing exception-message behavior. Existing content, permission,
numeric-source and progress-patch assertions were retained. The progress test
uses this shared harness; its production path and assertions were not weakened.
Actual HA translation and exception-metadata behavior remains covered by the
previously accepted real-HA quality evidence.

The media partial-setup fixture now supplies entry.runtime_data.setup_failed,
entity_id and the HA state-registry cleanup surface used by the Phase 6 rollback
path. Existing exact subscription acquisition/removal, no-double-cleanup and
media-value assertions remain. Additional assertions require setup_failed and
release of the reserved entity ID. No production exception was swallowed to make
the tests pass, and no case was skipped or removed.

The changes after the earlier QA closure are confined to those two test fixtures.
No new production defect was found. Previously validated real HA migration,
lifecycle and quality behavior remains applicable; those tests were not repeated.

## Coverage reconciliation

The reviewer compared JUnit case identities as classname::name, including each
parameterized case suffix:

- Initial errors: 40. environment-retry.xml: 40 cases, zero failures/errors;
  the two identity sets are equal.
- Initial failures: 19. impl-targeted-24.xml: 24 cases, zero failures/errors/skips;
  every initial failure identity is present (zero missing).
- The 468 initial passing cases remain valid because these fixes only complete
  the affected fixtures; the retry also includes five previously passing cases
  from the affected media parameterization.

Therefore all 527 initial Windows cases now have applicable passing evidence
across the original run and targeted retries. This is cumulative evidence, not
an assertion that one full pytest invocation passed. Commands and selection are
retained in impl-targeted-24-validation.txt and environment-retry-selection.txt;
retry stdout and JUnit artifacts are in build/phase6-final-gate. Scoped Ruff and
git diff --check also passed for the fixture changes.

No open independent-review findings remain. Resume only the prepared,
not-yet-executed checks of the same full gate, retaining the original failure
and targeted closure artifacts. Do not claim the complete Phase 6 or full gate
has passed until those remaining checks and the supervisor review finish.
No staging, commit, push or Phase 7 work was performed by this reviewer.