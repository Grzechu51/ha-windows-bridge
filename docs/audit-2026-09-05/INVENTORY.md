# HA Windows Bridge — inwentarz audytu

Stan: 5 września 2026, commit 0df284b423ecf7c3e78563028fdab9e65d0c4270. Załącznik do [raportu](<F:/Codex/HA MQTT PC/docs/audit-2026-09-05/REPORT.md>).

Inwentarz jest indeksem pokrycia przeglądu, nie oceną każdego wiersza ani zapewnieniem braku błędów. Decyzje dotyczą bieżącej roli modułu. Funkcje produktu i macierz głównych subsystemów są w sekcji 4 raportu. Liczby linii obejmują komentarze i puste wiersze. Symbole i importy odczytano przez AST; dynamiczne wywołania, lambdy i eksporty biblioteczne nie tworzą tu osobnych funkcji.

Zakres bazowy: **177 plików Git, 85 modułów produkcyjnych, 34 pliki testów**. Poniżej także entrypointy, narzędzia i każdy pozostały śledzony plik. .venv/build/dist i zewnętrzne narzędzia nie są autorskim kodem objętym liczbą modułów.

## Moduły produkcyjne

| Moduł | Linie | Decyzja | Rola i ocena |
| --- | --- | --- | --- |
| [custom_components/ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py>) | 550 | REWRITE podział | Setup/unload, registry, actions, source ACL i HTTP image; wydzielić services/images/runtime. |
| [custom_components/ha_windows_bridge/announcement.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py>) | 264 | REFACTOR | Walidator discovery/schema/platform/topic; naprawić typy, tożsamość i limity. |
| [custom_components/ha_windows_bridge/binary_sensor.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/binary_sensor.py>) | 48 | KEEP/REFACTOR | Cienka platforma binarna; health i typed runtime. |
| [custom_components/ha_windows_bridge/button.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/button.py>) | 30 | KEEP/REFACTOR | Encje akcji komputera/aplikacji; polityka wyniku i tłumaczone błędy. |
| [custom_components/ha_windows_bridge/config_flow.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/config_flow.py>) | 129 | REFACTOR | MQTT discovery i Direct, unique IDs/reconfigure; jeden wpis i real HA tests. |
| [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>) | 22 | KEEP/REFACTOR | Domena, platformy, wersje i limity; jeden jawny kontrakt. |
| [custom_components/ha_windows_bridge/diagnostics.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/diagnostics.py>) | 32 | KEEP/EXTEND | Dobra allowlista diagnostyki; dodać health/kompatybilność bez danych prywatnych. |
| [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>) | 118 | REFACTOR | Wspólna baza MQTT, komendy i availability; freshness i async_on_remove. |
| [custom_components/ha_windows_bridge/media_payload.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py>) | 133 | KEEP/REFACTOR | Walidacja stanu i artwork media; wspólne fixtures z encoderem. |
| [custom_components/ha_windows_bridge/media_player.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py>) | 294 | REWRITE lifecycle/projection | Per-app i active media player; brak _unsubscribers i częściowy setup wymagają poprawy. |
| [custom_components/ha_windows_bridge/notify.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py>) | 101 | REFACTOR | MQTT/Direct popup i Windows balloon; availability per transport/capability. |
| [custom_components/ha_windows_bridge/number.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/number.py>) | 53 | KEEP/REFACTOR | Głośność/balance; opcjonalne duplikaty media_player, nowy target/result. |
| [custom_components/ha_windows_bridge/runtime.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py>) | 196 | REFACTOR | Pending futures, Direct lease, routing i command IDs; dobry owner, dodać wspólny stan. |
| [custom_components/ha_windows_bridge/select.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/select.py>) | 47 | KEEP/REFACTOR | Audio/monitor select; stable IDs i aktualizacja capabilities. |
| [custom_components/ha_windows_bridge/sensor.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/sensor.py>) | 54 | REFACTOR | Wartości, units i state_class; limit 255, quality i poprawne GPU/disk semantics. |
| [custom_components/ha_windows_bridge/switch.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/switch.py>) | 49 | KEEP/REFACTOR | Mute i inne przełączniki; nowy runtime/result, dostępność. |
| [custom_components/ha_windows_bridge/websocket.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py>) | 101 | KEEP/REFACTOR | Autoryzacja, socket ownership, heartbeat/results; zachować ACL i limit sesji. |
| [ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__init__.py>) | 3 | KEEP | Wersja pakietu i metadane. |
| [ha_windows_bridge/__main__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__main__.py>) | 4 | KEEP | Entrypoint python -m; przekazuje sterowanie do desktop. |
| [ha_windows_bridge/application/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/__init__.py>) | 1 | KEEP | Znacznik pakietu / eksporty; bez własnej logiki usług. |
| [ha_windows_bridge/application/application.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py>) | 313 | REFACTOR | Właściciel konfiguracji, usług, kolejek lifecycle/query i komend; oddzielić I/O oraz transakcję apply. |
| [ha_windows_bridge/application/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py>) | 125 | KEEP/REFACTOR | Router, kolejka wykonania, dedup i wynik; zachować ograniczenia, domknąć lifecycle/ACK. |
| [ha_windows_bridge/application/lifecycle.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py>) | 112 | KEEP/REFACTOR | Topologiczny nadzorca usług; dobry cleanup zależności, rozszerzyć kontrakt stop na wszystkich właścicieli. |
| [ha_windows_bridge/application/telemetry.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py>) | 605 | REPLACE | Scheduler, odczyty, cache, discovery i publikacja; rozdzielić stan, capabilities, źródła i projekcję. |
| [ha_windows_bridge/application/windows_commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py>) | 141 | REFACTOR | Allowlista efektów Windows i notifications; osobna policy, stabilny target, wynik silnika overlay. |
| [ha_windows_bridge/audio.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py>) | 408 | REFACTOR | Core Audio, mikrofon, endpointy i sesje; jeden COM owner, callbacki, wspólny snapshot. |
| [ha_windows_bridge/communication/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/__init__.py>) | 1 | KEEP | Znacznik pakietu / eksporty; bez własnej logiki usług. |
| [ha_windows_bridge/communication/gateway.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py>) | 52 | REFACTOR | Łączenie transportu, routera i replay; usunąć synchroniczny replay pod lockiem. |
| [ha_windows_bridge/communication/home_assistant.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py>) | 234 | REFACTOR | Direct WebSocket auth/reconnect/heartbeat; zachować wąski adapter i kontrolę epoki. |
| [ha_windows_bridge/communication/mqtt.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py>) | 122 | REFACTOR | Paho lifecycle, subskrypcje/publish/LWT; jawne ACK i limity. |
| [ha_windows_bridge/communication/protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py>) | 119 | REFACTOR/REPLACE legacy | Mapowanie topiców i parsowanie starych formatów; walidacja domenowa niżej, compatibility na brzegu. |
| [ha_windows_bridge/communication/publishing.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/publishing.py>) | 33 | REPLACE | Cache publikacji i replay; lock inversion i utrata aktualnej obserwacji. |
| [ha_windows_bridge/communication/state.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py>) | 89 | REFACTOR | ConnectionMachine, epoka i backoff; eventy poza lockiem. |
| [ha_windows_bridge/communication/status.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/status.py>) | 29 | KEEP | Mały model statusu połączenia; rozszerzyć health bez zależności Qt. |
| [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>) | 537 | REFACTOR | Wspólny model ustawień, defaults i legacy SettingsStore; oddzielić model od starego persistence. |
| [ha_windows_bridge/core/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/__init__.py>) | 1 | KEEP | Znacznik pakietu / eksporty; bez własnej logiki usług. |
| [ha_windows_bridge/core/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py>) | 88 | KEEP/REFACTOR | Envelope, walidacja, błędy i dedup; zachować limity, rozwinąć session/results. |
| [ha_windows_bridge/core/configuration.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py>) | 136 | REFACTOR | Profil format2, ścisłe typy i atomowy zapis; wspólny budżet capabilities i recovery/migracja. |
| [ha_windows_bridge/core/events.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py>) | 49 | KEEP/REFACTOR | Mały synchroniczny EventBus; jawne tematy, immutable payload i unikanie callout pod cudzym lockiem. |
| [ha_windows_bridge/core/observability.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/observability.py>) | 35 | REFACTOR | Bufor logów i redakcja; rotowany ślad i jawny schema eksportu. |
| [ha_windows_bridge/core/secrets.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py>) | 40 | KEEP | Platformowo niezależny kontrakt szyfrowania i ograniczony rekord sekretów. |
| [ha_windows_bridge/core/state.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py>) | 47 | KEEP/EXTEND | Immutable statusy usług; nie jest jeszcze store próbek Windows. |
| [ha_windows_bridge/data_exchange.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/data_exchange.py>) | 125 | REPLACE legacy | Stary import/export diagnostyki i ustawień; wycofać po migracji do jednego profilu. |
| [ha_windows_bridge/desktop.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/desktop.py>) | 108 | REFACTOR | Composition root Qt/Windows, profil, mutex, uruchomienie i cleanup; wymagany finally częściowego startu. |
| [ha_windows_bridge/discovery.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py>) | 1097 | REPLACE projection | Tematy i opisy licznych encji; zachować semantykę funkcji, przenieść mapping do HA. |
| [ha_windows_bridge/i18n.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py>) | 461 | REFACTOR | Globalny język i stary słownik PL/EN; ujednolicić z obecnym shell. |
| [ha_windows_bridge/integration_protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/integration_protocol.py>) | 60 | REPLACE | Announcement i definicje encji; semantyczne capabilities, wersja i wspólne fixtures. |
| [ha_windows_bridge/media.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py>) | 369 | REFACTOR | WinRT runner, GSMTC snapshot, artwork i komendy; jeden owner, session identity i eventy. |
| [ha_windows_bridge/media_protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py>) | 52 | REFACTOR | Serializacja media i artwork po stronie Windows; jeden kontrakt obu końców. |
| [ha_windows_bridge/mqtt_cleanup.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/mqtt_cleanup.py>) | 134 | KEEP/REFACTOR | Usuwanie własnych starych retained topics; ograniczać do znanego inventory/prefixu. |
| [ha_windows_bridge/overlays/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/__init__.py>) | 1 | KEEP | Znacznik pakietu / eksporty; bez własnej logiki usług. |
| [ha_windows_bridge/overlays/constants.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/constants.py>) | 16 | KEEP | Ograniczenia i dozwolone warianty; związać z publicznym schema. |
| [ha_windows_bridge/overlays/engine.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py>) | 169 | KEEP/REFACTOR | Czysta kolejka, visible/pending, timeout i media; doprecyzować PATCH/ack/lock policy. |
| [ha_windows_bridge/overlays/examples.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/examples.py>) | 43 | KEEP | Przykłady powiadomień; generować według wspólnego kontraktu. |
| [ha_windows_bridge/overlays/glass.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py>) | 152 | REPLACE backend | Timer, worker i obróbka tła; capture opcjonalny, pełny lifecycle i budżet energii. |
| [ha_windows_bridge/overlays/media_style.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py>) | 75 | KEEP/REFACTOR | Tokeny i styl karty media; scalić z design system. |
| [ha_windows_bridge/overlays/models.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/models.py>) | 146 | REFACTOR | Normalizacja notification i opcji; ścisłe typy, tri-state PATCH, bez rozproszonych defaults. |
| [ha_windows_bridge/overlays/positioning.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py>) | 93 | KEEP | Czysta geometria i stacking/work area; dodać stable monitor identity przy adapterze. |
| [ha_windows_bridge/overlays/presentation.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py>) | 573 | REWRITE warstwę | Widget, content, QR, layout, animation i efekt; wydzielić przygotowanie contentu i host. |
| [ha_windows_bridge/overlays/service.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py>) | 228 | REWRITE host | Qt ingress, timery, okna i engine; bounded inbox i rzeczywisty wynik przyjęcia. |
| [ha_windows_bridge/overlays/windows_media.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/windows_media.py>) | 23 | REFACTOR | Model danych/payload dla lokalnego media overlay; użyć wspólnego snapshotu. |
| [ha_windows_bridge/runtime/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/__init__.py>) | 1 | KEEP | Znacznik pakietu / eksporty; bez własnej logiki usług. |
| [ha_windows_bridge/runtime/polling.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/polling.py>) | 35 | KEEP/REFACTOR | Deadline per source, cache i izolacja wyjątków; dodać quality, nie udawać izolacji blokowania. |
| [ha_windows_bridge/runtime/worker.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py>) | 54 | KEEP/REFACTOR | Ograniczony SerialWorker i stop; jawny wynik końca oraz podział kolejek według ownership. |
| [ha_windows_bridge/security.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/security.py>) | 42 | KEEP/REFACTOR | Walidacja hostów/topiców/URL, ochrona/redakcja starszych ścieżek; zredukować duplikaty. |
| [ha_windows_bridge/single_instance.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/single_instance.py>) | 17 | REFACTOR | Named mutex w sesji użytkownika; pełne ctypes/error handling, opcjonalna aktywacja okna. |
| [ha_windows_bridge/startup.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/startup.py>) | 36 | KEEP/REFACTOR | HKCU Run i cytowanie komendy; wynik apply i cleanup uninstall. |
| [ha_windows_bridge/system_actions.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py>) | 98 | REFACTOR policy | Ograniczone akcje zasilania; rozdzielić forced shutdown i uprawnienia. |
| [ha_windows_bridge/system_monitor.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py>) | 970 | REWRITE orchestration | Kontekst, WMI/WUA, PnP, GPU, dyski, shell/process actions; niezależni providerzy i COM. |
| [ha_windows_bridge/theme.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/theme.py>) | 5 | REFACTOR | Starsze QSS/tokeny używane pośrednio; jeden zestaw źródeł stylu. |
| [ha_windows_bridge/ui/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/__init__.py>) | 1 | KEEP | Znacznik pakietu / eksporty; bez własnej logiki usług. |
| [ha_windows_bridge/ui/control_style.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/control_style.py>) | 47 | KEEP | ProxyStyle i natywne kontrolki; testować aktualną linię Qt. |
| [ha_windows_bridge/ui/inputs.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/inputs.py>) | 31 | KEEP/REFACTOR | Bezpieczne zachowanie wheel i kontrolek formularza; spójna klawiatura/focus. |
| [ha_windows_bridge/ui/motion.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py>) | 63 | REFACTOR | Motion tokens i Reduced Motion; jedyne źródło polityki dla całego UI/overlay. |
| [ha_windows_bridge/ui/navigation.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/navigation.py>) | 43 | KEEP/REFACTOR | Animowana nawigacja i strony; ujednolicić tokeny i obsługę focus. |
| [ha_windows_bridge/ui/shell.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py>) | 666 | REWRITE strony | IA, formularze, inventory, tray, config i eventy; view models nad wspólnym stanem. |
| [ha_windows_bridge/ui/theme.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py>) | 157 | REFACTOR | Bieżący motyw shell/light/dark/accent; scalić tokeny i sprawdzić kontrast. |
| [ha_windows_bridge/ui_components.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py>) | 1054 | REFACTOR/REMOVE dead | Używany AppCard i pozostałości dawnego UI; naprawić klawiaturę, usuwać tylko bez referencji. |
| [ha_windows_bridge/updater.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/updater.py>) | 71 | REFACTOR | GitHub latest i porównanie wersji; poprawna obsługa prerelease i kanałów. |
| [ha_windows_bridge/windows/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/__init__.py>) | 1 | KEEP | Znacznik pakietu / eksporty; bez własnej logiki usług. |
| [ha_windows_bridge/windows/capture.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py>) | 214 | REPLACE/OPTIONAL | DXGI/DXcam, mapowanie output i wykluczanie okien; ograniczyć prywatne API i cache topology. |
| [ha_windows_bridge/windows/credentials.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/credentials.py>) | 9 | KEEP | Mały adapter DPAPI bieżącego użytkownika. |
| [ha_windows_bridge/windows/native.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/native.py>) | 62 | REFACTOR | Power/WTS/display/theme/Explorer events; dodać brakujące źródła i cleanup. |
| [ha_windows_bridge/windows/resources.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/resources.py>) | 46 | KEEP/REFACTOR | Inwentarz zasobów Qt/Windows do diagnostyki; prywatność i bezpieczny odczyt. |
| [ha_windows_bridge/windows_effects.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py>) | 237 | KEEP/REFACTOR | Win32/DWM, DPI i preferencje animacji; używać feature gates, oddzielić martwe efekty. |

