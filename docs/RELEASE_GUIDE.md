# Release candidate — installation, recovery and validation

This guide describes the current source candidate, **2.0.0-alpha.11**, undergoing
Phase 7. It is not an announcement of a published or accepted release. See
[Phase 7 status](audit-2026-09-05/PHASE7.md) for evidence and outstanding gates.
Use matching Windows and HA artifacts from the accepted build. Do not substitute
an older published alpha when testing this candidate.

## Build and identify the candidate

On Windows x64 with the repository's development environment and Inno Setup:

```powershell
.\build.ps1 -SkipInstall -Installer
```

`-SkipInstall` uses the existing environment. Omit it when dependencies must be
installed using `constraints.txt`. The script runs repository tests, regenerates
version/icon resources, performs a clean PyInstaller build, checks the packaged
smoke and versions, builds the installer, and writes SHA-256 checksums.
The additional lint/security and independent QA gates are tracked in PHASE7.md.

Expected outputs in `dist`:

- `HA-Windows-Bridge-2.0.0-alpha.11-win64.zip`
- `HA-Windows-Bridge-Setup-2.0.0-alpha.11.exe`
- `HA-Windows-Bridge-HA-Integration-2.0.0-alpha.11.zip`
- `SHA256SUMS-2.0.0-alpha.11.txt`

Record the actual hashes with validation results. Rebuilding changes artifact
identity and requires repeating affected artifact checks. No signing certificate
is assumed: absent `HAWB_SIGNING_THUMBPRINT`, artifacts are unsigned and Windows
may show a publisher warning. Record signature status; do not claim signed release.

## Install

1. Use a separate Windows test account or disposable VM for acceptance. Copy the
   final artifacts there; source code, Python, `.venv` and build tools must not be
   present on that machine. Verify hashes against the candidate checksum file.
2. Run the installer as the intended user. The default installation is
   `%LOCALAPPDATA%\Programs\HA Windows Bridge`. It is a per-user desktop app,
   not a Windows service. Start from the installed shortcut.
3. Portable alternative: unpack the entire `win64.zip`; keep `_internal` beside
   the EXE. Do not mix files from different builds.
4. Back up HA before installing the matching `custom_components/ha_windows_bridge`
   directory from the integration ZIP. Restart the test HA. The declared minimum
   is 2026.9.0 and the validated matrix is 2026.9.0 / 2026.9.3. This candidate's
   publication through HACS is a separate release action.
5. Configure MQTT for sensors/audio; Direct is for overlays. Enable only needed
   features, save/apply and start services. See [quickstart](V2_QUICKSTART.md) and
   [HA compatibility and migration](HOME_ASSISTANT_COMPATIBILITY.md).

Record first-run UI, absent-server behavior, actual transport recovery, command
delivery, overlay display and clean exit. A `--smoke-test` exit alone does not
prove connectivity, installation or daily GUI usability.

## Upgrade

Before upgrading, exit Bridge from the tray. Back up the entire
`%LOCALAPPDATA%\HAWindowsBridge` directory and take a HA backup. The 2.0 profile is
`profile-v2.json`; its credentials use DPAPI bound to the Windows account. Keep
the backup private. A settings export contains no credentials and is not a full
credential backup.

Test at least a representative earlier 2.0 release with a populated profile and
autostart enabled. Record its exact version and installer hash. Install the
candidate over that installation, then verify feature selections, `device_id`,
credentials, autostart path and one running process. The installer replaces its
bundled runtime so old Qt DLLs cannot remain mixed with the new build.

For a 0.x profile, 2.0 does **not** silently migrate `config.json`; configure 2.0
explicitly and retain the old file as backup. Test this separately if 0.x upgrades
are part of the intended distribution.

The Phase 6 HA registry migration is breaking: old entity IDs and history may
change. Check Repairs, dashboard and automation references after migration.
Subsequent reload/restart of the canonical model must retain its identity. Do not
delete migration journals or compatibility adapters as a cleanup shortcut.

