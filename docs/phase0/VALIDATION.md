# Phase 0 — wykonanie i walidacja

Data: 2026-09-06. Specyfikacja: [REPORT.md](../audit-2026-09-05/REPORT.md), sekcja 19, Phase 0. Punkt odniesienia: `0df284b423ecf7c3e78563028fdab9e65d0c4270`, wersja `2.0.0-alpha.8`.

Wdrożono wyłącznie blokery i reprodukcje Phase 0. Nie wykonywano ponownego pełnego audytu ani nowej architektury. Oryginalne REPORT.md i INVENTORY.md pozostawiono bez zmian. Przed pracą katalog audytu był już nieśledzony przez Git.

## Definition of Done

| Kryterium REPORT.md | Wynik / granica weryfikacji |
| --- | --- |
| Regresje C/H objęte Phase 0 przechodzą | C01, H01, H02, H03 i H09: lokalne testy przechodzą. H02 ma dodatkowo przygotowane testy na rzeczywistych platformach HA. |
| Istniejące 274 testy bez utraty zakresu | 274 testy przed zmianami przeszły. Końcowo 336 testów przechodzi, bez usunięcia istniejących testów lub osłabienia ich asercji. Rozszerzono tylko kontrakt atrap publishera i autostartu w test_v2_application.py. |
| Min/latest HA setup sprawdzony | **Oczekuje na Linux CI.** Przygotowano prawdziwy bootstrap/import/config flow/setup/reload/unload dla HA 2026.9.0 i 2026.9.1. Lokalny Windows nie jest dowodem zgodności HA. Zgodnie z decyzją użytkownika brak Linux/WSL/Dockera nie blokuje pozostałych prac. |
| Raport metryk procesu z konfiguracją referencyjną | Zakończony pomiar 1800 s po 30 s rozgrzewki, 1801 próbek. Wyniki i ograniczenia poniżej oraz w BASELINE.json. |

Nie deklarujemy pełnego zweryfikowania DoD przed zielonymi zadaniami `ha-runtime` na obu wersjach HA.

## Zmiany i reprodukcje

| ID audytu | Naprawa przyczyny | Testy |
| --- | --- | --- |
| C01 / P06 | ConnectionMachine aktualizuje stan pod lockiem, a emituje zdarzenia po jego zwolnieniu. Publisher wykonuje transport I/O oraz callbacki poza swoim lockiem. Reconnect jedynie oznacza replay do wykonania przez scheduler. | Dwa rzeczywiste wątki i kontrolowane zdarzeniami przeploty gateway/publisher/connection machine; odczyt stanu z osobnego wątku podczas każdego przejścia MQTT i Direct. |
| H01 / P01 | Oddzielny cache obserwacji i dirty. Odczyty offline trafiają do publishera. Nieudane wysłanie/wyjątek/replay pozostają do ponowienia. Odpowiedź starego wysłania nie czyści nowszej obserwacji lub sesji. Scheduler ponawia także podczas pauzy sensorów. | 20 → 80, false/wyjątek send, reconnect, offline i nieudany replay, równoległa zmiana, QoS, retained deletion; brak replay komend/results. |
| H02 / P04, M19 | Oba odtwarzacze natychmiast rejestrują cleanup każdej subskrypcji. Przy wyjątku/cancellation jawnie wywołują add_to_platform_abort, bo HA nie robi tego automatycznie po błędzie async_added_to_hass. | Lokalne pełne moduły z atrapą API: poprawny setup, głośność/mute i każdy punkt częściowego setupu. Osobne testy prawdziwego HA w tests_ha. |
| H03 / P07 | Scoped CoInitializeEx/CoUninitialize w wątku wykonującym odczyt. Pożyczone STA nie jest zwalniane przez providera. WMI zwraca zwykłe wartości; proxy nie wychodzą z apartmentu. Awaria nie jest utrwalana jako pusty sukces. WUA używa tego samego ownership. | Własny/pożyczony apartment, failure init/query, zwolnienie proxy, ponowienie identity/GPU/disk, PnP unavailable i recovery, błąd WUA. Rzeczywisty odczyt CPU z nowego wątku na Windows również przeszedł. |
| H05 | Minimum HACS zmienione z nieprawdziwego 2025.1.0 na wybraną linię wsparcia 2026.9.0; aktualna wersja macierzy 2026.9.1. | Rzeczywiste testy Linux CI przygotowane, **jeszcze niewykonane**. |
| H09 / P11 | Rollback obejmuje zapis, autostart, budowę i start usług; przywraca faktyczny poprzedni autostart i intencję running/stopped. Błąd rollbacku daje jawne configuration_rollback_failed, bez configuration.changed. | Awaria każdego etapu w running/stopped, częściowa zmiana autostartu, nieudany stop i nieudany rollback, także błąd startu przechwycony przez supervisor. |
| M01 / P02 | Pierwsza enumeracja i zmiana wyjść audio zgłaszają inventory_requested; brak wywołania nieistniejącej metody. | Pierwsze wyjście, brak zmiany, hotplug. |
| M06 / P03 | Update overlay pomija niepodane title/message. Jawne puste pole nadal czyści zawartość. | Istniejący harness usługi HA → rzeczywisty NotificationEngine; progress-only zachowuje tekst i pinned. |
| P05 | Porównanie wersji przez packaging.Version uwzględnia alpha/rc/stable. | Alpha → stable, rc → stable, kolejna alpha, starsza alpha i identyczna wersja. |
| M02 / P08 | HealthStatus pochodzi z MSFT_PhysicalDisk, Temperature z MSFT_StorageReliabilityCounter. | Ścisła walidacja dwóch zapytań; nieudany odczyt nie zapisuje udanego timestampu cache. Mapowanie fizyczny dysk/wolumin pozostaje na Phase 3. |
| M04 / P09 | Budżet pełnego skonfigurowanego inventory, tras i payloadu sprawdzany przed zapisem/DPAPI. Zachowane limity HA; bez cichego obcinania encji. | 63/64/128 aplikacji, opcjonalne funkcje, zgodność z dekoderem HA; odrzucenie przed zapisem i seal. |
| M09 / P10 | Typ platform sprawdzany przed membership. | Lista, słownik, null, bool i liczba są kontrolowanie odrzucane. |
| M15 / P12 | Commit slidera również dla klawiatury/kółka; snapshot nie wysyła komendy, drag emituje po zwolnieniu. | Prawdziwy Qt AppCard: Right, wheel, drag i programowe odświeżenie. |

