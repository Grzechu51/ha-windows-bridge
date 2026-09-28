# Phase 6 initial real Home Assistant runtime — historical FAIL

Date: 2026-09-24. This report is immutable historical evidence, not final QA.

Environment: Ubuntu-24.04 WSL2 x86_64, Python 3.14.7, real Home Assistant
2026.9.0. Only MQTT delivery is replaced by the existing test boundary; HA
bootstrap, config entries, entity platforms and registries run real code.

Result: **2 failed, 5 passed**, 50.62 seconds.
Artifact: `build/phase6-runtime/ha-2026.9.0-initial.xml`.

| Finding | Evidence | Required correction |
| --- | --- | --- |
| RT-01 test assumption | Missing capability retained its customized registry entry and HA restored its state as unavailable; test expected no state | Assert registry/customization preservation and unavailable state, then successful restoration |
| RT-02 partial rollback | Unloading platforms never loaded raises ValueError; aggregate unload returns false and runtime_data is retained | Roll back only the entry platforms actually instantiated; test platform and entity-add failures separately |

Bootstrap also logged absent ffmpeg and inability to compile pymicro-vad because
Ubuntu had no C++ compiler. These are environment deficiencies to resolve before
accepting a clean runtime run. Installing build-essential, ffmpeg and libturbojpeg
is scoped to Ubuntu WSL; Python packages remain in isolated per-HA venvs.

Version verification before tests: direct PyPI metadata reported latest stable
2026.9.3; both 2026.9.0 and 2026.9.3 require Python >=3.14.2. Isolated venvs for
both versions installed successfully and initially passed pip check. The existing
uncommitted CI matrix 2026.9.0/2026.9.3 is therefore current; no additional version
change was necessary.

P6-LIFECYCLE-01 (HA swallowing platform errors) remains open pending implementation
and real-runtime validation. Independent QA and the full gate have not run.