## Indeks klas, funkcji i zależności

Zależności obejmują także importy wykonywane wewnątrz funkcji. Lista zewnętrzna zawiera nazwy pakietów importowanych (również standardową bibliotekę), a nie listę instalowanych dystrybucji. Puste package markers nie wymagają osobnego managera.

### custom_components/ha_windows_bridge/__init__.py

Setup/unload, registry, actions, source ACL i HTTP image; wydzielić services/images/runtime.

Wewnętrzne importy: [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>), [custom_components/ha_windows_bridge/runtime.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py>), [custom_components/ha_windows_bridge/websocket.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `asyncio`, `base64`, `datetime`, `homeassistant`, `json`, `math`, `typing`, `urllib`, `voluptuous`.

| Symbol | Rodzaj |
| --- | --- |
| [_image_data_uri](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:151>) | def |
| [_text_attribute](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:164>) | def |
| [_number_attribute](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:171>) | def |
| [_live_media_position](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:179>) | def |
| [_async_media_image](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:198>) | async def |
| [_async_entity_image](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:224>) | async def |
| [async_setup](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:240>) | async def |
| [async_setup.publish_overlay](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:244>) | async def |
| [async_setup.publish_overlay.text_from_entity](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:334>) | async def |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:495>) | async def |
| [async_unload_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/__init__.py:545>) | async def |

### custom_components/ha_windows_bridge/announcement.py

Walidator discovery/schema/platform/topic; naprawić typy, tożsamość i limity.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `json`, `math`, `re`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [_text](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py:77>) | def |
| [_topic](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py:86>) | def |
| [_finite](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py:93>) | def |
| [_entity](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py:103>) | def |
| [parse_discovery_announcement](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py:161>) | def |
| [_protocol](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py:244>) | def |

### custom_components/ha_windows_bridge/binary_sensor.py

Cienka platforma binarna; health i typed runtime.

Wewnętrzne importy: [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `contextlib`, `homeassistant`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/binary_sensor.py:15>) | async def |
| [BridgeBinarySensor](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/binary_sensor.py:28>) | class |
| [BridgeBinarySensor.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/binary_sensor.py:29>) | def |
| [BridgeBinarySensor._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/binary_sensor.py:40>) | def |

### custom_components/ha_windows_bridge/button.py

Encje akcji komputera/aplikacji; polityka wyniku i tłumaczone błędy.

Wewnętrzne importy: [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/button.py:13>) | async def |
| [BridgeButton](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/button.py:23>) | class |
| [BridgeButton.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/button.py:24>) | def |
| [BridgeButton.async_press](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/button.py:29>) | async def |

### custom_components/ha_windows_bridge/config_flow.py

MQTT discovery i Direct, unique IDs/reconfigure; jeden wpis i real HA tests.