`telemetry.published` i wyczyszczenie dirty oznaczają przyjęcie przez obecny interfejs transportu/Paho, **nie PUBACK ani potwierdzenie HA**. Obserwacja pozostaje w cache, a nowa sesja oznacza pełny replay. Polityka PUBACK i bounded outbox pozostają na Phase 2. Nie wprowadzono Protocol v3.

Nowe testy C01/H01/H02/H09 uruchomiono też na odizolowanym kodzie z HEAD sprzed zmian. Wynik kontrolny: **20 oczekiwanych failures, 4 passed, 8 deselected**. Log: `build/phase0-red.log`. Upewniono się, że import pochodzi z odizolowanego katalogu, a nie z edytowalnej instalacji bieżącego kodu. Te celowe failures nie są wynikiem końcowej walidacji.

## Wyniki lokalne — Windows

Środowisko: Python 3.13.5, repozytoryjne `.venv`, Qt offscreen. Katalog tymczasowy pytest znajduje się w `build/`, aby ominąć ograniczenia dostępu do domyślnego TEMP.

| Kontrola | Wynik |
| --- | --- |
| Pytest przed zmianami | 274 passed, 17.24 s |
| Pytest końcowy | **336 passed, 13.97 s**; `build/phase0-pytest.xml` |
| Ruff, całe repo | PASS |
| pip check | PASS — No broken requirements found |
| Bandit `-ll -ii` | PASS — 0 medium, 0 high; 1 low (istniejący jitter random), 10 istniejących wyłączeń konkretnych reguł |
| pip-audit | Brak znanych podatności w sprawdzanych bibliotekach; lokalny projekt 2.0.0a8 pominięty, ponieważ nie występuje w bazie PyPI |
| PyInstaller | PASS; `build/phase0-pyinstaller.log` |
| Gotowy EXE `--smoke-test` | PASS, kod wyjścia 0, uruchomiony ukryty/offscreen |
| Rzeczywisty WMI CPU w nowym wątku | PASS, 1 wiersz Manufacturer=AuthenticAMD; wątek zakończony |
| git diff --check | PASS |
| YAML workflow / składnia tests_ha | PASS; nie jest to wykonanie runtime HA |

