# Phase 6 independent QA — closure and final review

Date: 2026-09-27. Status: **CLOSED / PASS for independent QA**.
The historical initial FAIL remains in PHASE6_QA_INITIAL.md. The final full gate
and supervisor's Phase 6 verdict are separate requirements and were not run by
this reviewer.

## Closure matrix

| Finding | Correction reviewed | Evidence | Result |
| --- | --- | --- | --- |
| P6-QA-01 (P2): older MQTT manifest suppresses valid Direct fallback | Direct capability names are stored from the validated websocket.connect handshake and checked independently. MQTT commands continue to use MQTT routes and manifest. Direct capability state clears on detach, expiry and close. | Independent reproduction passed on HA 2026.9.0 and 2026.9.3; durable test additionally rejects invalid Direct handshake and disallowed MQTT overlay. | CLOSED |

The implementation is confined to runtime.py, websocket.py and a regression in
tests_ha/test_runtime.py. It does not alter the completed registry migration,
MQTT authorization, discovery IDs or one-entry model. The fallback command still
requires a live authorized Direct connection and a valid protocol session.

## Evidence

Independent replay of build/phase6-runtime/test_independent_qa.py:

- qa-direct-capability-closure-min.xml: HA 2026.9.0, 1 passed, 0 errors/failures.
- qa-direct-capability-closure-current-isolated.xml: HA 2026.9.3, 1 passed,
  0 errors/failures.

The first current-version closure attempt, qa-direct-capability-closure-current,
failed before integration setup because two reviewer bootstrap processes competed
for port 8123 (Errno 98, address already in use). Only that invalid run was retried
in isolation. Its log is retained; it is not evidence of an integration defect.
The runner's HA invocations must be sequential with the present fixed-port fixture.

Durable implementation regression reviewed and its existing results checked:

- test_direct_handshake_capability_is_independent_of_retained_mqtt_manifest:
  direct-manifest-min.xml and direct-manifest-current.xml, 1 passed each.
- Invalid Direct capability handshake is rejected without acquiring an owner;
  an accepted overlay.show/direct handshake succeeds despite the older MQTT
  audio-only manifest; a disallowed MQTT overlay still raises capability_unavailable.
- Implementation agent's affected Windows runtime/lifecycle selection: 26 passed.
- Scoped Ruff and git diff --check passed; the reviewer also rechecked diff --check.

All other Phase 6 lifecycle/migration/quality evidence reviewed in the initial
report remains applicable. Unchanged migrations were not rerun. No further
open or deferred actionable findings remain from the independent review.

## Scope and limits

Review covered the Phase 6 tracked diff and new integration/migration/errors/
Repairs and compatibility documentation. Breaking registry IDs are intentional;
no compatibility-only device or alias was requested. Real HA bootstrap, config
flows, entities, registry lifecycle, services and translation loader were covered
by the accepted evidence. Network and selected connection/send/permission
boundaries are controlled, as documented. No physical-broker or complete Windows
installation soak is claimed; orderly HA restart does not prove atomic multi-store
recovery after hard power loss.

The prepared one-time final full gate may now run. This QA PASS is not a claim
that that gate, remote CI, or the final Astra supervisor review has already passed.
No staging, commit, push, history rewrite or Phase 7 work was performed.