## Recovery

- **Connection unavailable:** check the displayed reason, broker/HA reachability,
  credentials, enabled overlay capability and HA permissions. Restore the service,
  then use reconnect if needed. Authentication/configuration failures need correction;
  repeated retries are not proof of recovery. Verify a fresh state change or command.
- **Partial apply / recovery required:** keep the existing profile and diagnostic
  evidence, correct the reported error and retry. If still blocked, quit normally
  and restart. Do not run two copies to bypass an unfinished shutdown.
- **Invalid or truncated profile:** close Bridge, copy the broken file for diagnosis,
  restore a known-good `profile-v2.json` under the same Windows account and restart.
  If no backup exists, rename the broken profile (do not overwrite it), start with
  defaults and re-enter credentials. A leftover `.json.tmp` is not an accepted profile.
  Test this only in a disposable account; never corrupt the user's active profile.
- **DPAPI error after account/machine move:** import public settings and re-enter
  secrets under the new account. Copying encrypted credentials does not guarantee
  portability. Keep the original backup until recovery is verified.
- **HA Repairs / migration conflict:** preserve the HA backup, resolve the exact
  conflict named in Repairs and reload. Do not manually delete registry entries or
  `.storage` journals to make the warning disappear.
- **Forced process termination:** only on a test instance, after saving and backing
  up the profile. Restart, verify mutex acquisition, profile preservation and new
  transport sessions. Do not equate this with hard-power-loss filesystem testing.
- **Rollback:** retain the prior installer and both profile/HA backups. Exit the
  candidate and restore the matching prior application/profile/HA state. Downgrading
  only the EXE does not reverse a breaking HA registry migration.

Use Diagnostics for a previewed report. Soak evidence is numeric telemetry, not a
replacement for the application's visible error details. Record the error category
and time; avoid sharing credentials, raw profile contents or notification payloads.

## Uninstall and autostart acceptance

On the isolated test machine, enable start with Windows in settings, save/apply,
then sign out/in. Verify one instance and the selected minimized behavior. Inspect
HKCU `Software\Microsoft\Windows\CurrentVersion\Run`, value `HAWindowsBridge`:
it must launch the installed EXE with `--autostart`, without a source or `.venv` path.
Disable/re-enable and repeat after upgrade.

Quit from the tray and uninstall through Windows Settings. Verify installed files,
shortcuts and the Run value belonging to this installation are removed, and no app
or child process remains. This product does not install a service. The user profile
is intentionally preserved for reinstall; credentials remain encrypted. Removing
personal configuration is a separate explicit user action, never an uninstall side
effect. An autostart value targeting a different portable installation must survive.

## Interactive fault and accessibility record

Use a dedicated broker/HA and the test Windows account. Each row in PHASE7.md needs
an actual result, timestamp, artifact hash, action, expected/observed behavior and
recovery time. A useful record format is:

```text
case | UTC fault time | UTC service healthy | UTC current state confirmed |
result | artifact SHA256 | observations / evidence file
```

Run start without each server, broker/HA restart, integration reload, 10-minute
network loss, sleep/resume, lock/unlock, audio/display hotplug, Explorer restart,
overlay expiry during reconnect, repeated apply/restarts and clean/forced exit.
Use ten repeat cycles for config apply, reconnect and restart checks. Do physical
fault testing separately from the uninterrupted 24h soak if it would invalidate
process continuity or sample coverage. Never interrupt the user's production HA,
network, Explorer or Windows session without permission.

Keyboard-only checks: navigate every page, operate toggles/sliders, save/discard,
open/close dialogs and return from tray. Focus and error text must remain visible.
Test 100%, 150%, 200% DPI, light/dark/high contrast, Windows reduced animation plus
app reduced motion, and screen-reader labels. Check timed and pinned overlays on
each monitor, mixed DPI and after display removal. Record native visual evidence;
offscreen assertions do not certify this matrix.

## Soak procedure and decision