Polecenia końcowe/reprodukcja z katalogu repozytorium:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider --basetemp build/phase0-complete-rollback-temp --junitxml=build/phase0-pytest.xml
.venv\Scripts\python.exe -m ruff check . --no-cache
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m bandit -r ha_windows_bridge custom_components -ll -ii
.venv\Scripts\python.exe -m pip_audit --local --progress-spinner off --cache-dir .pip-audit-cache
.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm HAWindowsBridge.spec
$executable = Resolve-Path '.\dist\HA Windows Bridge\HA Windows Bridge.exe'
$process = Start-Process -FilePath $executable -ArgumentList '--smoke-test' -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0) { throw "Smoke test failed: $($process.ExitCode)" }
git diff --check
```

Testy grupowe były wykonywane po kolejnych zmianach. Grupa HA/fixtures: 42 passed; końcowa grupa apply/lifecycle: 13 passed. Łącznie dodano 62 lokalne przypadki regresyjne. Nie wykonywano prawdziwego autostartu, shutdown/restart Windows, zmian głośności ani zapisu profilu użytkownika; skutki uboczne są kontrolowane w regresjach.

## Linux CI — pozostaje do uruchomienia po pushu

Rozszerzono istniejący workflow **[validate.yml](../../.github/workflows/validate.yml)**, bez nowego równoległego workflow. Zachowano hassfest, HACS, Windows quality/build/smoke/pip-audit. Do Windows quality dodano pip check, a Ruff obejmuje również nowe tests_ha i narzędzie baseline.

Nowy job `ha-runtime` działa na `ubuntu-latest`, Python 3.14, macierz HA **2026.9.0 / 2026.9.1**. Instaluje rzeczywisty pakiet Home Assistant oraz biblioteki testowe/importowanych komponentów. Nie stosuje AST ani atrap modułów Home Assistant. Podmieniona jest wyłącznie granica sieci MQTT — dostarczanie wiadomości, stan połączenia i rejestracja subskrypcji — aby nie wymagać brokera ani sekretów.

W pięciu przypadkach wykonuje: import wszystkich modułów integracji, prawdziwy bootstrap HA, discovery/config flow, rejestry i osiem platform encji, aktualizacje głośności/mute, setup aktywnego odtwarzacza, reload z zachowaniem ID, unload bez pozostawionych subskrypcji/runtime oraz częściową awarię subskrypcji obu odtwarzaczy. Osobno sprawdza Direct config flow/setup/unload bez MQTT.

Fixtures: `tests_ha/fixtures/announcement-v2.json` oraz `profile-settings-v2.json`. Drugi jest publiczną częścią rzeczywistego profilu v2, bez sekretów. Lokalny test potwierdza, że parser profilu i generator announcement odtwarzają dokładnie zapisany kontrakt (schema 3, **protocol 2**, tak jak przed Phase 0).

Po pushu workflow uruchamia się automatycznie. Ręczne wywołanie GitHub CLI:

```sh
gh workflow run validate.yml --ref NAZWA_GALEZI
gh run list --workflow validate.yml --branch NAZWA_GALEZI --limit 5
gh run watch RUN_ID --exit-status
```

Można też użyć GitHub → Actions → Validate Home Assistant integration → Run workflow. Nie potrzeba dodatkowych sekretów ani ręcznej konfiguracji środowiska.

Dokładny krok testowy Linux (dla każdej wersji macierzy):

```sh
python -m pytest tests_ha -o asyncio_mode=auto --timeout=120 --junitxml=ha-runtime.xml
python -m pip check
```

**Niewykonane lokalnie:** oba joby HA runtime, hassfest i HACS. Zmiany nie zostały wypchnięte na GitHub w tej pracy. Zielone testy lokalne i przejrzenie oficjalnych API nie zastępują wyniku Linux CI.

Źródła użyte do sprawdzenia granic API: [HA 2026.9.0 helpers.target](https://github.com/home-assistant/core/blob/2026.9.0/homeassistant/helpers/target.py), [wymagania HA 2026.9.1](https://github.com/home-assistant/core/blob/2026.9.1/pyproject.toml), [HA Entity lifecycle](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/helpers/entity.py), [HA EntityPlatform](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/helpers/entity_platform.py), [Microsoft COM](https://learn.microsoft.com/en-us/windows/win32/learnwin32/initializing-the-com-library).

## Baseline procesu

<!-- BASELINE_START -->
Pomiar zakończony: **1800 s po 30 s rozgrzewki**, 1801 próbek. Początek 2026-09-06 12:55:42 UTC; czas procesu z rozgrzewką i zamknięciem 1830.085 s. Dane: [BASELINE.json](BASELINE.json); surowe próbki lokalnie: `build/phase0-baseline.jsonl`.

Sprzęt: AMD Ryzen 5 5600, 6 rdzeni / 12 wątków, 31.91 GiB RAM, Windows 11 build 26200, Python 3.13.5. Brak baterii; plan „Wysoka wydajność”. CPU jest procentem **całej maszyny**, nie jednego rdzenia.

Profil: MQTT offline na zarezerwowanym porcie loopback, master audio i media, CPU/RAM, polling 0.5 s; bez aplikacji, GPU/WUA/PnP/dysków, Direct, capture i overlay. Pełny publiczny profil znajduje się w JSON. Pierwsza połowa ma ukryte okno, druga otwarte Qt offscreen. Narzędzie nie czyta profilu użytkownika, nie zapisuje ustawień/autostartu i nie steruje Windows/audio.

| Metryka | Ukryte okno, 900 próbek | Otwarte Qt offscreen, 901 próbek |
| --- | --- | --- |
| CPU median / p95 / max | 0 / 0.131 / 0.390% | 0 / 0.260 / 0.525% |
| Working set median / p95 | 133.70 / 134.84 MiB | 139.55 / 139.75 MiB |
| Private bytes median / p95 | 142.37 / 144.10 MiB | 147.31 / 147.42 MiB |
| Uchwyty min / median / max | 444 / 455 / 472 | 445 / 461 / 468 |
| Wątki min / median / max | 13 / 14 / 18 | 13 / 15 / 18 |

Provider p95: master audio 0.079 ms, system_metrics 5.831 ms, media 1.765 ms. Czasy providerów obejmują także rozgrzewkę. Brak opcjonalnego Libre/OpenHardwareMonitor dał jawnie 359 zdarzeń health error; CPU/RAM pozostały dostępne. Przyjętych publikacji: 0, zgodnie z profilem offline. `shutdown_completed=true`; `Application.shutdown()` trwał 0.002 s (wcześniejszy cleanup okna/overlay jest poza tym timerem).

Private bytes pierwsza→ostatnia próbka wzrosły o 3.09 MiB w części ukrytej i 3.36 MiB w części z oknem. Nie dowodzi to ani nie wyklucza wycieku: profiler przechowuje próbki/czasy, a pokazanie okna tworzy zasoby Qt. P95 CPU jest poniżej proponowanego 0.5%, ale pojedynczy max z oknem wyniósł 0.525%. Nie deklarujemy zaliczenia całego budżetu performance audytu.

Ograniczenia: pomiar po naprawach, bez liczbowego baseline procesu sprzed zmian; nie dowodzi przyspieszenia. W tym samym środowisku wykonywano kontrole jakości. Brak brokera online, aktywnego audio/overlay, wake-up, głębokości kolejek, natywnego input/DPI/DWM i opóźnień GUI. Qt offscreen zgłosił brak katalogu fontów PySide6; proces zakończył się poprawnie. Pełna macierz sekcji 13 i soak pozostają niewykonane. Poprzednią przerwaną sesję bez kompletnego wyniku odrzucono.

Powtórzenie lokalne:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.venv/Scripts/python.exe -X utf8 -u tools/phase0_baseline.py --seconds 1800 --warmup 30 --output build/phase0-baseline.json
```

