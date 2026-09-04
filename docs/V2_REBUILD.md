# HA Windows Bridge 2.0 — przebudowa

Status: **2.0.0-alpha.1**, lokalna gałąź `codex/bridge-2.0`. To uruchamialna nowa architektura, nie certyfikowane wydanie produkcyjne. Walidacja rzeczywistego HA, DWM oraz wielogodzinne pomiary sprzętowe są oddzielnymi bramkami wydania.

Punkt odniesienia: commit `31054e5` (prototyp 0.10.0-beta.5 wraz z wcześniejszą modernizacją). Usunięte implementacje i ich testy można odtworzyć z tego commita; nie są pakowane do nowej aplikacji.

## 1. Inventory produktu, nie starej implementacji

| Funkcja produktu | Implementacja 2.0 / zakres |
| --- | --- |
| MQTT: discovery, retained state, LWT, reconnect | Osobny transport, protokół, cache publikacji i gateway. Ogłoszenia schema 3; polecenia v2 z ACK. |
| Bezpośrednie HA WebSocket | Własne API integracji, uprawnienia do konkretnej encji popupu, heartbeat, jedna aktywna sesja na komputer. Tylko nakładki; sensory i audio nadal przez MQTT. |
| Głośność Windows, aplikacji, aktywnego programu, mikrofon, mute, wyjście i balans | Zachowane adaptery Windows Audio; jawne komendy w application, platformy HA. |
| Każda wybrana aplikacja jako media_player | Zachowany model encji HA; nie udajemy, że regulacja głośności aplikacji udostępnia metadane utworu. |
| Bieżąca sesja multimedialna Windows | WinRT, stan, okładka, czas, play/pause/next/previous/seek. Przyciski na nakładce nie sterują przypadkowym lokalnym playerem dla źródła z HA. |
| Sterowanie programami | Start/close tylko dla skonfigurowanego programu i osobno włączonych uprawnień. Chronione procesy nadal odrzucane. |
| Sensory CPU/RAM/GPU, aktywne okno, bezczynność, blokada | Wspólny scheduler; cache, izolacja awarii źródeł, brak odpytywania przy rozłączonym MQTT. |
| Windows Update, restart, uptime, bateria, plan zasilania | Zachowane adaptery, osobne częstotliwości odczytu. Dostępność metryk zależy od sprzętu. |
| Dyski oraz PnP | Jawny wybór w nowym UI; enumeracja w tle na żądanie. |
| Powiadomienia Windows | Prezentacja w zasobniku na żądanie Application; GUI nie wykonuje zdalnych komend systemowych. |
| Nakładki | Niezależny model i engine: kolejka, parallel, priority, ID update/replace/remove/clear, pinned, hover, progress, lifetime, MDI, obrazy, QR. |
| Kamery i źródła HA | Integracja rozwiązuje encje z kontrolą uprawnień, pobiera ograniczony obraz i wysyła go do PC. To klatka obrazu, nie transmisja wideo. |
| DPI/monitory/obszar roboczy | Czysty PlacementEngine w pikselach logicznych; Qt per-monitor scaling; nasłuchiwanie zmian ekranów i obszaru roboczego. |
| Acrylic / glass | Native Acrylic i przezroczysta powierzchnia jako fallback. Liquid używa obecnie Acrylic; desktop capture nie jest uruchamiany. |
| Tray i autostart | Stan transportów, liczba sensorów, reconnect, pause, przykład, ustawienia, exit; autostart wskazuje nowe wejście. |
| Ustawienia i bezpieczeństwo | Izolowany profile-v2.json; atomowa transakcja publicznych ustawień i DPAPI credentials; import/export bez sekretów, reset. |
| Aktualizacje | Opcjonalny odczyt stabilnych wydań GitHub w tle. Brak automatycznego instalowania. |
| Diagnostyka | Ograniczony ring buffer, redakcja sekretów, eksport wersji Python/Qt/Windows, usług i połączeń. |

## 2. Stara i nowa architektura

Stara:

```text
app -> GUI MainWindow
          +-- tworzy i zatrzymuje MqttBridge (sieć + komendy + sensory)
          +-- tworzy i zatrzymuje DirectHaBridge
          +-- OverlayManager -> duża OverlayCard + przechwytywanie pulpitu
          +-- ustawienia, zasobnik, logi, urządzenia i akcje Windows
```

Nowa:

```text
desktop (composition root)
  +-- Application -> ServiceSupervisor -> transporty + TelemetryService
  |      +-- CommandRouter -> jawny allowlist -> adaptery Windows
  |      +-- ConfigurationStore -> SecretStore -> DPAPI
  |      +-- EventBus / StateStore / DiagnosticBuffer
  +-- DesktopWindow -> formularze i zamiary użytkownika, bez lifecycle backendu
  +-- OverlayService -> NotificationEngine -> PlacementEngine -> NotificationWindow
  +-- WindowsEventBridge -> sleep/resume, session, display, theme, Explorer

MQTT -> MqttTransport -> TopicProtocol -> CommandRouter -> WindowsCommands
HA WS -> HomeAssistantTransport -> Gateway -> ten sam CommandRouter
HA integration -> ConfigEntry.runtime_data -> ACK / timeout / availability
```

## 3. Decyzje dotyczące subsystemów

| Subsystem prototypu | Decyzja | Wynik |
| --- | --- | --- |
| gui.py / ui/main_window.py / stare pages | REWRITE | Usunięte. Nowy shell, 7 stron, osobny Application. |
| app.py | REWRITE | Usunięty. desktop.py składa zależności; main.py, moduł i console entry używają 2.0. |
| overlay.py / manager / card / queue | REWRITE | Usunięte. Czysty engine i placement; prezentacja bez starego managera. |
| mqtt_bridge.py | REWRITE | Usunięty. Transport nie enumeruje urządzeń ani nie wywołuje GUI. |
| direct_bridge.py | REWRITE | Usunięty. Nowa maszyna stanów, scoped API, heartbeat i ACK. |
| config.py | REPLACE + KEEP | Nowy trwały format i SecretStore. Dataclasses i walidatory pozostają wartościowym modelem; czytniki prototypu nie są używane do startu 2.0. |
| audio.py / media.py / system_monitor.py / system_actions.py | KEEP + REFACTOR ownership | Sprawdzone granice Windows API zachowane; uruchamianie i komendy kontroluje nowy rdzeń. |
| windows_effects.py | KEEP, ograniczony zakres | Adapter NativeBackdrop używany. Capture nie jest aktywowany w 2.0. |
| custom_components/ha_windows_bridge | REFACTOR + REWRITE runtime | runtime_data, sesje WebSocket z kontrolą encji, ACK, timeout, unload. Zachowane modele encji i rozwiązywanie źródeł HA. |
| ui_components / design tokens / motion | KEEP + REFACTOR | Kontrolki i wspólna polityka ruchu, bez własnej ramki tytułowej. |

## 4. Istotne decyzje i granice

- Native QMainWindow zachowuje systemową ramkę, resize, caption i menu Windows. Nie implementujemy własnych przycisków udających natywne Snap Layouts.
- Usługi zatrzymują się w odwrotnej kolejności zależności. Nieudane zatrzymanie blokuje nowy start, zamiast pozostawiać dwie instancje backendu.
- Komendy mają ID, TTL, kontrolę rozmiaru i jawne uprawnienia. Cache deduplikacji nie wyrzuca świeżych poleceń tylko po to, aby zrobić miejsce; przy przeciążeniu zwraca błąd.
- ACK akcji Windows oznacza wynik adaptera. Dla nakładek wynik `queued_for_presentation` oznacza przekazanie do prezentacji, nie dowód, że użytkownik zobaczył kartę.
- Zdalne źródło `media_player_entity` jest prezentacją danych HA; nie uruchamia kontrolek sterujących niezwiązanym playerem Windows.
- Operacji Windows już wykonywanej przez API nie zabijamy przemocą po timeout. Wynik może zawierać `may_have_completed`; połączenie nie obiecuje rollbacku.
- Nowy Direct kanał nie używa administratorowego `fire_event`/dowolnego `subscribe_events`. Autoryzacja sprawdzana przy connect, heartbeat i ACK; obca sesja nie może potwierdzić cudzej komendy.
- Import nie przenosi sekretów. Przy zmianie adresu serwera nie podstawia starego tokenu/hasła pod nowy serwer.
- Domyślny profil 2.0 nie uruchamia automatycznie sieci ani autostartu. Stary profil nie jest automatycznie nadpisywany.

## 5. Breaking changes