Acceptance requires 24h on the final artifact, with no AI session needed. Copy
`tools/soak_monitor.ps1` to the test machine; Python and source code are not needed.
Close any already-running Bridge normally first: a second launch activates the old
instance and cannot enable telemetry for it. Launch the accepted installed EXE with
an absolute telemetry path, then run the monitor in PowerShell:

```powershell
$soakRoot = Join-Path $env:LOCALAPPDATA ('HAWindowsBridge\soak-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $soakRoot | Out-Null
$telemetry = Join-Path $soakRoot 'telemetry.json'
$bridgeExe = Join-Path $env:LOCALAPPDATA 'Programs\HA Windows Bridge\HA Windows Bridge.exe'
Start-Process -FilePath $bridgeExe -ArgumentList @('--soak-telemetry', ('"' + $telemetry + '"')) -WindowStyle Hidden
.\soak_monitor.ps1 -TelemetryPath $telemetry -OutputDirectory (Join-Path $soakRoot 'run') -ExpectedExePath $bridgeExe -DurationHours 24 -IntervalSeconds 5
```

If running from the repository, use `.\tools\soak_monitor.ps1` for the last command.
Confirm the normal app is connected and telemetry is fresh before beginning the
acceptance run. Start the enabled services from the GUI if auto-connect is disabled.
Do not use `--smoke-test` for soak: it deliberately exits and never connects services.

`samples.csv` records UTC, status, PID/uptime, working set, private memory, handles,
threads, whole-machine CPU, telemetry age, warning/error counts and transport
failure/reconnect/recovery counters and timestamps. `summary.json` records coverage,
invalid samples/gaps, warm baseline, latest sample and peaks. `telemetry.json` is
an atomically replaced snapshot; CSV retains sampled history. Telemetry contains
allowlisted states and counters, not log messages, credentials or configuration.
It is opt-in and must be enabled again after a normal app restart.

Use `-DurationHours 0.01` for a short monitor check; it must report an incomplete
acceptance run. Ctrl+C ends observation; preserve the partial CSV/summary and start
a new output directory for acceptance. A hard kill of the monitor may leave only
CSV; that is incomplete evidence. Do not reuse/overwrite an existing output directory.

Keep a 30-minute warm baseline and a written reference workload/budget before the
long run. Keep the PC awake for the uninterrupted soak; exercise suspend/restart
separately in the fault matrix. Retain samples, summary, final telemetry and manual
fault record together. A transport's outage-to-connected duration does not measure
the time from network restoration to confirmed fresh HA state; record those two
external timestamps separately for the <=10s recovery target.

During the acceptance run you may work normally: browse, use office applications,
play audio/video and lock/unlock the screen. Keep the same Bridge process and
monitor PowerShell session running, with the configured services available. Screen
locking is fine only if Windows will not subsequently sleep. Do not restart or
update Bridge, reboot/shut down Windows, sign out, suspend/hibernate or close the
laptop lid if that suspends it. Those actions belong to the separate fault matrix
and require a fresh uninterrupted run afterward. Avoid changing the measured
feature/overlay/capture configuration mid-run. Record unusual workloads and times;
evaluate idle CPU only in matching idle windows, not while gaming or rendering.
An unexpected outage should be retained as evidence, not hidden by restarting the
monitor or replacing its files. Preserve that run, diagnose it and start a new
output directory when ready to retry.

Acceptance: complete observation coverage, no unexplained crash/restart or app
errors, stable private memory/handles/threads across matched workload windows,
idle CPU below the reference target, working commands/providers and bounded
recovery. Review deliberate fault warnings separately. Missing data or an untested
row remains PENDING. `PENDING_REVIEW` means the monitor completed its observation
checks and still requires review of resource trends, enabled workload and physical
evidence. `INCOMPLETE_OR_FAIL` requires addressing the listed reasons. Neither is
a final Phase 7 PASS. Optional 48–72h confidence runs are not required for acceptance.