<!-- BASELINE_END -->

## Świadomie pozostawione na późniejsze fazy

- H04: izolacja wolnych/zawieszonych providerów, cancellation/deadline, pełny kontrakt lifecycle — Phase 1/3.
- H06: capabilities niezależne od chwilowego health oraz usunięcie automatycznego kasowania encji z registry — Phase 2/6. Phase 0 nie rozwiązuje całego tego problemu.
- H07: osobne zgody na power actions, zmiana semantyki wymuszonego zamykania i lokalne anulowanie — późniejsza warstwa polityk/Windows; nie wykonywano tych akcji.
- H08: prawdziwe ACK silnika overlay, bounded inbox przed Qt, statusy accepted/displayed — Phase 2/4.
- M03: migracja procentów GPU fan do poprawnych jednostek i historii; zachowano istniejący test do świadomej migracji Phase 3.
- Pełny StateOutbox/ComputerState, generacje całej aplikacji, odporność transakcji na crash, PUBACK/SUBACK, Protocol v3, tożsamość sesji audio/media, adaptacyjny polling — Phase 1–3.
- Nowe GUI/overlay, DWM/capture i efekty, pełne ACL/URL policy, migration/Repairs/diagnostics, Python minimum/constraints poza dodaniem bezpośredniej zależności packaging — odpowiednie późniejsze fazy.
- Real broker/Direct fault matrix, 24–72 h soak, install/upgrade/uninstall, fizyczna macierz DPI/sleep/sterowników i budżety opóźnień GUI — dalsze bramki roadmapy, zwłaszcza Phase 7.

