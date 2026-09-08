# Phase 3 — Windows providers and energy

This document records the implemented runtime boundary. It does not change the
architecture approved in REPORT.md and does not include overlay or GUI redesign.

## Flow

Before Phase 3, sensor-scheduler called Core Audio, WinRT, psutil, WMI, WUA and
subprocess adapters itself. A slow WUA, WMI, GPU or media call could delay every
other observation. The configuration UI also had an independent inventory read.

The active path is now:

    Windows API -> owned provider -> ComputerState -> GUI/HA projection
                -> StateOutbox -> MQTT transport

ComputerState distinguishes a successful empty collection from unavailable
data. A failure retains the last good value, changes provider health, and never
masquerades as endpoint, media-session, disk, or PnP removal. Generation and
sample-epoch guards discard callbacks and I/O results from an old runtime.

## Owners and scheduling

| Source | Owner | Event wake-up | Polling fallback | Disabled behavior |
| --- | --- | --- | --- | --- |
| Core Audio master, endpoint, microphone, app sessions | audio provider, one MTA thread | endpoint volume, default device, device hotplug, new session | adaptive from configured interval to 10x / at least 5 s | no audio provider when every audio capability is disabled; inventory is one-shot |
| GSMTC media | media provider plus one WinRT asyncio owner | current session, session list, playback, metadata, timeline | adaptive from configured interval to 10x / at least 5 s | no media owner unless media/overlay needs it |
| Desktop/session | desktop_context provider | WTS lock/unlock and display change | configured interval, backing off to 5x / at least 2 s | no worker |
| Processes | processes provider | none | 0.5 s minimum, backing off to 10x / at least 5 s | no worker |
| CPU/RAM | cpu_ram provider | none | 0.5 s minimum, backing off to 10x / at least 5 s | no worker |
| GPU/hardware sensors | gpu provider | none | 5–30 s | no worker |
| Power/restart health | windows_health provider | suspend/resume | 30–300 s | no worker |
| Windows Update | windows_update provider and one tracked WUA I/O | none | 30 minutes, 15 s read deadline | no worker |
| Storage | storage provider | WM_DEVICECHANGE | 5–60 s | no worker; inventory is one-shot |
| PnP | pnp provider | WM_DEVICECHANGE | 10–120 s | no worker; inventory is one-shot |
| Network wake-up | transport lifecycle remains separate | device change and resume emit windows.network_changed | transport-owned reconnect only | no sensor poller |

Callback bodies only signal/coalesce refresh work. They do not enumerate
Windows, mutate ComputerState under a provider lock, publish to the network, or
call GUI code. Provider reads run outside locks. Slow providers have independent
workers; WUA timeout and unfinished shutdown are explicit health/lifecycle
failures.

## Identity, source and units

- Audio endpoints use the Core Audio device ID. Application session aggregates
  retain every Core Audio InstanceIdentifier (Identifier/PID fallback).
- GSMTC state includes the Windows source_app_user_model_id as session_id.
  Commands use the observed ID as a compare-before-execute guard, so a newly
  selected player cannot receive a command intended for a disappeared session.
- Disk health comes from MSFT_PhysicalDisk.HealthStatus. Temperature is queried
  separately from MSFT_StorageReliabilityCounter.Temperature; legacy SMART is a
  health fallback only.
- NVIDIA nvidia-smi fan.speed is published as gpu_fan in percent. Actual RPM
  from Libre/OpenHardwareMonitor is a separate gpu_fan_rpm metric.
- The existing gpu_fan entity keeps its stable unique ID and topic. Its discovery
  unit changes from rpm to percent, allowing Home Assistant to update the entity
  in place; no registry deletion is performed.

## Compatibility and deferred work

The low-level WindowsAudioService and WindowsSystemMonitor methods remain as
compatibility adapter seams and for one-shot configuration inventory. Production
telemetry and commands receive state-backed facades/owners. Existing MQTT entity
topics and Protocol v3 remain unchanged; session_id is an optional additive
media-state field. MQTT and Direct HA retain their independent lifecycle.

Capture, overlay behavior, GUI redesign, and broader Home Assistant registry
polish remain deferred to Phases 4–6.