1. Direct HA wymaga integracji 2.0. Stary tunel zdarzeń został usunięty.
2. Nowy profil `profile-v2.json`, nie `config.json`; brak automatycznego importu starych sekretów. Ustaw połączenie ponownie.
3. Protokół komend v2: `version/id/kind/target/arguments/issued_at/ttl_ms`, wynik na `.../v2/result`; HA ogłasza schema 3.
4. Stare Python API GUI/MqttBridge/DirectHaBridge/OverlayManager usunięte. Nie ma warstwy zgodności dla wewnętrznych importów.
5. Nieprawidłowa głośność poza zakresem jest odrzucana, nie przycinana po cichu.
6. Liquid Glass obecnie używa natywnego fallbacku; stare kosztowne przechwytywanie tła nie jest częścią nowego renderowania.
7. Nowe UI jest obecnie polskie. Pełne EN, zaawansowany edytor źródeł i podgląd live wszystkich metryk nie są deklarowane jako gotowe.

## 6. Drzewo odpowiedzialności

```text
ha_windows_bridge/
  desktop.py
  application/{application,lifecycle,commands,windows_commands,telemetry}.py
  core/{commands,configuration,secrets,events,state,observability}.py
  communication/{mqtt,home_assistant,gateway,protocol,publishing,state}.py
  windows/{credentials,native,capture}.py (capture: eksperyment, poza pakietem alpha)
  overlays/{engine,models,positioning,presentation,service,constants}.py
  ui/{shell,navigation,inputs,control_style,theme,motion}.py
  runtime/{polling,worker}.py
  audio.py, media.py, system_monitor.py, system_actions.py, startup.py
custom_components/ha_windows_bridge/
  runtime.py, websocket.py, config_flow.py, diagnostics.py
  entity.py, media_player.py, notify.py, sensor.py, ...
```

## 7. Referencje i licencje

Przegląd wszystkich sześciu repozytoriów i przypięte rewizje znajdują się również w `MODERNIZATION_AUDIT.md`. Nie włączono obcego kodu ani nowej biblioteki UI.

- [Home Assistant Core](https://github.com/home-assistant/core): runtime_data, callback ownership, autoryzacja i wsparcie encji; Apache-2.0.
- [Deskmate](https://github.com/JakubWawrzola/deskmate): produkt desktopowy i rozdzielenie powierzchni użytkownika; MIT.
- [WinUI Gallery](https://github.com/microsoft/WinUI-Gallery): nawigacja, spokojne powierzchnie, hierarchia tekstu; MIT.
- [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets): referencja zachowania kontrolek; GPL-3.0, kod niekopiowany.
- [CustomWindow](https://github.com/re7gog/CustomWindow): konsekwencje własnej ramki; wybrano natywną ramkę, repo jest archiwalne; MIT.
- [pyqttoast](https://github.com/niklashenning/pyqttoast): kolejka/placement/presentation jako odrębne odpowiedzialności; MIT.
- [Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/): checklist, nie deklaracja oficjalnego poziomu jakości.
- [HA WebSocket commands](https://github.com/home-assistant/core/blob/dev/homeassistant/components/websocket_api/commands.py): weryfikacja administratorowych ograniczeń standardowego kanału zdarzeń.
- [Native Snap Layouts](https://learn.microsoft.com/en-us/windows/apps/desktop/modernize/ui/apply-snap-layout-menu): powód zachowania ramki systemowej.

## 8. Pozostałe bramki wydania

- Test na rzeczywistym Home Assistant: nowe API WebSocket, wszystkie platformy MQTT, restart HA, uprawnienia użytkownika bez administratora, unload/reload integracji.
- Test DWM/Acrylic na Windows 10/11: Snap, HDR, RDP, mieszane DPI, zmiana monitora, taskbar, suspend/resume i restart Explorer.
- Wielogodzinny pomiar idle CPU/RAM i testy utraty sieci; nie zastępują ich krótkie testy automatyczne.
- Pełna lokalizacja nowego shell oraz dodatkowe akcje kart. Przyciski mediów lokalnych są obsługiwane; dowolne zdalne akcje przycisków nie są jeszcze publicznym API.
- Liquid/GPU dopiero po pomiarach i osobnym progu wydajności. Fallback jest celowy.
- Potwierdzenie widoczności ikon w realnym HACS po publikacji; lokalna obecność plików brand nie dowodzi odświeżenia katalogu HACS.
- Brak podpisu Authenticode i brak publikacji tej gałęzi w GitHub Releases.

Wyniki bieżących testów, build i diff są dopisywane w `V2_VALIDATION.md`.