## Zmienione i nowe pliki

Poniższa lista obejmuje Phase 0; nie obejmuje istniejącego katalogu wcześniejszego audytu ani ignorowanych build/dist/venv.

<!-- FILES_START -->
- `.github/workflows/validate.yml`
- `HOME_ASSISTANT_INTEGRATION.md`
- `custom_components/ha_windows_bridge/__init__.py`
- `custom_components/ha_windows_bridge/announcement.py`
- `custom_components/ha_windows_bridge/binary_sensor.py`
- `custom_components/ha_windows_bridge/entity.py`
- `custom_components/ha_windows_bridge/media_player.py`
- `custom_components/ha_windows_bridge/sensor.py`
- `docs/phase0/BASELINE.json`
- `docs/phase0/VALIDATION.md`
- `ha_windows_bridge/application/application.py`
- `ha_windows_bridge/application/telemetry.py`
- `ha_windows_bridge/communication/gateway.py`
- `ha_windows_bridge/communication/publishing.py`
- `ha_windows_bridge/communication/state.py`
- `ha_windows_bridge/config.py`
- `ha_windows_bridge/core/configuration.py`
- `ha_windows_bridge/integration_protocol.py`
- `ha_windows_bridge/system_monitor.py`
- `ha_windows_bridge/ui_components.py`
- `ha_windows_bridge/updater.py`
- `ha_windows_bridge/windows/com.py`
- `hacs.json`
- `pyproject.toml`
- `tests/test_phase0_apply.py`
- `tests/test_phase0_ha_entities.py`
- `tests/test_phase0_providers.py`
- `tests/test_phase0_publishing.py`
- `tests/test_phase0_regressions.py`
- `tests/test_v2_application.py`
- `tests_ha/conftest.py`
- `tests_ha/fixtures/announcement-v2.json`
- `tests_ha/fixtures/profile-settings-v2.json`
- `tests_ha/test_runtime.py`
- `tools/phase0_baseline.py`
<!-- FILES_END -->

## git diff --stat

Statystyka śledzonych plików z `git diff --stat`; nowe pliki są osobno wymienione wyżej, ponieważ nie wykonywano git add/commit.

<!-- STAT_START -->
```text
 .github/workflows/validate.yml                     |  31 ++++-
 HOME_ASSISTANT_INTEGRATION.md                      |   6 +
 custom_components/ha_windows_bridge/__init__.py    |  16 +--
 .../ha_windows_bridge/announcement.py              |   2 +-
 .../ha_windows_bridge/binary_sensor.py             |   7 +-
 custom_components/ha_windows_bridge/entity.py      |   3 +-
 .../ha_windows_bridge/media_player.py              |  70 ++++------
 custom_components/ha_windows_bridge/sensor.py      |   7 +-
 ha_windows_bridge/application/application.py       |  37 ++++--
 ha_windows_bridge/application/telemetry.py         |  62 +++++----
 ha_windows_bridge/communication/gateway.py         |   2 +-
 ha_windows_bridge/communication/publishing.py      |  82 ++++++++++--
 ha_windows_bridge/communication/state.py           |  29 ++--
 ha_windows_bridge/config.py                        |   3 +
 ha_windows_bridge/core/configuration.py            |   4 +
 ha_windows_bridge/integration_protocol.py          |  27 ++++
 ha_windows_bridge/system_monitor.py                | 146 ++++++++++++---------
 ha_windows_bridge/ui_components.py                 |   4 +
 ha_windows_bridge/updater.py                       |  15 ++-
 hacs.json                                          |   2 +-
 pyproject.toml                                     |   1 +
 tests/test_v2_application.py                       |   4 +-
 22 files changed, 368 insertions(+), 192 deletions(-)
```

Dodatkowo 13 nowych plików Phase 0 (łącznie 35 zmienionych/nowych plików), bez katalogu wcześniejszego audytu.
<!-- STAT_END -->
