# Phase 6 independent QA — initial FAIL

Date: 2026-09-27. Independent reviewer, separate from the implementation agent.
This is immutable historical evidence. Later fixes and closure belong in a
separate report; this initial verdict must not be replaced with PASS.

Scope: the complete Phase 6 working-tree diff and new integration, migration,
Repairs, error-helper and compatibility documents against AGENTS.md and the
current breaking-registry product decision. Git status, diff --check, diff
--stat and diff --name-status were inspected. No broad repository discovery,
full gate, staging, commit, push or Phase 7 work was performed.

## Initial verdict

**FAIL / OPEN**: one confirmed functional finding, P6-QA-01 (P2).
No additional actionable findings were identified in the reviewed Phase 6 diff.

### P6-QA-01 — MQTT retained capabilities suppress a valid Direct fallback

Location: custom_components/ha_windows_bridge/runtime.py, BridgeRuntime.start
and BridgeRuntime._send (initial review lines 74-81 and 276-286).
The new one-entry fallback subscribes to MQTT capabilities even when its popup
uses Direct. The initial _send implementation then checks the active Direct
command against self.capabilities, which contains the MQTT manifest, rather than
against the capabilities validated by the new Direct connection handshake.

A previously published MQTT profile with overlay_enabled=False has no overlay.show
capability (ha_windows_bridge/communication/protocol.py, route construction and
capabilities()). The gateway publishes that manifest retained
(ha_windows_bridge/communication/gateway.py). A newer Windows session can enable
Direct overlay and connect to HA while its MQTT connection is unavailable. HA
can still have the older retained manifest. The valid Direct handshake succeeds,
but sending its popup raises translated capability_unavailable before any command
reaches the Direct sender. This defeats the configured Direct fallback in the
new consolidated entry model.

Expected: validate Direct commands using the currently authorized Direct
connection contract; retain MQTT route/capability validation for MQTT commands.
A stale or different-session MQTT manifest must not disable a newer valid Direct
session. Do not weaken MQTT validation or change the completed registry migration.

Reproduction source: build/phase6-runtime/test_independent_qa.py (ignored local
artifact). It creates a real HA Direct entry, discovers a schema-3 MQTT bridge
without a popup, supplies an older MQTT manifest containing audio only, establishes
a newer Direct session advertising overlay.show/direct, and sends a popup.

- HA 2026.9.0: qa-direct-capability-min-valid.xml, 1 failed;
  HomeAssistantError: Capability is not available on this transport. This first
  valid reproduction attached the Direct sender through runtime.attach.
- HA 2026.9.3: qa-direct-capability-current-handshake.xml, 1 failed; same error.
  This version passes the actual websocket.connect handler and its capability
  validation before sending, with a controlled authorized connection.
- The earlier qa-direct-capability-min.xml had an invalid protocol fixture
  (KeyError before the relevant path) and is not finding evidence.

Closure requires a durable regression using an accepted Direct handshake with
stale MQTT capabilities, a negative MQTT-capability assertion, targeted passes
on both supported HA versions, and independent review of the exact fix.

## Other reviewed areas and reused evidence

Lifecycle ownership, rollback of swallowed HA platform/entity failures,
WebSocket subscription cleanup, runtime cancellation and late callbacks were
reviewed against the already accepted real-HA lifecycle/reload evidence.

Canonical entry/device/popup identity, migration preflight and exact ownership
checks, journal replay, cleanup after verified setup, useful setting transfer,
ambiguous-source rejection and orderly restart were reviewed. The user's accepted
breaking migration was applied; preservation of old registry IDs was not required.
Existing migration-min-full/current-full (25 passes each), restart selections and
orphan/retry regressions remained valid and were not rerun without cause.

Services validation and authorization, disabled targets, numeric overflow and
non-finite handling, translated exceptions, EN/PL loading and placeholder parity,
service selectors, Repairs creation/clear paths and diagnostic allowlisting were
reviewed. Existing quality-final-min/current (6 passes each) and quality-actions
(1 pass each) evidence was reused. Diagnostics serialize structural allowlisted
scalars/counts, not entry data, identities, topics or runtime payloads.

## Validation boundaries

Reproductions use actual HA 2026.9.0/2026.9.3 in isolated WSL Ubuntu environments.
The network MQTT boundary, authorized connection and outbound Direct sender are
controlled; this is not a physical broker or complete Windows deployment test.
Previously accepted orderly HA stop/start evidence does not claim atomic
multi-store recovery from hard power loss. The final full gate was deliberately
not run before finding closure. This report alone is not a final Phase 6 PASS.