Wewnętrzne importy: [custom_components/ha_windows_bridge/announcement.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/announcement.py>), [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `typing`, `voluptuous`.

| Symbol | Rodzaj |
| --- | --- |
| [ConfigFlow](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/config_flow.py:22>) | class |
| [ConfigFlow.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/config_flow.py:27>) | def |
| [ConfigFlow.async_step_mqtt](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/config_flow.py:31>) | async def |
| [ConfigFlow.async_step_confirm](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/config_flow.py:60>) | async def |
| [ConfigFlow.async_step_reconfigure](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/config_flow.py:70>) | async def |
| [ConfigFlow.async_step_user](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/config_flow.py:90>) | async def |

### custom_components/ha_windows_bridge/const.py

Domena, platformy, wersje i limity; jeden jawny kontrakt.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`.

| Symbol | Rodzaj |
| --- | --- |
| [direct_overlay_event](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py:15>) | def |

### custom_components/ha_windows_bridge/diagnostics.py

Dobra allowlista diagnostyki; dodać health/kompatybilność bez danych prywatnych.

Wewnętrzne importy: [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `homeassistant`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_get_config_entry_diagnostics](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/diagnostics.py:14>) | async def |

### custom_components/ha_windows_bridge/entity.py

Wspólna baza MQTT, komendy i availability; freshness i async_on_remove.

Wewnętrzne importy: [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [entity_definitions](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:15>) | def |
| [bridge_device_info](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:23>) | def |
| [message_text](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:35>) | def |
| [BridgeMqttEntity](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:40>) | class |
| [BridgeMqttEntity.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:46>) | def |
| [BridgeMqttEntity.async_added_to_hass](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:64>) | async def |
| [BridgeMqttEntity._availability_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:95>) | def |
| [BridgeMqttEntity._mqtt_connection_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:104>) | def |
| [BridgeMqttEntity._update_availability](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:109>) | def |
| [BridgeMqttEntity._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:114>) | def |
| [BridgeMqttEntity._async_publish](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py:117>) | async def |

### custom_components/ha_windows_bridge/media_payload.py

Walidacja stanu i artwork media; wspólne fixtures z encoderem.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `base64`, `binascii`, `hashlib`, `json`, `math`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [_raw_size](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py:18>) | def |
| [_load_json_object](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py:22>) | def |
| [_text](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py:34>) | def |
| [_finite_number](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py:40>) | def |
| [parse_media_state](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py:52>) | def |
| [_detected_content_type](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py:97>) | def |
| [parse_media_artwork](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py:109>) | def |

### custom_components/ha_windows_bridge/media_player.py

Per-app i active media player; brak _unsubscribers i częściowy setup wymagają poprawy.

Wewnętrzne importy: [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>), [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>), [custom_components/ha_windows_bridge/media_payload.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_payload.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `json`, `math`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:42>) | async def |
| [HAWindowsAppVolumePlayer](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:57>) | class |
| [HAWindowsAppVolumePlayer.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:65>) | def |
| [HAWindowsAppVolumePlayer.async_added_to_hass](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:77>) | async def |
| [HAWindowsAppVolumePlayer._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:91>) | def |
| [HAWindowsAppVolumePlayer._volume_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:102>) | def |
| [HAWindowsAppVolumePlayer._mute_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:113>) | def |
| [HAWindowsAppVolumePlayer.async_set_volume_level](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:123>) | async def |
| [HAWindowsAppVolumePlayer.async_mute_volume](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:127>) | async def |
| [HAWindowsMediaPlayer](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:134>) | class |
| [HAWindowsMediaPlayer.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:143>) | def |
| [HAWindowsMediaPlayer.supported_features](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:165>) | def |
| [HAWindowsMediaPlayer.async_added_to_hass](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:171>) | async def |
| [HAWindowsMediaPlayer.async_will_remove_from_hass](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:198>) | async def |
| [HAWindowsMediaPlayer._availability_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:205>) | def |
| [HAWindowsMediaPlayer._mqtt_connection_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:210>) | def |
| [HAWindowsMediaPlayer._update_availability](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:215>) | def |
| [HAWindowsMediaPlayer._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:222>) | def |
| [HAWindowsMediaPlayer._thumbnail_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:243>) | def |
| [HAWindowsMediaPlayer._clear_artwork](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:257>) | def |
| [HAWindowsMediaPlayer.async_get_media_image](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:262>) | async def |
| [HAWindowsMediaPlayer._send_command](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:266>) | async def |
| [HAWindowsMediaPlayer.async_media_play](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:272>) | async def |
| [HAWindowsMediaPlayer.async_media_pause](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:275>) | async def |
| [HAWindowsMediaPlayer.async_media_stop](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:278>) | async def |
| [HAWindowsMediaPlayer.async_media_next_track](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:281>) | async def |
| [HAWindowsMediaPlayer.async_media_previous_track](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:284>) | async def |
| [HAWindowsMediaPlayer.async_media_seek](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:287>) | async def |
| [HAWindowsMediaPlayer.async_set_volume_level](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:290>) | async def |
| [HAWindowsMediaPlayer.async_mute_volume](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/media_player.py:293>) | async def |

### custom_components/ha_windows_bridge/notify.py

MQTT/Direct popup i Windows balloon; availability per transport/capability.

Wewnętrzne importy: [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>), [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `json`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:19>) | async def |
| [BridgeDirectNotify](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:28>) | class |
| [BridgeDirectNotify.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:34>) | def |
| [BridgeDirectNotify.async_added_to_hass](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:41>) | async def |
| [BridgeDirectNotify.available](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:48>) | def |
| [BridgeDirectNotify.async_send_message](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:51>) | async def |
| [BridgeWindowsNotify](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:63>) | class |
| [BridgeWindowsNotify.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:66>) | def |
| [BridgeWindowsNotify.async_added_to_hass](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:70>) | async def |
| [BridgeWindowsNotify._update_availability](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:77>) | def |
| [BridgeWindowsNotify.async_send_message](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/notify.py:81>) | async def |

### custom_components/ha_windows_bridge/number.py

Głośność/balance; opcjonalne duplikaty media_player, nowy target/result.

Wewnętrzne importy: [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `math`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/number.py:15>) | async def |
| [BridgeNumber](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/number.py:25>) | class |
| [BridgeNumber.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/number.py:26>) | def |
| [BridgeNumber._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/number.py:38>) | def |
| [BridgeNumber.async_set_native_value](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/number.py:51>) | async def |

### custom_components/ha_windows_bridge/runtime.py

Pending futures, Direct lease, routing i command IDs; dobry owner, dodać wspólny stan.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `asyncio`, `dataclasses`, `homeassistant`, `json`, `math`, `time`, `typing`, `uuid`.

| Symbol | Rodzaj |
| --- | --- |
| [command_arguments](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:18>) | def |
| [BridgeRuntime](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:49>) | class |
| [BridgeRuntime.start](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:67>) | async def |
| [BridgeRuntime.attach](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:72>) | def |
| [BridgeRuntime.detach](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:79>) | def |
| [BridgeRuntime.heartbeat](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:85>) | def |
| [BridgeRuntime._expired](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:93>) | def |
| [BridgeRuntime._notify](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:106>) | def |
| [BridgeRuntime._mqtt_result](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:111>) | def |
| [BridgeRuntime._result](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:121>) | def |
| [BridgeRuntime.send](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:129>) | async def |
| [BridgeRuntime.close](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/runtime.py:181>) | def |

### custom_components/ha_windows_bridge/select.py

Audio/monitor select; stable IDs i aktualizacja capabilities.

Wewnętrzne importy: [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/select.py:18>) | async def |
| [BridgeSelect](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/select.py:29>) | class |
| [BridgeSelect.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/select.py:30>) | def |
| [BridgeSelect._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/select.py:37>) | def |
| [BridgeSelect.async_select_option](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/select.py:44>) | async def |

### custom_components/ha_windows_bridge/sensor.py

Wartości, units i state_class; limit 255, quality i poprawne GPU/disk semantics.

Wewnętrzne importy: [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `contextlib`, `homeassistant`, `math`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/sensor.py:16>) | async def |
| [BridgeSensor](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/sensor.py:26>) | class |
| [BridgeSensor.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/sensor.py:27>) | def |
| [BridgeSensor._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/sensor.py:42>) | def |

### custom_components/ha_windows_bridge/switch.py

Mute i inne przełączniki; nowy runtime/result, dostępność.

Wewnętrzne importy: [custom_components/ha_windows_bridge/entity.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/entity.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [async_setup_entry](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/switch.py:14>) | async def |
| [BridgeSwitch](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/switch.py:24>) | class |
| [BridgeSwitch.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/switch.py:25>) | def |
| [BridgeSwitch._state_received](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/switch.py:35>) | def |
| [BridgeSwitch.async_turn_on](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/switch.py:45>) | async def |
| [BridgeSwitch.async_turn_off](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/switch.py:48>) | async def |

### custom_components/ha_windows_bridge/websocket.py

Autoryzacja, socket ownership, heartbeat/results; zachować ACL i limit sesji.

Wewnętrzne importy: [custom_components/ha_windows_bridge/const.py](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/const.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `homeassistant`, `voluptuous`.

| Symbol | Rodzaj |
| --- | --- |
| [BridgeConnectionError](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py:14>) | class |
| [BridgeConnectionError.__init__](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py:15>) | def |
| [authorized_runtime](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py:20>) | def |
| [connect](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py:54>) | def |
| [heartbeat](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py:71>) | def |
| [result](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py:89>) | def |
| [async_register_commands](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/websocket.py:99>) | def |

### ha_windows_bridge/__init__.py

Wersja pakietu i metadane.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/__main__.py

Entrypoint python -m; przekazuje sterowanie do desktop.

Wewnętrzne importy: [ha_windows_bridge/desktop.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/desktop.py>).
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/application/__init__.py

Znacznik pakietu / eksporty; bez własnej logiki usług.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/application/application.py

Właściciel konfiguracji, usług, kolejek lifecycle/query i komend; oddzielić I/O oraz transakcję apply.

Wewnętrzne importy: [ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__init__.py>), [ha_windows_bridge/application/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py>), [ha_windows_bridge/application/lifecycle.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py>), [ha_windows_bridge/application/telemetry.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py>), [ha_windows_bridge/application/windows_commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py>), [ha_windows_bridge/communication/gateway.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py>), [ha_windows_bridge/communication/home_assistant.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py>), [ha_windows_bridge/communication/status.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/status.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/core/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py>), [ha_windows_bridge/core/events.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py>), [ha_windows_bridge/core/observability.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/observability.py>), [ha_windows_bridge/core/state.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py>), [ha_windows_bridge/overlays/windows_media.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/windows_media.py>), [ha_windows_bridge/runtime/worker.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py>), [ha_windows_bridge/security.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/security.py>), [ha_windows_bridge/updater.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/updater.py>), [ha_windows_bridge/windows/resources.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/resources.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `copy`, `dataclasses`, `importlib`, `json`, `logging`, `platform`, `threading`, `time`, `uuid`.

| Symbol | Rodzaj |
| --- | --- |
| [Application](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:29>) | class |
| [Application.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:30>) | def |
| [Application._protect_secrets](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:61>) | def |
| [Application._connection_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:64>) | def |
| [Application.connection_snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:70>) | def |
| [Application.check_updates](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:74>) | def |
| [Application._build_services](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:80>) | def |
| [Application._schedule](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:104>) | def |
| [Application._run_operation](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:110>) | def |
| [Application.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:117>) | def |
| [Application._start](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:121>) | def |
| [Application.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:135>) | def |
| [Application._stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:139>) | def |
| [Application.reconnect](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:147>) | def |
| [Application.reconnect.reconnect](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:149>) | def |
| [Application.apply_configuration](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:155>) | def |
| [Application.apply_configuration.apply](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:165>) | def |
| [Application.pause_sensors](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:183>) | def |
| [Application.request_inventory](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:187>) | def |
| [Application.request_inventory.query](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:190>) | def |
| [Application._query_once](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:202>) | def |
| [Application._query_once.run](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:207>) | def |
| [Application.request_resources](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:219>) | def |
| [Application.request_media_example](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:222>) | def |
| [Application.request_media_example.query](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:223>) | def |
| [Application.request_media_refresh](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:246>) | def |
| [Application.request_media_refresh.query](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:247>) | def |
| [Application.suspend](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:260>) | def |
| [Application.resume](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:264>) | def |
| [Application.resume.resume](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:269>) | def |
| [Application.command](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:275>) | def |
| [Application.diagnostic_report](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:282>) | def |
| [Application.export_diagnostics](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:293>) | def |
| [Application.shutdown](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py:297>) | def |

### ha_windows_bridge/application/commands.py

Router, kolejka wykonania, dedup i wynik; zachować ograniczenia, domknąć lifecycle/ACK.

Wewnętrzne importy: [ha_windows_bridge/core/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py>), [ha_windows_bridge/runtime/worker.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `dataclasses`, `logging`, `threading`, `time`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [Execution](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:20>) | class |
| [CommandRouter](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:28>) | class |
| [CommandRouter.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:29>) | def |
| [CommandRouter.register](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:39>) | def |
| [CommandRouter.submit](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:45>) | def |
| [CommandRouter._execute](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:75>) | def |
| [CommandRouter._reply](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:100>) | def |
| [CommandRouter.closed](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:107>) | def |
| [CommandRouter.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/commands.py:111>) | def |

### ha_windows_bridge/application/lifecycle.py

Topologiczny nadzorca usług; dobry cleanup zależności, rozszerzyć kontrakt stop na wszystkich właścicieli.

Wewnętrzne importy: [ha_windows_bridge/core/state.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `logging`, `threading`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [Service](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:12>) | class |
| [Service.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:13>) | def |
| [Service.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:14>) | def |
| [Registration](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:18>) | class |
| [ServiceSupervisor](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:23>) | class |
| [ServiceSupervisor.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:24>) | def |
| [ServiceSupervisor.register](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:32>) | def |
| [ServiceSupervisor._order](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:41>) | def |
| [ServiceSupervisor._order.visit](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:44>) | def |
| [ServiceSupervisor.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:60>) | def |
| [ServiceSupervisor.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:88>) | def |
| [ServiceSupervisor.active](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/lifecycle.py:110>) | def |

### ha_windows_bridge/application/telemetry.py

Scheduler, odczyty, cache, discovery i publikacja; rozdzielić stan, capabilities, źródła i projekcję.

Wewnętrzne importy: [ha_windows_bridge/audio.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py>), [ha_windows_bridge/communication/protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/discovery.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py>), [ha_windows_bridge/integration_protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/integration_protocol.py>), [ha_windows_bridge/media_protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py>), [ha_windows_bridge/runtime/polling.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/polling.py>), [ha_windows_bridge/system_monitor.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `functools`, `json`, `logging`, `os`, `threading`, `time`.

| Symbol | Rodzaj |
| --- | --- |
| [TelemetryService](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:51>) | class |
| [TelemetryService.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:54>) | def |
| [TelemetryService.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:85>) | def |
| [TelemetryService.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:93>) | def |
| [TelemetryService.pause](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:102>) | def |
| [TelemetryService._connection_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:106>) | def |
| [TelemetryService._publish_number_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:112>) | def |
| [TelemetryService._publish_switch_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:116>) | def |
| [TelemetryService._publish_text_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:120>) | def |
| [TelemetryService._publish_volume_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:124>) | def |
| [TelemetryService._publish_master_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:131>) | def |
| [TelemetryService.publish_discovery](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:135>) | def |
| [TelemetryService._monitor_loop](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:232>) | def |
| [TelemetryService._monitor_master](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:268>) | def |
| [TelemetryService._monitor_apps](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:298>) | def |
| [TelemetryService._monitor_active](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:347>) | def |
| [TelemetryService._monitor_total_audio_sessions](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:370>) | def |
| [TelemetryService._monitor_microphone](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:380>) | def |
| [TelemetryService._monitor_context](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:409>) | def |
| [TelemetryService._monitor_system](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:440>) | def |
| [TelemetryService._monitor_windows_health](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:495>) | def |
| [TelemetryService._monitor_disks](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:520>) | def |
| [TelemetryService._monitor_devices](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:545>) | def |
| [TelemetryService._monitor_audio_output](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:557>) | def |
| [TelemetryService._monitor_media](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:570>) | def |
| [TelemetryService._publish_running](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:601>) | def |
| [TelemetryService._publish_active_app](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/telemetry.py:604>) | def |

### ha_windows_bridge/application/windows_commands.py

Allowlista efektów Windows i notifications; osobna policy, stabilny target, wynik silnika overlay.

Wewnętrzne importy: [ha_windows_bridge/communication/protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py>), [ha_windows_bridge/core/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `base64`.

| Symbol | Rodzaj |
| --- | --- |
| [WindowsCommands](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py:10>) | class |
| [WindowsCommands.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py:11>) | def |
| [WindowsCommands.install](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py:16>) | def |
| [WindowsCommands._bool](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py:42>) | def |
| [WindowsCommands._success](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py:48>) | def |
| [WindowsCommands.execute](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py:52>) | def |
| [WindowsCommands._notification](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/windows_commands.py:114>) | def |

### ha_windows_bridge/audio.py

Core Audio, mikrofon, endpointy i sesje; jeden COM owner, callbacki, wspólny snapshot.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `_ctypes`, `collections`, `comtypes`, `contextlib`, `dataclasses`, `pathlib`, `psutil`, `pycaw`, `time`, `win32gui`, `win32process`.

| Symbol | Rodzaj |
| --- | --- |
| [AudioApplication](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:23>) | class |
| [AudioSessionSnapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:32>) | class |
| [MicrophoneSnapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:39>) | class |
| [AudioOutputDevice](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:47>) | class |
| [com_scope](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:54>) | def |
| [WindowsAudioService](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:62>) | class |
| [WindowsAudioService.get_master_snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:63>) | def |
| [WindowsAudioService.get_master_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:74>) | def |
| [WindowsAudioService.set_master_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:78>) | def |
| [WindowsAudioService.get_master_mute](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:87>) | def |
| [WindowsAudioService.set_master_mute](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:91>) | def |
| [WindowsAudioService.get_master_balance](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:99>) | def |
| [WindowsAudioService.set_master_balance](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:115>) | def |
| [WindowsAudioService.get_microphone_snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:131>) | def |
| [WindowsAudioService._microphone_signal_active](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:158>) | def |
| [WindowsAudioService.set_microphone_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:161>) | def |
| [WindowsAudioService.set_microphone_mute](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:164>) | def |
| [WindowsAudioService._set_microphone_endpoint](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:168>) | def |
| [WindowsAudioService.list_output_devices](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:182>) | def |
| [WindowsAudioService.set_output_device](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:202>) | def |
| [WindowsAudioService.list_audio_applications](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:229>) | def |
| [WindowsAudioService.session_snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:270>) | def |
| [WindowsAudioService.count_audio_sessions](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:303>) | def |
| [WindowsAudioService.volume_snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:323>) | def |
| [WindowsAudioService.get_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:326>) | def |
| [WindowsAudioService.get_mute](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:329>) | def |
| [WindowsAudioService.set_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:333>) | def |
| [WindowsAudioService.set_mute](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:358>) | def |
| [WindowsAudioService.get_active_process_name](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:383>) | def |
| [WindowsAudioService._read_session_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py:394>) | def |

### ha_windows_bridge/communication/__init__.py

Znacznik pakietu / eksporty; bez własnej logiki usług.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/communication/gateway.py

Łączenie transportu, routera i replay; usunąć synchroniczny replay pod lockiem.

Wewnętrzne importy: [ha_windows_bridge/communication/mqtt.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py>), [ha_windows_bridge/communication/protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py>), [ha_windows_bridge/communication/publishing.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/publishing.py>), [ha_windows_bridge/core/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `logging`.

| Symbol | Rodzaj |
| --- | --- |
| [MqttGateway](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py:12>) | class |
| [MqttGateway.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py:13>) | def |
| [MqttGateway.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py:22>) | def |
| [MqttGateway.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py:26>) | def |
| [MqttGateway._connection_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py:32>) | def |
| [MqttGateway.receive](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py:36>) | def |
| [MqttGateway._reply](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/gateway.py:51>) | def |

### ha_windows_bridge/communication/home_assistant.py

Direct WebSocket auth/reconnect/heartbeat; zachować wąski adapter i kontrolę epoki.

Wewnętrzne importy: [ha_windows_bridge/communication/state.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py>), [ha_windows_bridge/core/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `contextlib`, `json`, `logging`, `ssl`, `threading`, `time`, `urllib`, `websocket`.

| Symbol | Rodzaj |
| --- | --- |
| [websocket_url](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:18>) | def |
| [HomeAssistantConnectionError](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:28>) | class |
| [HomeAssistantConnectionError.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:29>) | def |
| [response_error](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:36>) | def |
| [HomeAssistantTransport](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:58>) | class |
| [HomeAssistantTransport.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:59>) | def |
| [HomeAssistantTransport.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:71>) | def |
| [HomeAssistantTransport.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:79>) | def |
| [HomeAssistantTransport._close_socket](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:87>) | def |
| [HomeAssistantTransport._read](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:94>) | def |
| [HomeAssistantTransport._send](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:106>) | def |
| [HomeAssistantTransport._connect](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:116>) | def |
| [HomeAssistantTransport._run](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:150>) | def |
| [HomeAssistantTransport._read_events](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:173>) | def |
| [HomeAssistantTransport.acknowledge](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:203>) | def |
| [HomeAssistantGateway](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:213>) | class |
| [HomeAssistantGateway.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:214>) | def |
| [HomeAssistantGateway.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:218>) | def |
| [HomeAssistantGateway.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:221>) | def |
| [HomeAssistantGateway.receive](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/home_assistant.py:224>) | def |

### ha_windows_bridge/communication/mqtt.py

Paho lifecycle, subskrypcje/publish/LWT; jawne ACK i limity.

Wewnętrzne importy: [ha_windows_bridge/communication/state.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/core/events.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `contextlib`, `logging`, `paho`, `threading`.

| Symbol | Rodzaj |
| --- | --- |
| [MqttTransport](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:16>) | class |
| [MqttTransport.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:17>) | def |
| [MqttTransport.connected](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:42>) | def |
| [MqttTransport.start](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:45>) | def |
| [MqttTransport.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:53>) | def |
| [MqttTransport.publish](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:65>) | def |
| [MqttTransport._run](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:70>) | def |
| [MqttTransport._on_connect](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:95>) | def |
| [MqttTransport._on_disconnect](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:109>) | def |
| [MqttTransport._on_message](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/mqtt.py:113>) | def |

### ha_windows_bridge/communication/protocol.py

Mapowanie topiców i parsowanie starych formatów; walidacja domenowa niżej, compatibility na brzegu.

Wewnętrzne importy: [ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__init__.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/core/commands.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py>), [ha_windows_bridge/discovery.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py>), [ha_windows_bridge/media_protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `json`, `math`, `time`, `uuid`.

| Symbol | Rodzaj |
| --- | --- |
| [Route](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:17>) | class |
| [number](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:23>) | def |
| [legacy_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:35>) | def |
| [TopicProtocol](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:41>) | class |
| [TopicProtocol.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:42>) | def |
| [TopicProtocol.__init__.add](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:47>) | def |
| [TopicProtocol.subscriptions](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:83>) | def |
| [TopicProtocol.decode](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/protocol.py:86>) | def |

### ha_windows_bridge/communication/publishing.py

Cache publikacji i replay; lock inversion i utrata aktualnej obserwacji.

Wewnętrzne importy: [ha_windows_bridge/core/events.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `threading`.

| Symbol | Rodzaj |
| --- | --- |
| [StatePublisher](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/publishing.py:9>) | class |
| [StatePublisher.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/publishing.py:10>) | def |
| [StatePublisher.connected](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/publishing.py:16>) | def |
| [StatePublisher.publish](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/publishing.py:19>) | def |
| [StatePublisher.replay](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/publishing.py:30>) | def |

### ha_windows_bridge/communication/state.py

ConnectionMachine, epoka i backoff; eventy poza lockiem.

Wewnętrzne importy: [ha_windows_bridge/core/events.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `enum`, `random`, `threading`.

| Symbol | Rodzaj |
| --- | --- |
| [ConnectionState](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:12>) | class |
| [ConnectionStatus](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:23>) | class |
| [ConnectionMachine](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:30>) | class |
| [ConnectionMachine.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:31>) | def |
| [ConnectionMachine.status](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:38>) | def |
| [ConnectionMachine.begin](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:42>) | def |
| [ConnectionMachine.connected](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:48>) | def |
| [ConnectionMachine.failed](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:55>) | def |
| [ConnectionMachine.retry](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:64>) | def |
| [ConnectionMachine.stop](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:71>) | def |
| [ConnectionMachine._set](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:76>) | def |
| [Backoff](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:82>) | class |
| [Backoff.delay](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py:86>) | def |

### ha_windows_bridge/communication/status.py

Mały model statusu połączenia; rozszerzyć health bez zależności Qt.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

| Symbol | Rodzaj |
| --- | --- |
| [connection_text](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/status.py:25>) | def |

### ha_windows_bridge/config.py

Wspólny model ustawień, defaults i legacy SettingsStore; oddzielić model od starego persistence.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `base64`, `collections`, `dataclasses`, `json`, `math`, `os`, `pathlib`, `platform`, `re`, `typing`, `unicodedata`, `uuid`, `win32crypt`.

| Symbol | Rodzaj |
| --- | --- |
| [slugify](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:25>) | def |
| [default_device_id](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:33>) | def |
| [AudioAppConfig](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:40>) | class |
| [AudioAppConfig.__post_init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:49>) | def |
| [AudioAppConfig.from_dict](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:56>) | def |
| [TrackedDeviceConfig](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:69>) | class |
| [TrackedDeviceConfig.__post_init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:78>) | def |
| [TrackedDeviceConfig.from_dict](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:85>) | def |
| [MqttConfig](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:96>) | class |
| [MqttConfig.from_dict](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:107>) | def |
| [HomeAssistantConfig](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:120>) | class |
| [HomeAssistantConfig.from_dict](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:127>) | def |
| [default_apps](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:135>) | def |
| [_remove_unused_legacy_defaults](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:143>) | def |
| [AppConfig](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:159>) | class |
| [AppConfig.__post_init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:206>) | def |
| [AppConfig.from_dict](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:238>) | def |
| [AppConfig.to_dict](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:354>) | def |
| [AppConfig.validation_errors](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:360>) | def |
| [SecretBackend](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:411>) | class |
| [SecretBackend.load](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:412>) | def |
| [SecretBackend.save](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:414>) | def |
| [DpapiSecretBackend](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:417>) | class |
| [DpapiSecretBackend.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:420>) | def |
| [DpapiSecretBackend.load](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:423>) | def |
| [DpapiSecretBackend.save](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:437>) | def |
| [default_data_dir](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:455>) | def |
| [SettingsStore](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:460>) | class |
| [SettingsStore.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:461>) | def |
| [SettingsStore.load](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:475>) | def |
| [SettingsStore.save](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:490>) | def |
| [SettingsStore.load_mqtt_topic_history](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:504>) | def |
| [SettingsStore.remember_mqtt_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:521>) | def |
| [SettingsStore.clear_mqtt_topic_history](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py:536>) | def |

### ha_windows_bridge/core/__init__.py

Znacznik pakietu / eksporty; bez własnej logiki usług.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/core/commands.py

Envelope, walidacja, błędy i dedup; zachować limity, rozwinąć session/results.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `hashlib`, `json`, `math`, `re`, `time`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [reject_constant](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:17>) | def |
| [CommandError](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:21>) | class |
| [CommandError.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:22>) | def |
| [Command](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:28>) | class |
| [Command.parse](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:36>) | def |
| [Command.fingerprint](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:72>) | def |
| [CommandResult](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:80>) | class |
| [CommandResult.encode](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/commands.py:86>) | def |

### ha_windows_bridge/core/configuration.py

Profil format2, ścisłe typy i atomowy zapis; wspólny budżet capabilities i recovery/migracja.

Wewnętrzne importy: [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/core/secrets.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `json`, `math`, `pathlib`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [public_settings](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:24>) | def |
| [parse_settings](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:30>) | def |
| [ConfigurationStore](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:88>) | class |
| [ConfigurationStore.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:89>) | def |
| [ConfigurationStore.load](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:94>) | def |
| [ConfigurationStore.save](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:108>) | def |
| [ConfigurationStore.export](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:126>) | def |
| [ConfigurationStore.import_settings](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py:130>) | def |

### ha_windows_bridge/core/events.py

Mały synchroniczny EventBus; jawne tematy, immutable payload i unikanie callout pod cudzym lockiem.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `dataclasses`, `logging`, `threading`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [Event](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py:12>) | class |
| [EventBus](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py:17>) | class |
| [EventBus.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py:18>) | def |
| [EventBus.subscribe](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py:24>) | def |
| [EventBus.subscribe.unsubscribe](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py:30>) | def |
| [EventBus.emit](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py:35>) | def |
| [EventBus.clear](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py:47>) | def |

### ha_windows_bridge/core/observability.py

Bufor logów i redakcja; rotowany ślad i jawny schema eksportu.

Wewnętrzne importy: [ha_windows_bridge/core/events.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py>), [ha_windows_bridge/security.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/security.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `logging`, `threading`.

| Symbol | Rodzaj |
| --- | --- |
| [DiagnosticBuffer](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/observability.py:12>) | class |
| [DiagnosticBuffer.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/observability.py:13>) | def |
| [DiagnosticBuffer.protect](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/observability.py:21>) | def |
| [DiagnosticBuffer.emit](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/observability.py:25>) | def |
| [DiagnosticBuffer.snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/observability.py:33>) | def |

### ha_windows_bridge/core/secrets.py

Platformowo niezależny kontrakt szyfrowania i ograniczony rekord sekretów.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `base64`, `json`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [Cipher](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py:11>) | class |
| [Cipher.encrypt](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py:12>) | def |
| [Cipher.decrypt](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py:13>) | def |
| [SecretStore](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py:16>) | class |
| [SecretStore.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py:17>) | def |
| [SecretStore.seal](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py:20>) | def |
| [SecretStore.unseal](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py:28>) | def |

### ha_windows_bridge/core/state.py

Immutable statusy usług; nie jest jeszcze store próbek Windows.

Wewnętrzne importy: [ha_windows_bridge/core/events.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/events.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `enum`, `threading`, `time`.

| Symbol | Rodzaj |
| --- | --- |
| [ServiceState](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py:12>) | class |
| [ServiceStatus](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py:21>) | class |
| [StateStore](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py:28>) | class |
| [StateStore.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py:29>) | def |
| [StateStore.set](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py:34>) | def |
| [StateStore.snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py:41>) | def |
| [StateStore.clear](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/state.py:45>) | def |

### ha_windows_bridge/data_exchange.py

Stary import/export diagnostyki i ustawień; wycofać po migracji do jednego profilu.

Wewnętrzne importy: [ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__init__.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/security.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/security.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `datetime`, `json`, `pathlib`, `platform`, `sys`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [export_configuration](<F:/Codex/HA MQTT PC/ha_windows_bridge/data_exchange.py:18>) | def |
| [import_configuration](<F:/Codex/HA MQTT PC/ha_windows_bridge/data_exchange.py:29>) | def |
| [_redact](<F:/Codex/HA MQTT PC/ha_windows_bridge/data_exchange.py:50>) | def |
| [build_diagnostic_report](<F:/Codex/HA MQTT PC/ha_windows_bridge/data_exchange.py:64>) | def |
| [_redact_report](<F:/Codex/HA MQTT PC/ha_windows_bridge/data_exchange.py:116>) | def |
| [save_diagnostic_report](<F:/Codex/HA MQTT PC/ha_windows_bridge/data_exchange.py:124>) | def |

### ha_windows_bridge/desktop.py

Composition root Qt/Windows, profil, mutex, uruchomienie i cleanup; wymagany finally częściowego startu.

Wewnętrzne importy: [ha_windows_bridge/application/application.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/application/application.py>), [ha_windows_bridge/audio.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/core/configuration.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py>), [ha_windows_bridge/core/secrets.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/secrets.py>), [ha_windows_bridge/media.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py>), [ha_windows_bridge/overlays/service.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py>), [ha_windows_bridge/single_instance.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/single_instance.py>), [ha_windows_bridge/startup.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/startup.py>), [ha_windows_bridge/system_actions.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py>), [ha_windows_bridge/system_monitor.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py>), [ha_windows_bridge/ui/control_style.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/control_style.py>), [ha_windows_bridge/ui/shell.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py>), [ha_windows_bridge/ui/theme.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py>), [ha_windows_bridge/windows/credentials.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/credentials.py>), [ha_windows_bridge/windows/native.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/native.py>), [ha_windows_bridge/windows_effects.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py>).
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `argparse`, `logging`, `sys`.

| Symbol | Rodzaj |
| --- | --- |
| [main](<F:/Codex/HA MQTT PC/ha_windows_bridge/desktop.py:30>) | def |
| [main.apply_theme](<F:/Codex/HA MQTT PC/ha_windows_bridge/desktop.py:65>) | def |

### ha_windows_bridge/discovery.py

Tematy i opisy licznych encji; zachować semantykę funkcji, przenieść mapping do HA.

Wewnętrzne importy: [ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__init__.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/media_protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `copy`, `dataclasses`.

| Symbol | Rodzaj |
| --- | --- |
| [DiscoveryMessage](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:12>) | class |
| [status_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:17>) | def |
| [app_volume_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:21>) | def |
| [app_running_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:26>) | def |
| [app_mute_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:30>) | def |
| [app_start_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:35>) | def |
| [app_close_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:39>) | def |
| [active_volume_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:43>) | def |
| [master_volume_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:48>) | def |
| [master_mute_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:53>) | def |
| [microphone_volume_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:58>) | def |
| [microphone_mute_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:63>) | def |
| [microphone_active_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:68>) | def |
| [audio_output_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:72>) | def |
| [active_app_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:77>) | def |
| [active_window_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:81>) | def |
| [fullscreen_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:85>) | def |
| [idle_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:89>) | def |
| [pc_active_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:93>) | def |
| [session_locked_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:97>) | def |
| [system_metric_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:101>) | def |
| [disk_volume_metric](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:105>) | def |
| [disk_volume_name](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:110>) | def |
| [power_action_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:115>) | def |
| [windows_notification_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:119>) | def |
| [master_balance_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:123>) | def |
| [app_session_count_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:128>) | def |
| [total_audio_session_count_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:132>) | def |
| [tracked_device_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:136>) | def |
| [overlay_notification_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:140>) | def |
| [overlay_monitor_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:144>) | def |
| [_legacy_overlay_template_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:149>) | def |
| [audio_profile_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:155>) | def |
| [_device](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:160>) | def |
| [_origin](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:170>) | def |
| [_base_entity](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:177>) | def |
| [discovery_messages](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:188>) | def |
| [discovery_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:967>) | def |
| [all_possible_discovery_messages](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:971>) | def |
| [all_possible_discovery_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:1065>) | def |
| [referenced_mqtt_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:1069>) | def |
| [all_possible_mqtt_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py:1078>) | def |

### ha_windows_bridge/i18n.py

Globalny język i stary słownik PL/EN; ujednolicić z obecnym shell.

Wewnętrzne importy: [ha_windows_bridge/security.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/security.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `copy`, `logging`.

| Symbol | Rodzaj |
| --- | --- |
| [translate](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py:432>) | def |
| [set_active_language](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py:438>) | def |
| [active_language](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py:443>) | def |
| [LocalizedFormatter](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py:447>) | class |
| [LocalizedFormatter.add_secrets](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py:452>) | def |
| [LocalizedFormatter.format](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py:455>) | def |

### ha_windows_bridge/integration_protocol.py

Announcement i definicje encji; semantyczne capabilities, wersja i wspólne fixtures.

Wewnętrzne importy: [ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__init__.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/discovery.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py>), [ha_windows_bridge/media_protocol.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `copy`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [integration_entity_definitions](<F:/Codex/HA MQTT PC/ha_windows_bridge/integration_protocol.py:12>) | def |
| [integration_announcement_payload](<F:/Codex/HA MQTT PC/ha_windows_bridge/integration_protocol.py:33>) | def |

### ha_windows_bridge/media.py

WinRT runner, GSMTC snapshot, artwork i komendy; jeden owner, session identity i eventy.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `asyncio`, `collections`, `concurrent`, `contextlib`, `dataclasses`, `datetime`, `hashlib`, `logging`, `pathlib`, `threading`, `time`, `typing`, `winrt`.

| Symbol | Rodzaj |
| --- | --- |
| [MediaArtwork](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:21>) | class |
| [MediaCapabilities](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:28>) | class |
| [MediaCapabilities.enabled_names](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:36>) | def |
| [MediaSnapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:45>) | class |
| [_seconds](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:60>) | def |
| [_playback_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:67>) | def |
| [friendly_media_source](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:76>) | def |
| [_timeline_position](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:103>) | def |
| [_image_content_type](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:115>) | def |
| [_read_artwork](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:127>) | async def |
| [_AsyncRunner](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:163>) | class |
| [_AsyncRunner.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:164>) | def |
| [_AsyncRunner._run](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:177>) | def |
| [_AsyncRunner.call](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:191>) | def |
| [_AsyncRunner.close](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:203>) | def |
| [WindowsMediaService](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:212>) | class |
| [WindowsMediaService.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:215>) | def |
| [WindowsMediaService._ensure_runner](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:226>) | def |
| [WindowsMediaService._manager_async](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:244>) | async def |
| [WindowsMediaService._snapshot_async](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:253>) | async def |
| [WindowsMediaService._artwork_async](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:292>) | async def |
| [WindowsMediaService.snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:312>) | def |
| [WindowsMediaService._execute_async](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:323>) | async def |
| [WindowsMediaService.execute](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:342>) | def |
| [WindowsMediaService.close](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:353>) | def |
| [WindowsMediaService.reopen](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py:362>) | def |

### ha_windows_bridge/media_protocol.py

Serializacja media i artwork po stronie Windows; jeden kontrakt obu końców.

Wewnętrzne importy: [ha_windows_bridge/audio.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/audio.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/media.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `base64`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [media_announcement_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py:11>) | def |
| [media_topics](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py:15>) | def |
| [media_thumbnail_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py:20>) | def |
| [media_state_payload](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py:24>) | def |
| [media_artwork_payload](<F:/Codex/HA MQTT PC/ha_windows_bridge/media_protocol.py:44>) | def |

### ha_windows_bridge/mqtt_cleanup.py

Usuwanie własnych starych retained topics; ograniczać do znanego inventory/prefixu.

Wewnętrzne importy: [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/discovery.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/discovery.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `contextlib`, `dataclasses`, `paho`, `threading`, `time`, `uuid`.

| Symbol | Rodzaj |
| --- | --- |
| [MqttCleanupResult](<F:/Codex/HA MQTT PC/ha_windows_bridge/mqtt_cleanup.py:19>) | class |
| [_safe_topic](<F:/Codex/HA MQTT PC/ha_windows_bridge/mqtt_cleanup.py:27>) | def |
| [cleanup_application_mqtt_data](<F:/Codex/HA MQTT PC/ha_windows_bridge/mqtt_cleanup.py:38>) | def |
| [cleanup_application_mqtt_data.on_connect](<F:/Codex/HA MQTT PC/ha_windows_bridge/mqtt_cleanup.py:64>) | def |
| [cleanup_application_mqtt_data.on_connect_fail](<F:/Codex/HA MQTT PC/ha_windows_bridge/mqtt_cleanup.py:71>) | def |

### ha_windows_bridge/overlays/__init__.py

Znacznik pakietu / eksporty; bez własnej logiki usług.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/overlays/constants.py

Ograniczenia i dozwolone warianty; związać z publicznym schema.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `re`.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/overlays/engine.py

Czysta kolejka, visible/pending, timeout i media; doprecyzować PATCH/ack/lock policy.

Wewnętrzne importy: [ha_windows_bridge/overlays/models.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/models.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `copy`, `dataclasses`, `time`.

| Symbol | Rodzaj |
| --- | --- |
| [Notification](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:12>) | class |
| [Notification.id](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:20>) | def |
| [NotificationEngine](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:24>) | class |
| [NotificationEngine.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:25>) | def |
| [NotificationEngine.submit](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:31>) | def |
| [NotificationEngine._activate](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:79>) | def |
| [NotificationEngine.remove](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:85>) | def |
| [NotificationEngine.defer](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:91>) | def |
| [NotificationEngine.release_deferred](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:100>) | def |
| [NotificationEngine._promote](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:104>) | def |
| [NotificationEngine.pause](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:115>) | def |
| [NotificationEngine.tick](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:126>) | def |
| [NotificationEngine.lifetime](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:135>) | def |
| [NotificationEngine.needs_clock](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:143>) | def |
| [NotificationEngine.media_position](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:146>) | def |
| [NotificationEngine.media_advancing](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:153>) | def |
| [NotificationEngine.refresh_media](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py:157>) | def |

### ha_windows_bridge/overlays/examples.py

Przykłady powiadomień; generować według wspólnego kontraktu.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `base64`, `functools`.

| Symbol | Rodzaj |
| --- | --- |
| [media_artwork](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/examples.py:12>) | def |
| [media_example](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/examples.py:38>) | def |

### ha_windows_bridge/overlays/glass.py

Timer, worker i obróbka tła; capture opcjonalny, pełny lifecycle i budżet energii.

Wewnętrzne importy: [ha_windows_bridge/runtime/worker.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py>), [ha_windows_bridge/windows/capture.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py>).
Importowane korzenie zewnętrzne/stdlib: `PIL`, `PySide6`, `__future__`, `hashlib`, `threading`, `time`.

| Symbol | Rodzaj |
| --- | --- |
| [blur_scene](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:16>) | def |
| [GlassRenderer](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:26>) | class |
| [GlassRenderer.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:29>) | def |
| [GlassRenderer.targets](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:44>) | def |
| [GlassRenderer.can_prime](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:51>) | def |
| [GlassRenderer.sync](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:54>) | def |
| [GlassRenderer.request](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:71>) | def |
| [GlassRenderer.request.render](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:87>) | def |
| [GlassRenderer._accept](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:109>) | def |
| [GlassRenderer._release_staged](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:130>) | def |
| [GlassRenderer._release](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:137>) | def |
| [GlassRenderer.invalidate](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:141>) | def |
| [GlassRenderer.close](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py:145>) | def |

### ha_windows_bridge/overlays/media_style.py

Tokeny i styl karty media; scalić z design system.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`.

| Symbol | Rodzaj |
| --- | --- |
| [artwork_rect](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py:8>) | def |
| [transition_bounds](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py:15>) | def |
| [edge_colour](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py:20>) | def |
| [contrast_ratio](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py:40>) | def |
| [contrast_ratio.luminance](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py:41>) | def |
| [ensure_contrast](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py:49>) | def |
| [media_palette](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py:62>) | def |

### ha_windows_bridge/overlays/models.py

Normalizacja notification i opcji; ścisłe typy, tri-state PATCH, bez rozproszonych defaults.

Wewnętrzne importy: [ha_windows_bridge/overlays/constants.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/constants.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `math`, `typing`, `uuid`.

| Symbol | Rodzaj |
| --- | --- |
| [validated_request](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/models.py:10>) | def |
| [finite_number](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/models.py:144>) | def |

### ha_windows_bridge/overlays/positioning.py

Czysta geometria i stacking/work area; dodać stable monitor identity przy adapterze.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`.

| Symbol | Rodzaj |
| --- | --- |
| [position_at_edge](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:7>) | def |
| [Rect](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:23>) | class |
| [Rect.right](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:30>) | def |
| [Rect.bottom](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:34>) | def |
| [Rect.intersects](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:37>) | def |
| [CardSize](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:42>) | class |
| [PlacementEngine](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:51>) | class |
| [PlacementEngine.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:58>) | def |
| [PlacementEngine.place](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py:61>) | def |

### ha_windows_bridge/overlays/presentation.py

Widget, content, QR, layout, animation i efekt; wydzielić przygotowanie contentu i host.

Wewnętrzne importy: [ha_windows_bridge/overlays/media_style.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/media_style.py>), [ha_windows_bridge/ui/motion.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py>), [ha_windows_bridge/windows_effects.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py>).
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `base64`, `qrcode`, `qtawesome`.

| Symbol | Rodzaj |
| --- | --- |
| [NotificationWindow](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:51>) | class |
| [NotificationWindow.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:56>) | def |
| [NotificationWindow.update_notification](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:126>) | def |
| [NotificationWindow._surface_region](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:310>) | def |
| [NotificationWindow._apply_surface_mask](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:315>) | def |
| [NotificationWindow._reinforce_surface_mask](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:320>) | def |
| [NotificationWindow._visual_widgets](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:329>) | def |
| [NotificationWindow._prepare_intro_frame](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:334>) | def |
| [NotificationWindow._finish_intro_frame](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:344>) | def |
| [NotificationWindow.stage](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:351>) | def |
| [NotificationWindow._update_media_buttons](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:361>) | def |
| [NotificationWindow.set_glass_image](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:367>) | def |
| [NotificationWindow.set_media_position](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:371>) | def |
| [NotificationWindow.paintEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:385>) | def |
| [NotificationWindow.constrain_width](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:454>) | def |
| [NotificationWindow.place](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:459>) | def |
| [NotificationWindow.place.frame](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:496>) | def |
| [NotificationWindow.place.complete](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:504>) | def |
| [NotificationWindow.place.start_animation](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:512>) | def |
| [NotificationWindow.retire](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:523>) | def |
| [NotificationWindow.retire.frame](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:538>) | def |
| [NotificationWindow.dispose](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:550>) | def |
| [NotificationWindow.enterEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:562>) | def |
| [NotificationWindow.leaveEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:566>) | def |
| [NotificationWindow.mouseReleaseEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py:570>) | def |

### ha_windows_bridge/overlays/service.py

Qt ingress, timery, okna i engine; bounded inbox i rzeczywisty wynik przyjęcia.

Wewnętrzne importy: [ha_windows_bridge/overlays/engine.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/engine.py>), [ha_windows_bridge/overlays/glass.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/glass.py>), [ha_windows_bridge/overlays/positioning.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/positioning.py>), [ha_windows_bridge/overlays/presentation.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/presentation.py>).
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `collections`, `contextlib`.

| Symbol | Rodzaj |
| --- | --- |
| [OverlayService](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:16>) | class |
| [OverlayService.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:19>) | def |
| [OverlayService._apply_preferences](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:46>) | def |
| [OverlayService._event](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:52>) | def |
| [OverlayService._example_options](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:80>) | def |
| [OverlayService.example](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:84>) | def |
| [OverlayService._screens_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:103>) | def |
| [OverlayService._display_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:111>) | def |
| [OverlayService._sync](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:115>) | def |
| [OverlayService._place](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:140>) | def |
| [OverlayService._dismiss](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:176>) | def |
| [OverlayService._hover](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:180>) | def |
| [OverlayService._clock_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:184>) | def |
| [OverlayService._tick](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:198>) | def |
| [OverlayService.close](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/service.py:210>) | def |

### ha_windows_bridge/overlays/windows_media.py

Model danych/payload dla lokalnego media overlay; użyć wspólnego snapshotu.

Wewnętrzne importy: [ha_windows_bridge/media.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/media.py>).
Importowane korzenie zewnętrzne/stdlib: `__future__`, `base64`.

| Symbol | Rodzaj |
| --- | --- |
| [windows_media_payload](<F:/Codex/HA MQTT PC/ha_windows_bridge/overlays/windows_media.py:9>) | def |

### ha_windows_bridge/runtime/__init__.py

Znacznik pakietu / eksporty; bez własnej logiki usług.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/runtime/polling.py

Deadline per source, cache i izolacja wyjątków; dodać quality, nie udawać izolacji blokowania.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `logging`, `time`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [PollScheduler](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/polling.py:11>) | class |
| [PollScheduler.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/polling.py:14>) | def |
| [PollScheduler.run](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/polling.py:21>) | def |

### ha_windows_bridge/runtime/worker.py

Ograniczony SerialWorker i stop; jawny wynik końca oraz podział kolejek według ownership.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `logging`, `threading`.

| Symbol | Rodzaj |
| --- | --- |
| [SerialWorker](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py:9>) | class |
| [SerialWorker.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py:12>) | def |
| [SerialWorker.submit](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py:21>) | def |
| [SerialWorker.is_alive](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py:33>) | def |
| [SerialWorker._run](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py:36>) | def |
| [SerialWorker.close](<F:/Codex/HA MQTT PC/ha_windows_bridge/runtime/worker.py:48>) | def |

### ha_windows_bridge/security.py

Walidacja hostów/topiców/URL, ochrona/redakcja starszych ścieżek; zredukować duplikaty.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `re`, `typing`, `urllib`.

| Symbol | Rodzaj |
| --- | --- |
| [redact_text](<F:/Codex/HA MQTT PC/ha_windows_bridge/security.py:20>) | def |
| [redact_data](<F:/Codex/HA MQTT PC/ha_windows_bridge/security.py:30>) | def |

### ha_windows_bridge/single_instance.py

Named mutex w sesji użytkownika; pełne ctypes/error handling, opcjonalna aktywacja okna.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `ctypes`.

| Symbol | Rodzaj |
| --- | --- |
| [SingleInstance](<F:/Codex/HA MQTT PC/ha_windows_bridge/single_instance.py:8>) | class |
| [SingleInstance.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/single_instance.py:9>) | def |
| [SingleInstance.close](<F:/Codex/HA MQTT PC/ha_windows_bridge/single_instance.py:14>) | def |

### ha_windows_bridge/startup.py

HKCU Run i cytowanie komendy; wynik apply i cleanup uninstall.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `contextlib`, `subprocess`, `sys`, `winreg`.

| Symbol | Rodzaj |
| --- | --- |
| [WindowsStartupManager](<F:/Codex/HA MQTT PC/ha_windows_bridge/startup.py:13>) | class |
| [WindowsStartupManager.command](<F:/Codex/HA MQTT PC/ha_windows_bridge/startup.py:15>) | def |
| [WindowsStartupManager.is_enabled](<F:/Codex/HA MQTT PC/ha_windows_bridge/startup.py:22>) | def |
| [WindowsStartupManager.set_enabled](<F:/Codex/HA MQTT PC/ha_windows_bridge/startup.py:30>) | def |

### ha_windows_bridge/system_actions.py

Ograniczone akcje zasilania; rozdzielić forced shutdown i uprawnienia.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `collections`, `ctypes`, `os`, `pathlib`, `subprocess`.

| Symbol | Rodzaj |
| --- | --- |
| [WindowsPowerActions](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py:13>) | class |
| [WindowsPowerActions.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py:16>) | def |
| [WindowsPowerActions.execute](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py:25>) | def |
| [WindowsPowerActions._lock](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py:62>) | def |
| [WindowsPowerActions._sleep](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py:70>) | def |
| [WindowsPowerActions._shutdown_command](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_actions.py:77>) | def |

### ha_windows_bridge/system_monitor.py

Kontekst, WMI/WUA, PnP, GPU, dyski, shell/process actions; niezależni providerzy i COM.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `ctypes`, `dataclasses`, `json`, `math`, `os`, `pathlib`, `psutil`, `pythoncom`, `subprocess`, `threading`, `time`, `typing`, `win32com`, `win32con`, `win32gui`, `win32process`, `winreg`.

| Symbol | Rodzaj |
| --- | --- |
| [PcContext](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:23>) | class |
| [SystemMetrics](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:32>) | class |
| [WindowsHealth](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:54>) | class |
| [DiskMetrics](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:64>) | class |
| [DiskVolume](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:74>) | class |
| [PnpDevice](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:84>) | class |
| [_LastInputInfo](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:91>) | class |
| [WindowsSystemMonitor](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:95>) | class |
| [WindowsSystemMonitor.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:112>) | def |
| [WindowsSystemMonitor.context_snapshot](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:124>) | def |
| [WindowsSystemMonitor.idle_seconds](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:146>) | def |
| [WindowsSystemMonitor.is_locked](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:156>) | def |
| [WindowsSystemMonitor._is_fullscreen](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:166>) | def |
| [WindowsSystemMonitor.system_metrics](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:185>) | def |
| [WindowsSystemMonitor.windows_health](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:236>) | def |
| [WindowsSystemMonitor._schedule_windows_update_check](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:273>) | def |
| [WindowsSystemMonitor._read_pending_windows_updates](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:288>) | def |
| [WindowsSystemMonitor.list_disk_volumes](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:307>) | def |
| [WindowsSystemMonitor.disk_metrics](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:335>) | def |
| [WindowsSystemMonitor._physical_disk_health](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:371>) | def |
| [WindowsSystemMonitor.list_pnp_devices](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:416>) | def |
| [WindowsSystemMonitor._pnp_devices_from_powershell](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:450>) | def |
| [WindowsSystemMonitor._is_user_facing_pnp_device](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:508>) | def |
| [WindowsSystemMonitor._sorted_pnp_devices](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:604>) | def |
| [WindowsSystemMonitor.present_device_ids](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:627>) | def |
| [WindowsSystemMonitor._pending_restart](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:633>) | def |
| [WindowsSystemMonitor._active_power_plan](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:653>) | def |
| [WindowsSystemMonitor._hardware_identity](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:682>) | def |
| [WindowsSystemMonitor.running_process_names](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:707>) | def |
| [WindowsSystemMonitor._windows_apps_shell_target](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:723>) | def |
| [WindowsSystemMonitor._shell_open](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:734>) | def |
| [WindowsSystemMonitor.start_application](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:742>) | def |
| [WindowsSystemMonitor.close_application](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:768>) | def |
| [WindowsSystemMonitor.close_application.request_close](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:789>) | def |
| [WindowsSystemMonitor._find_nvidia_smi](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:810>) | def |
| [WindowsSystemMonitor._gpu_metrics](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:829>) | def |
| [WindowsSystemMonitor._windows_gpu_metrics](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:877>) | def |
| [WindowsSystemMonitor._hardware_monitor_metrics](<F:/Codex/HA MQTT PC/ha_windows_bridge/system_monitor.py:908>) | def |

### ha_windows_bridge/theme.py

Starsze QSS/tokeny używane pośrednio; jeden zestaw źródeł stylu.

Wewnętrzne importy: [ha_windows_bridge/ui/theme.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py>).
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/ui/__init__.py

Znacznik pakietu / eksporty; bez własnej logiki usług.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/ui/control_style.py

ProxyStyle i natywne kontrolki; testować aktualną linię Qt.

Wewnętrzne importy: [ha_windows_bridge/ui/theme.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py>).
Importowane korzenie zewnętrzne/stdlib: `PySide6`.

| Symbol | Rodzaj |
| --- | --- |
| [BridgeProxyStyle](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/control_style.py:8>) | class |
| [BridgeProxyStyle.drawPrimitive](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/control_style.py:11>) | def |

### ha_windows_bridge/ui/inputs.py

Bezpieczne zachowanie wheel i kontrolek formularza; spójna klawiatura/focus.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `PySide6`.

| Symbol | Rodzaj |
| --- | --- |
| [WheelSafeComboBox](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/inputs.py:5>) | class |
| [WheelSafeComboBox.wheelEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/inputs.py:8>) | def |
| [SettingsWheelGuard](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/inputs.py:12>) | class |
| [SettingsWheelGuard.eventFilter](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/inputs.py:15>) | def |

### ha_windows_bridge/ui/motion.py

Motion tokens i Reduced Motion; jedyne źródło polityki dla całego UI/overlay.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `collections`, `ctypes`, `dataclasses`, `sys`.

| Symbol | Rodzaj |
| --- | --- |
| [MotionToken](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py:15>) | class |
| [MotionSystem](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py:22>) | class |
| [MotionSystem.enabled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py:37>) | def |
| [MotionSystem.animate](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py:51>) | def |

### ha_windows_bridge/ui/navigation.py

Animowana nawigacja i strony; ujednolicić tokeny i obsługę focus.

Wewnętrzne importy: [ha_windows_bridge/ui/motion.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py>).
Importowane korzenie zewnętrzne/stdlib: `PySide6`.

| Symbol | Rodzaj |
| --- | --- |
| [PageStack](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/navigation.py:9>) | class |
| [PageStack.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/navigation.py:10>) | def |
| [PageStack._clear_transition](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/navigation.py:15>) | def |
| [PageStack.setCurrentIndex](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/navigation.py:25>) | def |

### ha_windows_bridge/ui/shell.py

IA, formularze, inventory, tray, config i eventy; view models nad wspólnym stanem.

Wewnętrzne importy: [ha_windows_bridge/__init__.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/__init__.py>), [ha_windows_bridge/communication/state.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/state.py>), [ha_windows_bridge/communication/status.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/communication/status.py>), [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/core/configuration.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/core/configuration.py>), [ha_windows_bridge/ui/inputs.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/inputs.py>), [ha_windows_bridge/ui/navigation.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/navigation.py>), [ha_windows_bridge/ui_components.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py>).
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `copy`, `enum`, `html`, `pathlib`, `qtawesome`.

| Symbol | Rodzaj |
| --- | --- |
| [Page](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:60>) | class |
| [UiEvents](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:69>) | class |
| [DesktopWindow](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:73>) | class |
| [DesktopWindow.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:74>) | def |
| [DesktopWindow._build](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:102>) | def |
| [DesktopWindow._content](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:181>) | def |
| [DesktopWindow._button](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:185>) | def |
| [DesktopWindow._card](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:190>) | def |
| [DesktopWindow._dashboard](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:207>) | def |
| [DesktopWindow._connections](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:222>) | def |
| [DesktopWindow._connections.field](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:227>) | def |
| [DesktopWindow._get](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:265>) | def |
| [DesktopWindow._set](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:271>) | def |
| [DesktopWindow._toggle](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:278>) | def |
| [DesktopWindow._applications](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:285>) | def |
| [DesktopWindow._add_card](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:297>) | def |
| [DesktopWindow._add_app](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:307>) | def |
| [DesktopWindow._remove_card](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:315>) | def |
| [DesktopWindow._activate_page](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:321>) | def |
| [DesktopWindow._refresh_visible_page](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:327>) | def |
| [DesktopWindow._update_applications](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:336>) | def |
| [DesktopWindow._overlays](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:370>) | def |
| [DesktopWindow._settings](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:407>) | def |
| [DesktopWindow._collect](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:429>) | def |
| [DesktopWindow._save](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:437>) | def |
| [DesktopWindow._refresh_fields](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:441>) | def |
| [DesktopWindow._export_settings](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:459>) | def |
| [DesktopWindow._import_settings](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:468>) | def |
| [DesktopWindow._reset_settings](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:488>) | def |
| [DesktopWindow._select_inventory](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:498>) | def |
| [DesktopWindow._diagnostics](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:527>) | def |
| [DesktopWindow._refresh_status](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:537>) | def |
| [DesktopWindow._event](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:568>) | def |
| [DesktopWindow._tray](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:618>) | def |
| [DesktopWindow.dispose](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:639>) | def |
| [DesktopWindow.showEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:648>) | def |
| [DesktopWindow.hideEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:653>) | def |
| [DesktopWindow.closeEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/shell.py:658>) | def |

### ha_windows_bridge/ui/theme.py

Bieżący motyw shell/light/dark/accent; scalić tokeny i sprawdzić kontrast.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `re`, `string`.

| Symbol | Rodzaj |
| --- | --- |
| [ThemeTokens](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py:13>) | class |
| [normalize_theme](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py:38>) | def |
| [style_for_theme](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py:149>) | def |

### ha_windows_bridge/ui_components.py

Używany AppCard i pozostałości dawnego UI; naprawić klawiaturę, usuwać tylko bez referencji.

Wewnętrzne importy: [ha_windows_bridge/config.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/config.py>), [ha_windows_bridge/i18n.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/i18n.py>), [ha_windows_bridge/ui/motion.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/motion.py>), [ha_windows_bridge/ui/theme.py](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui/theme.py>).
Importowane korzenie zewnętrzne/stdlib: `PIL`, `PySide6`, `__future__`, `qtawesome`, `win32gui`.

| Symbol | Rodzaj |
| --- | --- |
| [HelpButton](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:55>) | class |
| [HelpButton.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:58>) | def |
| [HelpButton.show_help](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:67>) | def |
| [HelpButton.enterEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:74>) | def |
| [ToggleSwitch](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:79>) | class |
| [ToggleSwitch.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:82>) | def |
| [ToggleSwitch.sizeHint](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:95>) | def |
| [ToggleSwitch.get_knob_position](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:98>) | def |
| [ToggleSwitch.set_knob_position](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:101>) | def |
| [ToggleSwitch._animate](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:107>) | def |
| [ToggleSwitch.paintEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:116>) | def |
| [ToggleSwitch.focusInEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:149>) | def |
| [ToggleSwitch.mousePressEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:154>) | def |
| [TitleBar](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:162>) | class |
| [TitleBar.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:165>) | def |
| [TitleBar._window_button](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:224>) | def |
| [TitleBar.toggle_maximize](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:232>) | def |
| [TitleBar.mousePressEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:241>) | def |
| [TitleBar.mouseDoubleClickEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:248>) | def |
| [NavButton](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:254>) | class |
| [NavButton.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:255>) | def |
| [NavButton.refresh_icon](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:267>) | def |
| [NavButton.set_language](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:272>) | def |
| [NavButton.set_compact](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:278>) | def |
| [AppCard](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:284>) | class |
| [AppCard.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:291>) | def |
| [AppCard._initials](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:391>) | def |
| [AppCard._show_initials](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:397>) | def |
| [AppCard._show_options_menu](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:405>) | def |
| [AppCard.set_executable_icon](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:410>) | def |
| [AppCard.event](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:440>) | def |
| [AppCard._remote_start_toggled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:446>) | def |
| [AppCard._extract_windows_icon](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:464>) | def |
| [AppCard._trim_transparent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:480>) | def |
| [AppCard.edit](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:496>) | def |
| [AppCard.to_config](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:518>) | def |
| [AppCard.set_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:529>) | def |
| [AppCard._slider_pressed](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:544>) | def |
| [AppCard._slider_released](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:547>) | def |
| [AppCard._slider_value_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:551>) | def |
| [AppCard.set_muted](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:554>) | def |
| [AppCard._apply_enabled_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:566>) | def |
| [AppCard._mute_toggled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:576>) | def |
| [MasterVolumeCard](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:581>) | class |
| [MasterVolumeCard.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:586>) | def |
| [MasterVolumeCard.set_volume](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:648>) | def |
| [MasterVolumeCard._slider_pressed](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:663>) | def |
| [MasterVolumeCard._slider_released](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:666>) | def |
| [MasterVolumeCard._slider_value_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:670>) | def |
| [MasterVolumeCard.set_muted](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:673>) | def |
| [MasterVolumeCard._mute_toggled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:684>) | def |
| [MasterVolumeCard.set_feature_enabled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:688>) | def |
| [MasterVolumeCard._apply_feature_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:694>) | def |
| [MicrophoneCard](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:705>) | class |
| [MicrophoneCard.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:710>) | def |
| [MicrophoneCard.set_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:770>) | def |
| [MicrophoneCard._slider_released](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:795>) | def |
| [MicrophoneCard._mute_toggled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:799>) | def |
| [MicrophoneCard.set_feature_enabled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:803>) | def |
| [MicrophoneCard._apply_feature_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:809>) | def |
| [AudioOutputCard](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:820>) | class |
| [AudioOutputCard.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:825>) | def |
| [AudioOutputCard.set_devices](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:873>) | def |
| [AudioOutputCard._selection_changed](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:883>) | def |
| [AudioOutputCard.set_feature_enabled](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:887>) | def |
| [AudioOutputCard._apply_feature_state](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:893>) | def |
| [SettingControlRow](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:904>) | class |
| [SettingControlRow.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:907>) | def |
| [SettingRow](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:931>) | class |
| [SettingRow.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:932>) | def |
| [SettingRow._apply_enabled_style](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:941>) | def |
| [WifiStatusBadge](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:948>) | class |
| [WifiStatusBadge.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:949>) | def |
| [WifiStatusBadge.set_connected](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:954>) | def |
| [WifiStatusBadge.paintEvent](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:958>) | def |
| [StatusCard](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:992>) | class |
| [StatusCard.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:993>) | def |
| [StatusCard.update_status](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:1037>) | def |
| [StatusCard.set_language](<F:/Codex/HA MQTT PC/ha_windows_bridge/ui_components.py:1047>) | def |

### ha_windows_bridge/updater.py

GitHub latest i porównanie wersji; poprawna obsługa prerelease i kanałów.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `json`, `re`, `typing`, `urllib`.

| Symbol | Rodzaj |
| --- | --- |
| [UpdateInfo](<F:/Codex/HA MQTT PC/ha_windows_bridge/updater.py:16>) | class |
| [_version_tuple](<F:/Codex/HA MQTT PC/ha_windows_bridge/updater.py:24>) | def |
| [parse_release](<F:/Codex/HA MQTT PC/ha_windows_bridge/updater.py:29>) | def |
| [GitHubUpdateChecker](<F:/Codex/HA MQTT PC/ha_windows_bridge/updater.py:46>) | class |
| [GitHubUpdateChecker.check](<F:/Codex/HA MQTT PC/ha_windows_bridge/updater.py:49>) | def |

### ha_windows_bridge/windows/__init__.py

Znacznik pakietu / eksporty; bez własnej logiki usług.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: brak.

Brak deklaracji klas i funkcji.

### ha_windows_bridge/windows/capture.py

DXGI/DXcam, mapowanie output i wykluczanie okien; ograniczyć prywatne API i cache topology.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `contextlib`, `ctypes`, `dataclasses`, `dxcam`, `re`, `sys`, `typing`.

| Symbol | Rodzaj |
| --- | --- |
| [CaptureResult](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:17>) | class |
| [DesktopDuplicationCapture](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:22>) | class |
| [DesktopDuplicationCapture.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:29>) | def |
| [DesktopDuplicationCapture.available](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:37>) | def |
| [DesktopDuplicationCapture._load](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:47>) | def |
| [DesktopDuplicationCapture._camera](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:58>) | def |
| [DesktopDuplicationCapture._set_capture_excluded](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:81>) | def |
| [DesktopDuplicationCapture.grab](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:96>) | def |
| [DesktopDuplicationCapture.release](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:150>) | def |
| [DesktopDuplicationCapture.grab_image](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:156>) | def |
| [DesktopDuplicationCapture.invalidate](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:185>) | def |
| [on_battery_power](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:194>) | def |
| [on_battery_power.SystemPowerStatus](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/capture.py:198>) | class |

### ha_windows_bridge/windows/credentials.py

Mały adapter DPAPI bieżącego użytkownika.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `win32crypt`.

| Symbol | Rodzaj |
| --- | --- |
| [DpapiCipher](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/credentials.py:2>) | class |
| [DpapiCipher.encrypt](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/credentials.py:3>) | def |
| [DpapiCipher.decrypt](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/credentials.py:7>) | def |

### ha_windows_bridge/windows/native.py

Power/WTS/display/theme/Explorer events; dodać brakujące źródła i cleanup.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `PySide6`, `__future__`, `ctypes`, `sys`.

| Symbol | Rodzaj |
| --- | --- |
| [system_accent](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/native.py:12>) | def |
| [WindowsEventBridge](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/native.py:23>) | class |
| [WindowsEventBridge.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/native.py:24>) | def |
| [WindowsEventBridge.nativeEventFilter](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/native.py:36>) | def |
| [WindowsEventBridge.close](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/native.py:57>) | def |

### ha_windows_bridge/windows/resources.py

Inwentarz zasobów Qt/Windows do diagnostyki; prywatność i bezpieczny odczyt.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `dataclasses`, `psutil`, `threading`, `time`.

| Symbol | Rodzaj |
| --- | --- |
| [ResourceUsage](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/resources.py:12>) | class |
| [ProcessResources](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/resources.py:18>) | class |
| [ProcessResources.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/resources.py:19>) | def |
| [ProcessResources.sample](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows/resources.py:27>) | def |

### ha_windows_bridge/windows_effects.py

Win32/DWM, DPI i preferencje animacji; używać feature gates, oddzielić martwe efekty.

Wewnętrzne importy: brak.
Importowane korzenie zewnętrzne/stdlib: `__future__`, `ctypes`, `sys`.

| Symbol | Rodzaj |
| --- | --- |
| [enable_per_monitor_v2](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:8>) | def |
| [_AccentPolicy](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:21>) | class |
| [_WindowCompositionAttributeData](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:30>) | class |
| [NativeBackdrop](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:38>) | class |
| [NativeBackdrop.__init__](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:56>) | def |
| [NativeBackdrop._dwm_attribute](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:61>) | def |
| [NativeBackdrop._legacy_acrylic](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:75>) | def |
| [NativeBackdrop._is_layered_window](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:98>) | def |
| [NativeBackdrop.apply_acrylic](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:108>) | def |
| [NativeBackdrop.prepare_window](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:136>) | def |
| [NativeBackdrop.exclude_capture](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:151>) | def |
| [NativeBackdrop.apply_rounded_region](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:160>) | def |
| [NativeBackdrop.apply_blur](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:201>) | def |
| [NativeBackdrop.disable](<F:/Codex/HA MQTT PC/ha_windows_bridge/windows_effects.py:213>) | def |

## Testy

Wszystkie poniższe pliki objął wykonany pytest suite: 274 przypadki PASS. Liczba deklaracji test_* nie musi odpowiadać liczbie przypadków po parametryzacji. Ocena jakości oraz brakujące testy: sekcja 15 raportu.

| Plik | Linie | Deklaracje test_* |
| --- | --- | --- |
| [tests/test_alpha2_polish.py](<F:/Codex/HA MQTT PC/tests/test_alpha2_polish.py>) | 160 | 6 |
| [tests/test_alpha3_visuals.py](<F:/Codex/HA MQTT PC/tests/test_alpha3_visuals.py>) | 165 | 8 |
| [tests/test_alpha4_repairs.py](<F:/Codex/HA MQTT PC/tests/test_alpha4_repairs.py>) | 225 | 11 |
| [tests/test_alpha5_popup.py](<F:/Codex/HA MQTT PC/tests/test_alpha5_popup.py>) | 408 | 16 |
| [tests/test_audio.py](<F:/Codex/HA MQTT PC/tests/test_audio.py>) | 9 | 1 |
| [tests/test_brand.py](<F:/Codex/HA MQTT PC/tests/test_brand.py>) | 18 | 1 |
| [tests/test_config.py](<F:/Codex/HA MQTT PC/tests/test_config.py>) | 281 | 16 |
| [tests/test_data_exchange.py](<F:/Codex/HA MQTT PC/tests/test_data_exchange.py>) | 73 | 3 |
| [tests/test_discovery.py](<F:/Codex/HA MQTT PC/tests/test_discovery.py>) | 203 | 7 |
| [tests/test_ha_lifecycle.py](<F:/Codex/HA MQTT PC/tests/test_ha_lifecycle.py>) | 113 | 4 |
| [tests/test_i18n.py](<F:/Codex/HA MQTT PC/tests/test_i18n.py>) | 23 | 1 |
| [tests/test_media.py](<F:/Codex/HA MQTT PC/tests/test_media.py>) | 433 | 16 |
| [tests/test_mqtt_cleanup.py](<F:/Codex/HA MQTT PC/tests/test_mqtt_cleanup.py>) | 76 | 1 |
| [tests/test_overlay_models.py](<F:/Codex/HA MQTT PC/tests/test_overlay_models.py>) | 38 | 4 |
| [tests/test_overlay_service.py](<F:/Codex/HA MQTT PC/tests/test_overlay_service.py>) | 144 | 4 |
| [tests/test_runtime.py](<F:/Codex/HA MQTT PC/tests/test_runtime.py>) | 97 | 5 |
| [tests/test_security.py](<F:/Codex/HA MQTT PC/tests/test_security.py>) | 56 | 3 |
| [tests/test_startup.py](<F:/Codex/HA MQTT PC/tests/test_startup.py>) | 16 | 1 |
| [tests/test_system_actions.py](<F:/Codex/HA MQTT PC/tests/test_system_actions.py>) | 50 | 3 |
| [tests/test_system_monitor.py](<F:/Codex/HA MQTT PC/tests/test_system_monitor.py>) | 356 | 19 |
| [tests/test_theme.py](<F:/Codex/HA MQTT PC/tests/test_theme.py>) | 32 | 3 |
| [tests/test_updater.py](<F:/Codex/HA MQTT PC/tests/test_updater.py>) | 35 | 3 |
| [tests/test_v2_application.py](<F:/Codex/HA MQTT PC/tests/test_v2_application.py>) | 66 | 2 |
| [tests/test_v2_configuration.py](<F:/Codex/HA MQTT PC/tests/test_v2_configuration.py>) | 45 | 3 |
| [tests/test_v2_core.py](<F:/Codex/HA MQTT PC/tests/test_v2_core.py>) | 126 | 6 |
| [tests/test_v2_desktop.py](<F:/Codex/HA MQTT PC/tests/test_v2_desktop.py>) | 83 | 2 |
| [tests/test_v2_ha_authorization.py](<F:/Codex/HA MQTT PC/tests/test_v2_ha_authorization.py>) | 54 | 2 |
| [tests/test_v2_ha_runtime.py](<F:/Codex/HA MQTT PC/tests/test_v2_ha_runtime.py>) | 143 | 5 |
| [tests/test_v2_notifications.py](<F:/Codex/HA MQTT PC/tests/test_v2_notifications.py>) | 48 | 3 |
| [tests/test_v2_positioning.py](<F:/Codex/HA MQTT PC/tests/test_v2_positioning.py>) | 29 | 3 |
| [tests/test_v2_transports.py](<F:/Codex/HA MQTT PC/tests/test_v2_transports.py>) | 130 | 7 |
| [tests/test_v2_ui_layout.py](<F:/Codex/HA MQTT PC/tests/test_v2_ui_layout.py>) | 68 | 2 |
| [tests/test_v2_windows_commands.py](<F:/Codex/HA MQTT PC/tests/test_v2_windows_commands.py>) | 106 | 6 |
| [tests/test_windows_effects.py](<F:/Codex/HA MQTT PC/tests/test_windows_effects.py>) | 167 | 6 |

## Entrypointy, narzędzia i spec

| Plik | Rola |
| --- | --- |
| [HAWindowsBridge.spec](<F:/Codex/HA MQTT PC/HAWindowsBridge.spec>) | PyInstaller: collect/excludes, zasoby i DLL; review konfiguracji, bez nowego builda. |
| [main.py](<F:/Codex/HA MQTT PC/main.py>) | Launcher source/frozen, przygotowanie zasobów i delegacja do desktop. |
| [mqtt_volume.pyw](<F:/Codex/HA MQTT PC/mqtt_volume.pyw>) | Zgodnościowy launcher GUI; zachować tylko przy świadomej potrzebie. |
| [tools/create_icon.py](<F:/Codex/HA MQTT PC/tools/create_icon.py>) | Generowanie zasobów marki; utility poza runtime. |
| [tools/package_ha_release.py](<F:/Codex/HA MQTT PC/tools/package_ha_release.py>) | Pakiet integracji HA; spójność manifestu i listy plików. |
| [tools/package_v2_preview.py](<F:/Codex/HA MQTT PC/tools/package_v2_preview.py>) | Artefakt preview; zbieżność z główną ścieżką release. |

## Pozostałe pliki śledzone przez Git

Dokumentacja starszych alpha jest dowodem historycznym, nie źródłem bieżących wyników audytu. Zasoby obrazów oceniano jako branding/packaging, nie jako moduły wykonujące logikę.

| Plik | Kategoria / uwaga |
| --- | --- |
| [.github/dependabot.yml](<F:/Codex/HA MQTT PC/.github/dependabot.yml>) | CI / aktualizacje zależności; konfiguracja poddana przeglądowi. |
| [.github/workflows/validate.yml](<F:/Codex/HA MQTT PC/.github/workflows/validate.yml>) | CI / aktualizacje zależności; konfiguracja poddana przeglądowi. |
| [.gitignore](<F:/Codex/HA MQTT PC/.gitignore>) | Wykluczenia artefaktów i lokalnych plików. |
| [Bridge 1.3.2](<F:/Codex/HA MQTT PC/Bridge 1.3.2>) | Przypadkowo śledzone wyjście terminala; kandydat do usunięcia (L05). |
| [CHANGELOG.md](<F:/Codex/HA MQTT PC/CHANGELOG.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [HOME_ASSISTANT_INTEGRATION.md](<F:/Codex/HA MQTT PC/HOME_ASSISTANT_INTEGRATION.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [LICENSE](<F:/Codex/HA MQTT PC/LICENSE>) | Licencja projektu; nie wykonywano odrębnego audytu prawnego. |
| [README.md](<F:/Codex/HA MQTT PC/README.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [RELEASING.md](<F:/Codex/HA MQTT PC/RELEASING.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [ROADMAP.md](<F:/Codex/HA MQTT PC/ROADMAP.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [SECURITY.md](<F:/Codex/HA MQTT PC/SECURITY.md>) | Polityka zgłaszania podatności i zakres wsparcia. |
| [assets/icon.ico](<F:/Codex/HA MQTT PC/assets/icon.ico>) | Zasób wizualny / branding. |
| [assets/icon.png](<F:/Codex/HA MQTT PC/assets/icon.png>) | Zasób wizualny / branding. |
| [assets/icon.svg](<F:/Codex/HA MQTT PC/assets/icon.svg>) | Zasób wizualny / branding. |
| [assets/version_info.txt](<F:/Codex/HA MQTT PC/assets/version_info.txt>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [brand/dark_icon.png](<F:/Codex/HA MQTT PC/brand/dark_icon.png>) | Zasób wizualny / branding. |
| [brand/icon.png](<F:/Codex/HA MQTT PC/brand/icon.png>) | Zasób wizualny / branding. |
| [build.ps1](<F:/Codex/HA MQTT PC/build.ps1>) | Build/test script; analiza ścieżek, poleceń i release, bez instalowania. |
| [constraints.txt](<F:/Codex/HA MQTT PC/constraints.txt>) | Zależności / metadane / narzędzia jakości; sekcje 13 i 15. |
| [custom_components/ha_windows_bridge/brand/dark_icon.png](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/brand/dark_icon.png>) | Zasób wizualny / branding. |
| [custom_components/ha_windows_bridge/brand/dark_logo.png](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/brand/dark_logo.png>) | Zasób wizualny / branding. |
| [custom_components/ha_windows_bridge/brand/icon.png](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/brand/icon.png>) | Zasób wizualny / branding. |
| [custom_components/ha_windows_bridge/brand/logo.png](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/brand/logo.png>) | Zasób wizualny / branding. |
| [custom_components/ha_windows_bridge/icons.json](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/icons.json>) | Kontrakt/metadata/UI integracji Home Assistant. |
| [custom_components/ha_windows_bridge/manifest.json](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/manifest.json>) | Kontrakt/metadata/UI integracji Home Assistant. |
| [custom_components/ha_windows_bridge/services.yaml](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/services.yaml>) | Kontrakt/metadata/UI integracji Home Assistant. |
| [custom_components/ha_windows_bridge/strings.json](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/strings.json>) | Kontrakt/metadata/UI integracji Home Assistant. |
| [custom_components/ha_windows_bridge/translations/en.json](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/translations/en.json>) | Kontrakt/metadata/UI integracji Home Assistant. |
| [custom_components/ha_windows_bridge/translations/pl.json](<F:/Codex/HA MQTT PC/custom_components/ha_windows_bridge/translations/pl.json>) | Kontrakt/metadata/UI integracji Home Assistant. |
| [docs/MODERNIZATION_ARCHITECTURE.md](<F:/Codex/HA MQTT PC/docs/MODERNIZATION_ARCHITECTURE.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/MODERNIZATION_AUDIT.md](<F:/Codex/HA MQTT PC/docs/MODERNIZATION_AUDIT.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/MODERNIZATION_FINAL_AUDIT.md](<F:/Codex/HA MQTT PC/docs/MODERNIZATION_FINAL_AUDIT.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/RELEASE_2.0.0-alpha.2.md](<F:/Codex/HA MQTT PC/docs/RELEASE_2.0.0-alpha.2.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/RELEASE_2.0.0-alpha.3.md](<F:/Codex/HA MQTT PC/docs/RELEASE_2.0.0-alpha.3.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/RELEASE_2.0.0-alpha.4.md](<F:/Codex/HA MQTT PC/docs/RELEASE_2.0.0-alpha.4.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/RELEASE_2.0.0-alpha.8.md](<F:/Codex/HA MQTT PC/docs/RELEASE_2.0.0-alpha.8.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/V2_DIFF_STAT.txt](<F:/Codex/HA MQTT PC/docs/V2_DIFF_STAT.txt>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/V2_QUICKSTART.md](<F:/Codex/HA MQTT PC/docs/V2_QUICKSTART.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/V2_REBUILD.md](<F:/Codex/HA MQTT PC/docs/V2_REBUILD.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/V2_VALIDATION.md](<F:/Codex/HA MQTT PC/docs/V2_VALIDATION.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/VALIDATION_2.0.0-alpha.2.md](<F:/Codex/HA MQTT PC/docs/VALIDATION_2.0.0-alpha.2.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/VALIDATION_2.0.0-alpha.3.md](<F:/Codex/HA MQTT PC/docs/VALIDATION_2.0.0-alpha.3.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/VALIDATION_2.0.0-alpha.4.md](<F:/Codex/HA MQTT PC/docs/VALIDATION_2.0.0-alpha.4.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [docs/VALIDATION_2.0.0-alpha.8.md](<F:/Codex/HA MQTT PC/docs/VALIDATION_2.0.0-alpha.8.md>) | Dokumentacja/wersja/walidacja; rozróżniono stan aktualny i archiwalny. |
| [e 1.3.2](<F:/Codex/HA MQTT PC/e 1.3.2>) | Przypadkowo śledzone wyjście terminala; kandydat do usunięcia (L05). |
| [hacs.json](<F:/Codex/HA MQTT PC/hacs.json>) | Kontrakt/metadata/UI integracji Home Assistant. |
| [installer/HAWindowsBridge.iss](<F:/Codex/HA MQTT PC/installer/HAWindowsBridge.iss>) | Instalator per-user; upgrade/uninstall/autostart wymagają realnej macierzy. |
| [pyproject.toml](<F:/Codex/HA MQTT PC/pyproject.toml>) | Zależności / metadane / narzędzia jakości; sekcje 13 i 15. |
| [requirements-dev.txt](<F:/Codex/HA MQTT PC/requirements-dev.txt>) | Zależności / metadane / narzędzia jakości; sekcje 13 i 15. |
| [requirements.txt](<F:/Codex/HA MQTT PC/requirements.txt>) | Zależności / metadane / narzędzia jakości; sekcje 13 i 15. |
| [scripts/test_local.ps1](<F:/Codex/HA MQTT PC/scripts/test_local.ps1>) | Build/test script; analiza ścieżek, poleceń i release, bez instalowania. |
| [tatus --short](<F:/Codex/HA MQTT PC/tatus --short>) | Przypadkowo śledzone wyjście terminala; kandydat do usunięcia (L05). |

## Zasady interpretacji

- KEEP nie oznacza zakazu zmian; oznacza brak uzasadnienia do przepisywania całej implementacji.
- Rola legacy nie oznacza, że cały plik jest nieużywany: config.py nadal zawiera aktywny model, a ui_components.py aktywny AppCard.
- Sprawdzenie importów nie wyklucza cykli wywołań ani zakleszczeń; C01 jest odtworzonym cyklem locków.
- Nie zmieniono żadnego z indeksowanych plików. Raport i ten załącznik są jedynymi nowymi dokumentami audytu.
