# HA Windows Bridge — niezależny audyt techniczny i produktowy

Data: 5 września 2026. Badany commit: `0df284b423ecf7c3e78563028fdab9e65d0c4270`. Wersja kodu: `2.0.0-alpha.8`.

Raport obejmuje kod aplikacji Windows, integrację Home Assistant, testy, konfigurację pakowania i dokumentację. Nie wprowadzono zmian w implementacji.

## 1. Executive summary

**Wybieram strategię B: bardzo głęboki refaktor z wymianą wybranych subsystemów.** Przebudowałbym zbieranie i publikowanie stanu, część lifecycle, granicę prezentacji overlay oraz model integracji HA. Zachowałbym Python, PySide6/Qt Widgets, czysty silnik kolejki i pozycjonowania, dużą część walidacji komend oraz DPAPI.

Projekt jest wartościową, szeroką funkcjonalnie wersją alpha. Ma już fundamenty drugiej generacji: osobny composition root, router komend, ograniczone kolejki, maszyny stanu połączeń i autoryzację Direct. **Nie jest jeszcze wiarygodnym agentem pracującym bezobsługowo przez wiele dni.** Największy problem to niespójny kontrakt pomiędzy stanem Windows, stanem dostarczonym do HA i cyklem życia właścicieli zasobów. Zielony status połączenia nie dowodzi aktualności encji.

Największa zaleta to użyteczny zestaw funkcji Windows + HA oraz kilka już dobrze odseparowanych fragmentów logiki. Odpowiedzią powinno być uporządkowanie granic odpowiedzialności i potwierdzeń, a następnie UX.

Odtworzyłem zakleszczenie MQTT na reconnect, utratę aktualizacji stanu, błąd tworzenia odtwarzacza aplikacji w HA, brak metody po zmianie urządzenia audio, wymazywanie tekstu przy częściowym update overlay, niespójność profilu po błędzie autostartu, przekroczenie limitu discovery przez 64 aplikacje i brak komendy po użyciu klawiatury na suwaku. Odczytowe próby Windows potwierdziły problem inicjalizacji COM i błędne zapytanie WMI o dyski.

| Strategia | Jakość / złożoność / ryzyko / utrzymanie | Decyzja |
| --- | --- | --- |
| A — ewolucyjny refaktor | Usunie lokalne regresje, lecz zachowa zależność sensorów od MQTT, dwa źródła danych audio i niepełne potwierdzenia. Dług utrzymania pozostanie. | Odrzucam jako główny kierunek. |
| **B — głęboki refaktor** | Pozwala wymienić błędne kontrakty i utrzymać sprawdzalną logikę. Każda wymiana może mieć własną bramkę jakości. | **Najlepszy stosunek jakości do złożoności i ryzyka.** |
| C — nowa generacja obok starej | Część tej pracy już wykonano: bieżący kod jest 2.0 alpha. Kolejny równoległy rdzeń powtórzyłby migrację i pomnożył adaptery. | Nie rekomenduję kolejnego startu architektury od zera. |
| D — pełny rewrite | Wymaga ponownego odkrycia zachowania COM, DWM, HA i urządzeń. Inny język nie usuwa problemów protokołu ani lifecycle. | Brak dowodów uzasadniających koszt i ryzyko. |

„2.0” w dalszej części oznacza docelową architekturę produktu; nie propozycję ponownego wydawania istniejących numerów.

**Zakres.** Inwentarz obejmuje 177 plików śledzonych przez Git: 85 modułów produkcyjnych Python, 13 430 linii tych modułów, 34 pliki testów i 4076 linii testów; dodatkowo entrypointy, narzędzia, CI, instalator, zasoby i dokumentację. Zależności z .venv, wygenerowane build/dist i zewnętrzny Inno Setup potraktowano jako zależności/artefakty, nie autorski kod do pełnego review. [Pełny inwentarz modułów](<F:/Codex/HA MQTT PC/docs/audit-2026-09-05/INVENTORY.md>).

**Własna walidacja:** 274 testy PASS w 17,37 s; Ruff PASS; pip check PASS; Bandit bez medium/high; pip-audit bez znanych podatności sprawdzonych bibliotek. Lokalnego projektu baza podatności nie audytuje. Obejrzałem sześć stron wyrenderowanych przez Qt offscreen i wykonałem dodatkowe próby z sekcji 15.

Nie zmieniano implementacji ani profilu użytkownika, nie wykonywano komend sterujących sprzętem, nie restartowano HA/brokera. Nie wykonano testu na pełnym serwerze HA, wielogodzinnego soak testu, instalacji ani fizycznej macierzy DWM/sleep/DPI. Historyczne wyniki zapisane w repozytorium nie są nowymi pomiarami tego audytu.

## 2. Current architecture

### Przepływ danych

~~~mermaid
flowchart TB
  Entry[desktop.main / main.py / python -m] --> App[Application]
  Entry --> Qt[QApplication + DesktopWindow + tray]
  Entry --> Overlay[OverlayService]
  Entry --> Native[WindowsEventBridge]
  App --> Sup[ServiceSupervisor]
  App --> Router[CommandRouter + SerialWorker]
  Sup --> MQTT[MqttGateway / MqttTransport]
  Sup --> Direct[HomeAssistantGateway / WebSocket]
  Sup --> Sensors[TelemetryService + PollScheduler]
  Sensors --> Win[Audio / SystemMonitor / Media]
  Sensors --> Publisher[StatePublisher]
  Publisher --> MQTT
  MQTT <--> Broker[MQTT broker]
  Broker <--> HA[HA custom integration]
  Direct <--> HA
  MQTT --> Router
  Direct --> Router
  Router --> Commands[WindowsCommands]
  Commands --> Win
  Commands --> Events[EventBus]
  Sensors --> Events
  Native --> Events
  Events --> Qt
  Events --> Overlay
  Overlay --> Engine[NotificationEngine + PlacementEngine]
  Overlay --> Windows[NotificationWindow]
  Overlay --> Glass[GlassRenderer + DXGI]
~~~

MQTT przenosi sensory, audio, sterowanie komputerem i nakładki. Direct jest wychodzącym połączeniem Windows → API WebSocket HA i przenosi **wyłącznie nakładki**. Nie stanowi alternatywy telemetrii. HA może wybrać Direct dla popupu wpisu odkrytego przez MQTT; pozostałe komendy pozostają na MQTT.

Sensory: Windows → adapter → TelemetryService → formatowanie tematów/payloadów HA → StatePublisher → MQTT → platformy integracji. Komendy: akcja/encja HA → envelope v2 albo adapter legacy → transport Windows → router/uprawnienia → adapter Windows. Dla popupu wykonanie przechodzi przez EventBus i kolejkę Qt.

### Ownership, wątki, timery i lifecycle

| Właściciel | Zasób | Start / stop | Ocena |
| --- | --- | --- | --- |
| desktop.main | QApplication, mutex, okno, overlay, native bridge, Application | Tworzenie sekwencyjne; cleanup po exec() | Jasny composition root; brak jednego try/finally dla częściowego startupu i zamknięcia sesji. |
| Application | _operations, kolejka 64 | SerialWorker lifecycle; close 4 s | Start/stop/save współdzieli kolejkę z odczytem podglądu mediów. |
| Application | _queries, kolejka 8 | Inwentarz dysków, urządzeń, aplikacji; close 4 s | Jest scalanie powtórzonych skanów; adaptery współdzielone z innymi wątkami. |
| CommandRouter | bridge-commands, kolejka 64 | Budowany razem z usługami; stop usuwa oczekujące zadania | Dobra granica wykonywania; transporty kończą pracę przed routerem. |
| ServiceSupervisor | Rejestr usług i zależności | Topologiczny start, odwrotny stop | RUNNING oznacza zakończenie start(), nie zdrową sieć lub sensor. |
| MqttTransport | Własny wątek Paho | connect/loop/retry; join 4 s | OS poza callbackiem sieci; emisja pod lockiem prowadzi do C01. |
| HomeAssistantTransport | Wątek WebSocket i socket | Handshake 3 s, recv 1 s; close socket i join 4 s | Wartościowe epoch, heartbeat i rozróżnienie błędów. |
| TelemetryService | Jeden daemon sensor-scheduler | Tylko przy skonfigurowanym MQTT; join 3 s | Blokujący provider wstrzymuje następne odczyty. |
| WindowsMediaService | Leniwa pętla asyncio i wątek | reopen/close, cancel zadań, join 1 s | Brak propagacji nieudanego zakończenia. |
| WindowsSystemMonitor | Daemon Windows Update | Uruchamiany przy odczycie health | Brak zarejestrowanego właściciela stopu synchronicznego WUA. |
| DesktopWindow | Timer aktywnej strony, tray, subskrypcja * | Timer stop przy hide/dispose | Dobre ograniczenie odświeżania widoku; ukryte karty nadal dostają aktualizacje. |
| OverlayService | Timer 50/500 ms, media 500 ms, okna, QScreen | Qt GUI, clear/dispose/close | Nie każdy wynik silnika wraca do nadawcy. |
| GlassRenderer | Timer 250/500/750 ms, worker kolejka 2 | Aktywny dla kart z efektem; bounded release/close | Niepełny cleanup nie jest propagowany do Application. |
| HA entry.runtime_data | Do 64 pending futures, lease Direct, MQTT results | Setup/unload | Właściwy punkt ownership; regresje są w platformach encji. |

Start: profil → DPAPI → mutex → obiekty Windows/Qt → router/usługi → opcjonalna sieć. Stop z GUI przechodzi przez worker lifecycle. Zakończenie Qt zamyka native/overlay/GUI, potem Application. Jeżeli workery nie kończą pracy, shutdown może wrócić przed zatrzymaniem wszystkich usług. Odmowa ponownego startu niedomkniętej usługi jest słuszna, lecz nie zastępuje kompletnego shutdownu.

### Sprzężenia i wymieszane odpowiedzialności

- **Telemetria zna MQTT i schemat HA.** publish_discovery() odczytuje Windows, wylicza capabilities z pomiarów i buduje inventory. Chwilowy błąd sprzętu może prowadzić do reloadu i usunięcia encji. Rozdzielić capability catalog, próbki i projekcję HA.
- **GUI ma drugą drogę odczytu audio.** Widoczna strona aplikacji korzysta z inwentarza lokalnego i odrzuca audio.snapshot; ukryte karty aktualizuje telemetria. Jeden snapshot powinien zasilać GUI i HA.
- **system_monitor.py miesza domeny.** Kontekst pulpitu, WMI, WUA, PnP, dyski, GPU, identyfikacja, ShellExecute i zamykanie aplikacji mają różne wymagania wątkowe i timeouty. Problemem jest izolacja, nie sama długość 970 linii.
- **ui/shell.py miesza formularze i zachowanie.** Buduje strony, importuje profile, skanuje aplikacje, obsługuje komendy, tray, logi i sieć. Wyodrębnienie stron umożliwi test workflow bez całego formularza.
- **overlays/presentation.py miesza przygotowanie contentu, QR, layout, natywne okno, animację i efekty.** Zmiana tła wpływa na lifecycle i pierwszą klatkę. Rozdzielić przygotowany content, widget i backend efektu.
- **HA __init__.py łączy setup z rozbudowaną akcją.** Źródła encji, uprawnienia, HTTP obrazów, normalizacja i fan-out powinny być osobnymi funkcjami/modułami.
- **Odwrócone zależności.** WindowsCommands importuje walidator z communication.protocol; core.configuration korzysta ze starego config.py; snapshoty domenowe leżą w adapterach. Przenieść współdzielone typy i walidację na dół zależności.

Statyczny graf 85 modułów ma 132 wewnętrzne krawędzie i **nie wykazał cykli importów**. Cykle wywołań i locków nadal istnieją — C01 jest przykładem. Globalne QApplication properties i aktywny język tworzą niejawny kontekst; logger i cache DXcam wymagają jawnego lifecycle. Stałe modułowe same w sobie nie są problemem.


## 3. Critical findings

Priorytety oznaczają wpływ na wydanie produktu, nie CVSS. Critical dotyczy niezawodności. **Nie potwierdzono krytycznego zdalnego wykonania dowolnego kodu.** „Odtworzone” oznacza próbę na rzeczywistym kodzie z kontrolowanymi atrapami albo wskazany odczyt Windows. „Analiza” oznacza ustaloną ścieżkę bez pełnego odtworzenia środowiska.

### Critical

**C01 — zakleszczenie MQTT na reconnect. Odtworzone; blokuje wydanie.**

[[ha_windows_bridge/communication/state.py:48]], [[ha_windows_bridge/communication/state.py:78]], [[ha_windows_bridge/communication/gateway.py:32]], [[ha_windows_bridge/communication/publishing.py:19]].

Wątek publikujący trzyma lock StatePublisher i w transport.connected czeka na lock ConnectionMachine. Wątek sieci trzyma lock ConnectionMachine, synchronicznie emituje connection.changed, a callback publisher.replay() czeka na lock publikacji. Bariera w próbie wymusiła ten splot: oba wątki pozostały zablokowane na wskazanych liniach, bez brokera i bez operacji Windows.

Skutek: transport i telemetria mogą stanąć do restartu; odczyt statusu lub stop również może utknąć. Naprawa: aktualizacja stanu pod lockiem, emisja **po zwolnieniu**; snapshot cache pod lockiem, I/O poza nim. Replay jako zadanie właściciela publikacji. Regresja z dwoma rzeczywistymi wątkami i kontrolowanym harmonogramem.

### High

| ID / dowód | Problem i konsekwencja | Naprawa |
| --- | --- | --- |
| **H01 — odtworzone**. [[ha_windows_bridge/application/telemetry.py:268]], [[ha_windows_bridge/communication/publishing.py:19]] | _last_master_volume i analogiczne cache aktualizują się niezależnie od sukcesu publikacji. Próba: wysłano 20%, odczytano 80%, publikacja zawiodła; reconnect odtworzył 20%, stabilne 80% nie zostało ponowione. | Cache ostatniego zaobserwowanego stanu oraz osobne dirty/delivery. Pełny snapshot nowej sesji; porównanie wartości nie jest dowodem dostarczenia. |
| **H02 — odtworzone**. [[custom_components/ha_windows_bridge/media_player.py:77]], [[custom_components/ha_windows_bridge/entity.py:64]] | HAWindowsAppVolumePlayer używa nieistniejącego _unsubscribers. AttributeError występuje przed subskrypcjami głośności/mute; odtwarzacz aplikacji nie kończy setupu. | Każdy cleanup natychmiast w async_on_remove. Test rzeczywistej platformy HA. |
| **H03 — odczyt Windows + analiza**. [[ha_windows_bridge/system_monitor.py:371]], [[ha_windows_bridge/system_monitor.py:416]], [[ha_windows_bridge/system_monitor.py:682]], [[ha_windows_bridge/system_monitor.py:877]] | WMI nie inicjalizuje COM dla wykonującego je workera. Probe w nowym wątku bez CoInitialize dał com_error; identyczny odczyt z inicjalizacją zwrócił dane. Puste wyniki mogą być mylone z brakiem sprzętu i utrwalone w cache. | Własny wątek/apartment providera, jawne CoInitializeEx/CoUninitialize, unavailable zamiast pustego „sukcesu”. [Wymagania COM](https://learn.microsoft.com/en-us/windows/win32/learnwin32/initializing-the-com-library). |
| **H04 — analiza**. [[ha_windows_bridge/application/telemetry.py:232]], [[ha_windows_bridge/application/application.py:280]], [[ha_windows_bridge/media.py:175]], [[ha_windows_bridge/system_monitor.py:600]] | Izolacja wyjątków nie izoluje zawieszenia. Jeden scheduler wykonuje blokujące odczyty; WUA i media mogą nie skończyć w budżecie; część close nie zwraca wyniku. Nie potwierdzono wycieku ilościowo. | Osobny wolny provider, kontrolowany właściciel WinRT, cancellation/deadline i kompletny raport stopu. Helper process tylko dla potwierdzonego nieanulowalnego API. |
| **H05 — oficjalne źródła**. [[hacs.json:2]], [[custom_components/ha_windows_bridge/__init__.py:22]] | Minimum HA 2025.1.0 jest nieprawdziwe: helpers.target nie istnieje w tym tagu. Import integracji może zawieść przed config flow. Testy AST pomijają importy. | Rzeczywiste minimum i testy Linux/HA dla minimum oraz aktualnej wersji. [HA 2025.1 helpers](https://github.com/home-assistant/core/tree/2025.1.0/homeassistant/helpers), [API 2026.9.1](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/helpers/target.py). |
| **H06 — analiza przepływu**. [[ha_windows_bridge/application/telemetry.py:142]], [[custom_components/ha_windows_bridge/config_flow.py:40]], [[custom_components/ha_windows_bridge/__init__.py:501]] | Inventory zależy od udanych opcjonalnych pomiarów. Reload usuwa z registry każdy brakujący unique_id. Chwilowy błąd może usunąć encję i ustawienia użytkownika. | Capabilities oddzielone od health. Brak próbki → unavailable; usuwanie wyłącznie przez jawne wycofanie capability/migrację. |
| **H07 — kod + Microsoft**. [[ha_windows_bridge/system_actions.py:55]] | Shutdown/restart używa /t 30. Dodatni timeout oznacza domyślne /f, czyli możliwość zamknięcia aplikacji z utratą niezapisanych danych. Jedna ogólna zgoda obejmuje wszystkie akcje. | Osobne uprawnienia i jawny tryb wymuszony. Lokalny etap odliczania z anulowaniem; sprawdzona semantyka bezpiecznego zamknięcia. Nie wykonywano tej operacji w audycie. [shutdown](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shutdown). |
| **H08 — analiza + kontrakt testów**. [[ha_windows_bridge/application/windows_commands.py:112]], [[ha_windows_bridge/overlays/service.py:47]], [[ha_windows_bridge/overlays/engine.py:27]] | Sukces popupu wraca przed wynikiem queue_full/not_found/model error. queued_for_presentation uczciwie ogranicza ACK, ale HA nie otrzymuje wyniku przyjęcia przez silnik. Kolejka Qt nie ma limitu odpowiadającego limitowi 32 kart. | Walidacja i bounded inbox przed Qt; accepted/queued/rejected z silnika, późniejszy event displayed/closed. Bez obietnicy „użytkownik przeczytał”. |
| **H09 — odtworzone**. [[ha_windows_bridge/application/application.py:165]] | Po skutecznym zapisie profilu błąd startup.set_enabled zostawia nowy plik, stary obiekt config i zatrzymane usługi. Rollback obejmuje tylko store.save. | Transakcja konfiguracji z rollbackiem albo niezależny błąd autostartu bez zatrzymania usług. Test każdego etapu apply. |

### Medium

| ID / miejsce | Problem i konsekwencja | Naprawa |
| --- | --- | --- |
| **M01 — odtworzone**. [[ha_windows_bridge/application/telemetry.py:557]] | Zmiana listy wyjść audio wywołuje nieistniejące _publish_discovery(). Lista została już zmieniona, więc następny cykl może nie ponowić inventory. | Poprawna ścieżka zgłoszenia capabilities; test pierwszego wykrycia i hotplug. |
| **M02 — odtworzone na Windows**. [[ha_windows_bridge/system_monitor.py:380]] | SELECT HealthStatus,Temperature FROM MSFT_PhysicalDisk jest nieprawidłowe. HealthStatus zwrócił 4 wiersze; wariant z Temperature — Invalid query. Legacy SMART nie zapewnia zastępstwa dla wszystkich NVMe. | Health z PhysicalDisk, temperatura z właściwego reliability counter i mapowaniem dysku. [Właściwości klasy](https://learn.microsoft.com/en-us/windows-hardware/drivers/storage/msft-physicaldisk). |
| **M03 — kod + NVIDIA**. [[ha_windows_bridge/system_monitor.py:839]], [[ha_windows_bridge/system_monitor.py:861]] | fan.speed jest procentem sterowania wentylatorem; kod i HA traktują go jako rpm. Test utrwala błąd sztuczną wartością 1450. | Metryka w %, RPM tylko z rzeczywistego źródła RPM. Jawna migracja jednostki i historii. [NVIDIA SMI](https://docs.nvidia.com/deploy/nvidia-smi/index.html#fan-speed). |
| **M04 — odtworzone**. [[ha_windows_bridge/core/configuration.py:46]], [[custom_components/ha_windows_bridge/announcement.py:207]] | Konfiguracja dopuszcza 256 aplikacji, UI 128, HA tylko 256 encji. 63 aplikacje → 255 encji: działa; 64 → 259: całe inventory odrzucone. Inne funkcje obniżają próg. | Jeden budżet capabilities/payload i walidacja przed zapisem. |
| **M05 — analiza**. [[custom_components/ha_windows_bridge/entity.py:109]], [[custom_components/ha_windows_bridge/notify.py:78]], [[ha_windows_bridge/application/telemetry.py:102]] | Availability ignoruje wiek próbek i pauzę sensorów. Windows balloon notify może być dostępne dzięki Direct, choć Direct nie przenosi tej komendy. | Dostępność per capability/transport; stale/paused/unavailable z czasem ostatniego odczytu. |
| **M06 — odtworzone**. [[custom_components/ha_windows_bridge/__init__.py:453]], [[ha_windows_bridge/overlays/engine.py:27]] | update_overlay samego progress wysyła puste title/message. Próba progress=65 usunęła message i przywróciła domyślny tytuł. | PATCH: brak pola zachowuje wartość, jawne clear usuwa; świadome odnawianie TTL. |
| **M07 — zagrożenie warunkowe**. [[custom_components/ha_windows_bridge/__init__.py:198]] | image_url inicjuje dowolne HTTP(S) z sieci HA, także z redirectami. Prawo sterowania popupem daje możliwość żądań do adresów osiągalnych przez HA. Nie wykazano kradzieży tokenu ani odczytu dowolnej odpowiedzi. | Domyślnie camera/image z ACL; zewnętrzne URL przez allowlistę originów, walidację redirectów/DNS i limity. |
| **M08 — analiza**. [[ha_windows_bridge/ui/shell.py:478]], [[ha_windows_bridge/communication/home_assistant.py:117]] | Import zachowuje sekret przy tym samym serwerze, ignorując zmianę TLS/verify_tls. Może osłabić ochronę istniejących poświadczeń. | Porównywać cały profil zaufania. Osłabienie TLS jako jawna operacja. |
| **M09 — odtworzony zły typ**. [[custom_components/ha_windows_bridge/announcement.py:103]] | platform=[] podnosi TypeError zamiast kontrolowanego odrzucenia. Parsery różnią się tolerancją i limitami. | Typ przed membership; wspólny corpus błędnych payloadów, limit głębokości i spójna walidacja. |
| **M10 — zagrożenie warunkowe**. [[custom_components/ha_windows_bridge/announcement.py:199]], [[custom_components/ha_windows_bridge/config_flow.py:40]] | Prefiks sprawdzany względem pola tego samego niezaufanego announcement zapewnia spójność, nie tożsamość. Klient mogący pisać discovery może podszyć się pod ID. | ACL per urządzenie; związanie discovery topic/device_id/prefiksu z zaakceptowaną tożsamością. |


| **M11 — analiza**. [[ha_windows_bridge/application/application.py:262]], [[ha_windows_bridge/core/observability.py:10]] | Diagnostyka Windows usuwa tokeny/hasła, ale pozostawia hosty, MQTT user, tematy, ścieżki i identyfikatory. Główny log jest w pamięci, więc crash odbiera kontekst. | Eksport przez allowlistę pól, pseudonimizacja; mały rotowany dziennik bez prywatnej treści. |
| **M12 — analiza**. [[ha_windows_bridge/communication/mqtt.py:45]], [[ha_windows_bridge/communication/mqtt.py:65]] | Brak jawnego limitu outgoing Paho, sprawdzenia SUBACK i potwierdzenia offline przy stop. Sukces publish nie dowodzi dostarczenia. | Bounded outbox, kontrola ACK/subskrypcji, flush z deadline. [Paho](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html). |
| **M13 — analiza**. [[ha_windows_bridge/communication/protocol.py:96]] | Legacy tworzy nowe ID/czas przy każdym odbiorze. Powtórzona stara komenda omija dedup/TTL end-to-end. | Wycofać legacy komendy skutkowe, z krótką kontrolowaną migracją. |
| **M14 — analiza**. [[ha_windows_bridge/overlays/glass.py:36]], [[ha_windows_bridge/windows/capture.py:73]], [[ha_windows_bridge/overlays/service.py:180]] | Szkło zależy od capture, prywatnych szczegółów DXcam i topologii ekranów; cleanup nie ma pełnego raportu. Wybór monitora ma indeksową tożsamość. | Opcjonalny backend, natychmiastowy fallback, stabilne ID ekranów i jawny lifecycle zasobów. |
| **M15 — odtworzone**. [[ha_windows_bridge/ui_components.py:544]] | Strzałka klawiatury zmienia suwak 50 → 51, ale nie emituje volume_requested. Akcja jest podpięta pod sliderReleased myszy. | Wspólny commit wartości dla myszy, klawiatury i accessibility; aktualizacja snapshotu bez komendy. |
| **M16 — kod + HA Core**. [[custom_components/ha_windows_bridge/sensor.py:36]] | Tekst przycinany do 1024 znaków przekracza limit stanu HA 255. Długi tytuł okna może zablokować zapis. | Stan ≤255; pełna treść tylko jako świadomie włączony atrybut albo pomijana. [HA const](https://github.com/home-assistant/core/blob/2026.9.1/homeassistant/const.py#L61). |
| **M17 — analiza**. [[ha_windows_bridge/media.py:255]], [[ha_windows_bridge/audio.py:146]], [[ha_windows_bridge/system_monitor.py:777]] | Media trafiają do aktualnej sesji w chwili wykonania; audio/process close używa basename. Zmiana sesji lub dwa identyczne basename osłabiają pewność celu. | Session/endpoint/app identity i rewizja; odrzucić komendę do nieaktualnego celu. |
| **M18 — metadane**. [[pyproject.toml:9]], [[constraints.txt:5]] | Deklarowane Python ≥3.11 koliduje z NumPy 2.5.2 w constraints, wymagającym ≥3.12. CI testuje tylko 3.13. | Ujednolicić minimum, constraints i macierz; nie deklarować nieweryfikowanego wsparcia. |
| **M19 — analiza**. [[custom_components/ha_windows_bridge/media_player.py:174]] | Aktywny media player dopisuje cleanup dopiero po całej krotce await. Awaria kolejnej subskrypcji może pozostawić pierwszą bez cleanup. | Natychmiastowe async_on_remove i test każdego punktu częściowego setupu. |
| **M20 — analiza**. [[custom_components/ha_windows_bridge/__init__.py:218]] | Jedno StreamReader.read(n) może zwrócić mniej danych przed EOF. Poprawny obraz nadsyłany porcjami może być ucięty. | Czytać porcjami do EOF z limitem całkowitym i timeoutem. [aiohttp StreamReader](https://docs.aiohttp.org/en/stable/streams.html#aiohttp.StreamReader.read). |

### Low

| ID / miejsce | Problem i konsekwencja | Naprawa |
| --- | --- | --- |
| **L01 — odtworzone**. [[ha_windows_bridge/updater.py:24]] | Porównanie major/minor/patch nie wykrywa alpha.8 → stable 2.0.0. Brak modelu kanałów. | Prawidłowa kolejność wersji, stable/preview i link do zweryfikowanego wydania. |
| **L02**. [[ha_windows_bridge/ui/shell.py:568]], [[ha_windows_bridge/ui_components.py:535]] | Wszystkie zdarzenia trafiają do GUI/overlay; ukryte karty wykonują aktualizacje i polish. | Tematyczne subskrypcje, scalanie snapshotów, aktualizacje tylko zmienionych widoków. |
| **L03**. [[ha_windows_bridge/ui/motion.py:14]], [[ha_windows_bridge/overlays/presentation.py:373]] | Motion tokens nie są jedynym źródłem czasu/dystansu; exit odbiega od deklaracji. | Jeden MotionPolicy i Reduced Motion; szczegóły w sekcji 8. |
| **L04**. [[installer/HAWindowsBridge.iss:52]], [[ha_windows_bridge/startup.py:16]] | Runtime usuwany przed kopiowaniem; brak jawnego cleanup własnego Run przy uninstall; kilka skryptów pakowania i rozjechane metadane. | Jedna ścieżka release; test upgrade/uninstall/rollback i czyste środowisko danego commita. |
| **L05**. [[docs/V2_QUICKSTART.md:7]], [[docs/V2_REBUILD.md:1]] | Historyczne opisy alpha mają sprzeczne deklaracje szkła/wersji. Pozostały nieużywane klasy UI, stary SettingsStore i trzy pliki wyjścia terminala. | Oznaczyć historię i aktualne źródło prawdy; usuwać martwy kod po ustaleniu migracji. |

Nie każdy problem wymaga nowego managera. C01 wymaga porządku locków; H02/M01 są małymi regresjami. Głęboka wymiana dotyczy błędnych kontraktów: stan/dostarczenie, capabilities/health, ownership i potwierdzenie prezentacji.

## 4. KEEP / REFACTOR / REPLACE / REWRITE matrix

KEEP oznacza zachowanie pomysłu i głównej implementacji z testami; REFACTOR — zachowanie modelu przy zmianie granic; REPLACE — zastąpienie rozwiązania innym mechanizmem; REWRITE — ponowne napisanie warstwy przy zachowaniu funkcji produktu. Oceny są jakościowe, nie sztuczną punktacją.

| Subsystem | Ocena | Decyzja | Problem | Rozwiązanie | Priorytet |
| --- | --- | --- | --- | --- | --- |
| Application core | Dobry początek, niepełne gwarancje | REFACTOR | Lifecycle i podgląd mediów dzielą kolejkę; stop/config transakcje | Jeden właściciel cyklu życia, osobne I/O i raport stopu | P0 |
| GUI | Czytelne, mocno formularzowe | REWRITE warstwy stron; KEEP Qt | Przegląd jako formularz, brak stanu capability/dirty | Nowy workflow i wspólny read model | P2 |
| Overlay | Dobry model kolejki; krucha prezentacja | KEEP engine/placement, REWRITE host/render pipeline | Dostarczenie, efekty, za dużo ról widgetu | Bounded inbox, content preparation, wynik silnika | P1 |
| Motion | Dobre intencje, częściowe wdrożenie | REFACTOR | Rozproszone stałe i brak wspólnej polityki | Jeden MotionPolicy, preferencje Windows | P2 |
| MQTT | Właściwa biblioteka, błędny ownership publikacji | REFACTOR transport; REPLACE publisher | C01, brak dirty/snapshot/ACK | Właściciel outboxu i kontrakt synchronizacji | P0 |
| Direct HA | Wąski, przydatny kanał | REFACTOR | Osobny adapter i konfiguracja, zależność od overlay | Wspólne wiadomości/polityka routingu | P1 |
| Protocol | Dobra baza komend v2 | REPLACE kontrakt inventory/state, REFACTOR komendy | Legacy i route tables, brak session/sequence | Jeden protokół domenowy z capabilities | P1 |
| HA integration | Dobre API setup, istotne regresje | REWRITE runtime projekcji/platform; KEEP małe parsery po poprawkach | Registry deletion, platform setup, min version | Typowany runtime, kontrakt testowany na HA | P0/P1 |
| Configuration | Dobry zapis atomowy, słaba transakcja | REFACTOR | Profil2 + legacy15, brak migracji użytkownika | Jeden schemat, walidacja pełnego snapshotu, rollback | P0/P1 |
| Secrets | Właściwa granica lokalna | KEEP | DPAPI nie chroni przed procesem tego samego usera | Utrzymać, powiązać trust profile i redact | P1 |
| System monitor | Najsłabsza spójność i izolacja | REWRITE orchestration; KEEP wybrane odczyty | WMI/COM, WUA, błędne units/query | Kilka małych providerów z health i ownerem | P0/P1 |
| Audio | Wartościowa implementacja domeny Windows | REFACTOR | Polling, basename, brak stable endpoint target | COM owner + callbacki + resync | P1 |
| Media | Dobry snapshot/artwork split | REFACTOR | Polling podwójny, cel current session, stop | Właściciel WinRT, zdarzenia, session ID | P1 |
| Windows integration | Właściwy native shell | REFACTOR | Brak sieci/PnP/end-session, statyczne monitory | Jedno źródło zdarzeń Windows, feature gates | P1 |
| Tray | Użyteczny | KEEP + REFACTOR | Zależny od okna, mało recovery i feedback | TrayController nad Application state | P2 |
| Logging | Redaktor dobry, ślad awarii za krótki | REPLACE pipeline, KEEP redact | Pamięć i niepełne namespaces | Rotacja, zdarzenia strukturalne, health transitions | P1 |
| Diagnostics | HA lepsze niż Windows | REFACTOR | Dane prywatne, brak freshness/latency | Jawny publiczny schema eksportu i preview | P1 |
| Tests | Dobra logika, słabe granice integracji | KEEP wartościowe, REPLACE atrapy krytycznych granic | H02/H05 przechodzą 274 testy | Real HA, broker harness, fault/soak | P0 |
| Build/dependencies | Powtarzalny częściowo | REFACTOR | Luźne deklaracje, stare metadata, kilka packaging paths | Jeden release manifest, czysty build, podpis i smoke | P1/P2 |

### Inventory funkcji produktu, niezależne od aktualnego kodu

| Funkcja | Wartość / jakość projektu funkcji | Ograniczenie | Implementacja |
| --- | --- | --- | --- |
| CPU/RAM/frequency | Podstawowa, potrzebna telemetria | Brak health per sensor i runtime preview | REFACTOR |
| GPU/temp/power/fan | Wartościowa opcjonalnie | Różne źródła/vendorzy, błędne jednostki, pierwszy GPU | REPLACE orkiestrację |
| Dyski per wolumin, transfer, health | Dobre rozdzielenie woluminu i globalnego I/O | Niedostępny WMI, błędne Temperature; brak mapowania physical→volume | REFACTOR |
| Windows health, bateria, zasilanie, uptime, update | Przydatne automatyzacjom | WUA potencjalnie blokuje; „brak danych” nie jest stanem | REPLACE provider health |
| Active app/window, idle, lock/fullscreen | Silny wyróżnik Windows + HA | Wysoka prywatność tytułów, limit HA 255 | REFACTOR, opt-in |
| PnP/USB/BT obecność | Przydatne dla stanowiska, kontrolerów, docka | Heurystyki nazw, utrata duplikatów, polling | REPLACE identyfikację/event source |
| Running process i liczba sesji audio | Dobre dla HA | Basename i globalne enumeracje | REFACTOR |
| Master volume/mute/balance | Właściwa funkcja i zakres | Brak eventowej obserwacji, różne dostępności kanałów | REFACTOR |
| Volume/mute per aplikacja | Bardzo wartościowe | Jedna nazwa wielu sesji; HA player ma regresję | REFACTOR + naprawa |
| Głośność aktywnej aplikacji | Użyteczna, ale cel ruchomy | Zmiana focusu przed wykonaniem | REFACTOR, target revision |
| Mikrofon volume/mute/sygnał | Przydatne | Sygnał powyżej progu nie oznacza „mikrofon używany” | REFACTOR i poprawne nazewnictwo |
| Wybór wyjścia audio | Wartościowy | Friendly name nie jest jednoznacznym endpoint ID | REPLACE kontrakt celu |
| GSMTC active media / artwork / play/pause/seek | Wyróżnik produktu | Tylko aplikacje wystawiające GSMTC, current session | REFACTOR |
| Start/close dozwolonej aplikacji | Sensowne ograniczenie | EXE basename, heurystyka Store AUMID | REFACTOR, stała allowlista |
| Lock/sleep/hibernate/shutdown/restart/cancel | Potrzebne automatyzacjom | Uprawnienia zbyt zbiorcze, H07 | REPLACE politykę |
| Natywne powiadomienie Windows | Wartość jako spokojny kanał | Tray balloon bez trwałej historii i activation actions | REPLACE docelowo Windows toast |
| Text/status/badge overlay | Dobra funkcja | Część layoutów różni się niewiele; badge pomija image/progress | KEEP engine, REWRITE prezentację |
| Progress / pinned / update / remove / clear | Bardzo dobry model automatyzacji | PATCH i wynik przyjęcia niepełne | REFACTOR |
| Windows media overlay live | Wartościowe, działa osobny timer i interpolacja | Ponowne polling GSMTC, brak session target | REFACTOR |
| HA media overlay | Użyteczne jako prezentacja | Snapshot, nie automatyczna subskrypcja stanu HA | REFACTOR + jasno opisać |
| Camera/image/QR | Przydatne dla dzwonka, alarmu, informacji | Kamera jest klatką, URL-fetch ma granicę sieciową | REFACTOR |
| Multi-monitor, queue/parallel/priority | Dobra logika geometryczna | Indeks monitora, deferred cards, brak feedbacku | KEEP placement/queue + rozszerzyć kontrakt |
| Blur/liquid | Opcjonalny polish | Capture i koszt pamięci/energii, RDP/HDR/driver | REPLACE domyślną politykę; eksperyment opt-in |
| MQTT discovery/custom HA actions | Ważna integracja | Za dużo encji i route metadata, brak spójnego health | REPLACE kontrakt |
| Direct overlay | Użyteczne bez brokera dla samych popupów | Nie obsługuje sensorów | REFACTOR, jawna macierz funkcji |
| Tray/autostart/single instance | Właściwe zachowanie desktop agent | Brak aktywacji istniejącego okna, uninstall Run | KEEP/REFACTOR |
| Import/export/reset/update/diagnostics | Podstawowe operacje produktu | Migracja starego profilu, trust, SemVer, recovery | REFACTOR |
| PL/EN | Wartościowe | Nowy shell jest PL; stary słownik nie daje pełnego EN | REPLACE pozostałości jednolitą lokalizacją |

Zachowałbym funkcje, ale ograniczył liczbę reprezentacji w HA: pojedynczy media_player per aplikacja już ma volume/mute; dodatkowe number/switch są opcjonalnymi encjami zaawansowanymi, zamiast obowiązkowym potrajaniem tego samego sterowania.


## 5. Proposed HA Windows Bridge 2.0 architecture

**Jeden proces użytkownika, jedno źródło stanu i jawni właściciele I/O.** GUI pozostaje PySide6/Qt Widgets. Nie dodawałbym kontenera DI, bazy danych, wewnętrznego HTTP, mikroserwisów ani osobnego Windows Service do obsługi interaktywnego pulpitu.

~~~mermaid
flowchart LR
  Windows[Windows APIs] --> Providers[Audio / Media / System providers]
  Providers --> Store[ComputerState + CapabilityCatalog]
  Store --> UI[Qt views]
  Store --> Projection[HA projection + state outbox]
  Projection --> MQTT[MQTT adapter]
  Projection --> WS[Direct adapter: zadeklarowane capabilities]
  MQTT --> Commands[CommandDispatcher + policy]
  WS --> Commands
  UI --> Commands
  Commands --> Providers
  Commands --> Notifications[NotificationEngine]
  Notifications --> Host[Qt notification host]
  Host --> Results[Delivery and lifecycle events]
~~~

### Najważniejsze typy i odpowiedzialności

| Typ | Odpowiedzialność | Czego nie powinien robić |
| --- | --- | --- |
| Application | Tworzenie, start/stop, apply config, desired state, koalescencja reconnect | Czytać WMI/GSMTC w kolejce lifecycle |
| ComputerState | Immutable snapshot, revision, timestamp, jakość próbki | Formatować tematy MQTT lub tworzyć QWidget |
| CapabilityCatalog | Stabilna lista możliwości i ich tożsamości | Usuwać capability po pojedynczym błędzie odczytu |
| CommandDispatcher | Walidacja, policy, ID/dedup/TTL, wybór właściciela, wynik | Wykonywać blokujące API na wątku sieci lub GUI |
| AudioService / MediaService / SystemSampler | Właściciele API i zasobów, odczyty/komendy, zdrowie źródła | Znać encje HA |
| StateOutbox | Snapshot bieżącej sesji, dirty state, ograniczenie bufora, delivery | Być drugim niezależnym cache „prawdy” Windows |
| MqttAdapter / DirectAdapter | Ramki, handshake, sieć, konkretne ACK transportu | Zawierać politykę zasilania, model GUI lub discovery Windows |
| NotificationEngine + QtNotificationHost | Engine: stan/kolejka/limity. Host: render i lifecycle okien | Ukrywać odrzucenia za sukcesem komendy |
| ConfigurationStore + SecretStore | Walidacja/migracja/zapis i DPAPI | Samodzielnie restartować usługi |
| HA BridgeRuntime | Projekcja capabilities/stanu na encje, futures komend | Wyciągać z pojedynczej próby sensora wniosek o usunięciu encji |

ComputerState i CapabilityCatalog mogą początkowo być dwoma dataclass i jednym store, a StateOutbox jednym niedużym modułem. Nie wymagają hierarchii repozytoriów i fabryk.

**Kierunek zależności:** domain/contract → stdlib; application → domain oraz wąskie porty; Windows/network/storage → realizacja tych portów; Qt → application/domain. Tylko bootstrap zna konkretne adaptery. UI ma polecenia użytkownika i modele widoku; zmiany Windows przechodzą tą samą drogą co komendy HA.

### Wątki i przekazywanie danych

- GUI: wyłącznie Qt, snapshoty i lekki rendering.
- Kolejka sterowania lifecycle: krótka, scalająca start/stop/reconnect; bez oczekiwania na media.
- Audio: jeden właściciel COM, jawnie dobrany apartment i wymagane pompowanie komunikatów. Callback kopiuje proste dane i kończy się szybko.
- Media: jedna pętla WinRT/asyncio z tokenami subskrypcji; bez drugiego odczytu dla overlay.
- System: harmonogram lekkich metryk i ograniczony wykonawca wolnych zapytań WMI. Wolny wynik nie blokuje audio/komend/GUI.
- Sieć: po jednym właścicielu transportu zgodnie z używaną biblioteką. Nie wymuszać wspólnej pętli asyncio tylko dla jednolitego wyglądu kodu.
- Capture: tworzony wyłącznie, gdy aktywny eksperymentalny efekt wymaga przechwytywania.

Wiadomości pomiędzy wątkami są immutable, z generation/session i ograniczonym rozmiarem. Kanał stanu przechowuje **najnowszą wartość**, nie każdą próbkę. Kanał komend zachowuje kolejność i jawnie odrzuca overflow. Callbacków nie wywołuje się pod lockiem danych. Subskrypcje tematyczne zastępują globalne „*” tam, gdzie UI potrzebuje tylko jednego typu zdarzenia.

### Startup i shutdown

Startup: (1) mutex i możliwość aktywacji istniejącego okna; (2) odczyt profilu i recovery; (3) walidacja pełnego profilu/sekretów; (4) stan aplikacji i GUI/tray; (5) tylko potrzebni providerzy; (6) snapshot capabilities; (7) transporty; (8) handshake/snapshot; (9) gotowość poszczególnych funkcji. Lokalny podgląd działa również bez brokera.

Shutdown: (1) desired=stopped i nowa generation; (2) odrzucenie nowego ingress; (3) anulowanie oczekujących komend/prac; (4) zakończenie bieżących komend w deadline; (5) terminalne wyniki, offline i ograniczony flush; (6) stop transportów; (7) unsubscribe Windows, zamknięcie COM/WinRT/capture przez właścicieli; (8) zamknięcie timerów/okien; (9) flush logu i release mutex. Każdy etap wykonuje swój cleanup również po błędzie poprzedniego. Raport końcowy wskazuje niezamknięty owner, bez udawania sukcesu.

**Sleep** jest przejściem sesji: zatrzymanie producentów, invalidacja przechwytywania i anulowanie nieaktualnych żądań. **Resume** tworzy nową sesję protokołu, resync sprzętu i snapshot; nie odtwarza starych komend skutkowych. Wielokrotne powiadomienia resume/reconnect scalają się do jednego zamiaru.

### Trzy podstawowe flows

1. Sensor: callback/poll → Sample(value, observed_at, quality) → ComputerState revision → GUI i StateOutbox → HA. Brak sieci nie zatrzymuje lokalnego modelu.
2. Komenda: parse → ACL/feature policy → dedup/TTL/session → właściciel API → wynik + niezależny nowy odczyt stanu. „Przyjęto” i „stan potwierdzony” to odrębne zdarzenia.
3. Powiadomienie: źródła HA → walidowany NotificationRequest → inbox → engine result → host/placement → displayed/closed. Niepowodzenie obrazu nie blokuje tekstowej wersji karty.

## 6. Proposed directory structure

Proponowane drzewo jest granicą odpowiedzialności, nie nakazem natychmiastowego tworzenia każdego pliku.

~~~text
ha_windows_bridge/
  __main__.py
  bootstrap.py
  domain/
    state.py                 # Sample, ComputerSnapshot, Capability
    commands.py              # Command, Result, Policy
    notifications.py         # request, patch, lifecycle events
  application/
    application.py           # lifecycle i config transaction
    command_dispatcher.py
    state_store.py           # capabilities + observed state
    ports.py                 # tylko interfejsy używane w testach
  protocol/
    codec.py                 # wersjonowane wiadomości
    validation.py
    fixtures/                # mały wspólny corpus kontraktu
  adapters/
    windows/
      audio.py
      media.py
      system.py              # psutil i harmonogram
      hardware.py            # WMI/GPU/dyski; kontrolowany owner
      session.py             # lock, power, display, network
      applications.py        # allowlisted start/close, identity
      power.py
      effects.py
    mqtt.py
    direct_ha.py
    state_outbox.py
    configuration.py
    secrets.py
  notifications/
    engine.py                # obecny engine po poprawkach kontraktu
    positioning.py           # obecne czyste obliczenia
    qt_host.py
    card.py
    content.py               # ograniczone przygotowanie obrazu/QR
    effects.py               # opcjonalny backend, fallback
  ui/
    shell.py
    tray.py
    pages/                   # overview, computer, apps, overlays, settings, diagnostics
    components.py
    theme.py
    motion.py
    translations/
  diagnostics.py

custom_components/ha_windows_bridge/
  __init__.py                 # wyłącznie setup/unload
  config_flow.py
  runtime.py                 # typowany ConfigEntry runtime
  protocol.py                # zgodny codec, testy wspólnych fixtures
  services.py
  image_sources.py
  entity.py
  sensor.py / binary_sensor.py / media_player.py / ...
  websocket.py
  diagnostics.py
  quality_scale.yaml          # własna jawna checklist
  strings.json / translations/
  services.yaml / manifest.json

tests/
  unit/                       # bez Qt/Windows
  contracts/
  windows/
  qt/
  integration_mqtt/
  integration_ha/
  soak/
tools/
  build_release.py            # jeden manifest artefaktów
docs/
  architecture.md
  protocol.md
  support-matrix.md
~~~

Nie tworzyłbym osobnego pakietu PyPI protokołu na starcie. Specyfikacja i wspólne fixtures mogą być źródłem zgodności obu stron w jednym repozytorium. Jeśli codec jest kopiowany do paczki HA, proces pakowania musi automatycznie sprawdzać zgodność; ręczne rozjeżdżanie parserów jest niedopuszczalne.

## 7. Communication architecture

### Decyzja między MQTT i Direct

**Wybieram wspólny protokół aplikacyjny i wąską abstrakcję adapterów, z MQTT jako głównym kanałem pełnego produktu.** Direct pozostaje opcjonalnym kanałem nakładek z jawną listą capabilities. Nie utrzymywałbym dwóch niezależnych mechanizmów domenowych. Nie usuwałbym brokera, ponieważ retained state, LWT i istniejące automatyzacje dają realną wartość. Pełna telemetria Direct to późniejsze rozszerzenie tego samego kontraktu, a nie warunek stabilizacji.

Wspólne są wiadomości, ID, walidacja, policy, wynik komendy i reguła wyboru kanału. Specyficzne pozostają Paho loop, WebSocket auth, subscribe/PUBACK i ping/lease. Wystarczy port send/receive/connection state; klasa bazowa próbująca ujednolicić wszystkie reconnecty pogorszyłaby czytelność.

### Co obecnie jest dobrze zrobione

Paho callback v2, MQTT 3.1.1, QoS1, retained state, LWT offline, odrzucanie retained komend, ograniczenie rozmiaru wejścia, kopiowanie payloadu i allowlista tematów. Backoff ma wzrost do 30 s i jitter 0,75–1,0. Direct ma timeout handshake, heartbeat co 30 s, deadline odpowiedzi 10 s, lease HA 90 s, właściciela socketu i klasy błędów auth/config/network. Komendy v2 mają ID, TTL, sprawdzanie przyszłego czasu, dedup i cache wyników. Błędu powtórzenia polecenia nie wolno naprawiać usunięciem tych zabezpieczeń.

### Proponowany protokół 3

Nowy major jest uzasadniony zmianą inventory/state/target, nie kosmetyką nazw pól. Zachować JSON; bez protobuf i własnego szyfrowania.

~~~json
{
  "version": 3,
  "id": "0195-audit-command",
  "session": "current-bridge-session",
  "device_id": "stable-device-uuid",
  "kind": "audio.volume.set",
  "target": "endpoint-or-app-id",
  "arguments": {"value": 0.42},
  "issued_at": 1788630000,
  "ttl_ms": 10000
}
~~~

- Hello/capabilities: supported protocol range, session ID, capability revision i lista uprawnień/funkcji. Brak zgodnej wersji daje czytelny błąd konfiguracji.
- State: snapshot/revision + kolejne aktualizacje, observed_at i quality; pełny snapshot po reconnect. Capabilities zmieniają się po świadomej zmianie konfiguracji lub trwałym wykryciu, nie po nieudanej próbce.
- Commands: ID generowane po stronie nadawcy; stabilny target; session chroni przed wykonaniem komendy starego uruchomienia. Pierwsza akceptacja używa UTC i tolerancji zegara, potem lokalnego monotonic deadline.
- Results: accepted/pending oraz succeeded/failed/rejected/cancelled, code i ograniczony result. Dla niepewnego zakończenia OS — may_have_completed. Błąd timeout nie jest automatycznym pozwoleniem na ponowienie shutdown.
- Notifications: osobno message ID i notification ID, show/patch/remove/clear, expected revision opcjonalnie. Po sukcesie przyjęcia event displayed/closed/dropped z powodem.
- Obrazy: osobny payload/hash i limit; nie przesyłać artwork w każdej próbce pozycji. Standardowe komendy mają znacznie mniejszy limit niż komendy z obrazem.
- Wspólne budżety: przykładowo komenda bez obrazu 32 KiB, cały envelope z obrazem do 768 KiB, raster po dekodowaniu do 512 KiB i limit pikseli, snapshot stanu 64 KiB. Wartości należy zatwierdzić testem najbogatszej konfiguracji, a nie rozproszyć w pięciu parserach.

MQTT: capability manifest retained, najnowszy snapshot retained, command/result bez retain. Zmiana retained inventory może wycofać capability wyłącznie przez jawny tombstone lub revision usunięcia. Birth HA wywołuje wymuszoną resynchronizację z jitterem; cache równości nie może jej anulować. Dokumentacja HA opisuje birth i ponowne publikowanie discovery/stanu; własna integracja powinna realizować równoważny kontrakt. [MQTT HA](https://www.home-assistant.io/integrations/mqtt/#discovery-messages-and-availability).

Warto użyć MQTT 5 dla expiry/session controls przy nowym protokole. Obecne MQTT 3.1.1 w kliencie Windows **nie jest samo w sobie błędem**: broker może obsługiwać równocześnie 3.1.1 i 5. Wymogi HA wobec brokera nie oznaczają, że każdy klient musi używać tej samej wersji.

Nie obiecywać exactly-once skutku OS. Idempotentne set-volume można bezpiecznie rozliczać dedupem; start/close/power wymagają świadomej semantyki powtórzeń. Pending/completed dedup ma limit i czas ważności. Retry na drugim transporcie zachowuje ten sam ID i session. Nie wysyłać jednocześnie przez oba kanały.

### Scenariusze sieciowe

| Scenariusz | Obecne zachowanie / luka | Kontrakt docelowy |
| --- | --- | --- |
| HA startuje później | MQTT retained pomaga; Direct retry network, ale integration_missing/config może zakończyć retry | Rozróżnić trwały błąd tokenu od oczekiwania na instalację/entry; czytelny Retry |
| Restart HA | Birth → inventory requested; równość cache może ograniczyć resend | Jawny resync snapshot/manifest i reset oczekujących futures |
| Restart brokera | Reconnect/replay; ryzyko C01/H01 | Snapshot observed state nowej sesji, potem dirty updates |
| Brak brokera 10 min / Wi-Fi | Retry jest ograniczone; telemetria zatrzymuje lokalne próbkowanie | Lokalny model działa na potrzebę GUI/policy; outbox trzyma ostatni stan, nie historię wszystkich próbek |
| Sleep na kilka godzin | Stop/rebuild istnieje, provider/capture lifecycle niepełny | Nowa session, discard przeterminowanych komend, odtworzenie ownerów |
| Zmiana sieci/IP | Głównie timeout i reconnect | Zdarzenie sieci invaliduje połączenie/DNS; hostnames nadal preferowane |
| Kilka reconnectów naraz | SerialWorker zachowuje kolejkę wielu restartów | Jeden desired state i jeden outstanding reconnect |
| Token unieważniony | AUTH_ERROR, ręczny reconnect po poprawce | Stan requires_action; UX odnowienia tokenu bez restartu całej aplikacji |
| Direct ginie podczas komendy | Pending Direct kończy się błędem; nowe popupy wracają do MQTT | Zachować deterministyczny wynik; retry tylko wg idempotencji, z tym samym ID |


## 8. Overlay architecture

**Zachować NotificationEngine i PlacementEngine, ponownie napisać granicę przyjęcia oraz uporządkować host/render pipeline.** Pełny rewrite czystej kolejki nie daje korzyści: ma limit widocznych 4, kolejkę 32, stabilne priorytety, update/remove/clear, hover pause, pinned i testowalne pozycjonowanie.

### Model i zachowanie

Docelowy NotificationRequest powinien zawierać stabilne notification_id, source, content, presentation, lifetime i policy. Komenda transportowa ma własne ID. Dzięki temu retry komendy nie jest kolejną kartą, a aktualizacja karty nie udaje nowej komendy show.

| Obszar | Ocena obecna | Projekt docelowy |
| --- | --- | --- |
| Show/update | Upsert istnieje; HA update potrafi skasować treść | Rozdzielić show/replace/patch; omitted nie znaczy empty |
| Priorytet/kolejka | Stabilne sortowanie i bounded pending są dobre | Priorytet wpływa na oczekujące; jawna polityka preemption wyłącznie gdy potrzebna |
| Pinned | Brak zegara jest oszczędny | Limit pinned per źródło, zawsze dostępna droga zamknięcia |
| Timeout | Widoczność ma monotonic clock i hover remaining | Osobno maksymalny wiek oczekiwania w kolejce oraz czas ekspozycji |
| Parallel/stacking | Dobre czyste obliczenia i odstępy | Osobny wynik deferred/no_space; nie blokować bez końca całej kolejki przez pierwszy duży element |
| Zamykanie | Okna mogą być w stanie retiring poza limitem engine | Limit obejmuje staging/visible/retiring; burst nie tworzy dowolnie wielu HWND |
| Lock/fullscreen | Sprawdzenie przed przekazaniem i clear na lock | Ponowna policy na GUI tuż przed show; session/generation usuwa race po clear/lock |
| Actions | Zamknięcie i lokalne media; brak ogólnego bezpiecznego API callbacków | Action ID zarejestrowane przez HA, wynik kliknięcia jako event; brak dowolnych poleceń/URL z payloadu |
| Progress | Właściwy model, rendering zależy od layoutu | Osobny widget wartości i tryb indeterminate; progress update nie resetuje lifetime |
| Media Windows | Timeline interpolowany, artwork nie dekoduje się przy każdej sekundzie | Wspólny snapshot WinRT; komendy do wskazanej sesji |
| Media HA | Pojedynczy snapshot | Domyślnie snapshot; subskrypcja tylko przez jawny czasowy lease |
| Camera/image | Statyczna klatka, nie streaming | Zachować snapshot, limit wieku i zasobów; streaming osobno jako przyszła funkcja |
| Badge | Mały i dobrze pozycjonowany | Jawnie określić supported content; dziś obraz/progress nie mają pełnej obsługi |
| Multi-monitor | Work area, ujemne origin i DPI są uwzględnione | Stable monitor ID, fallback na primary, aktualizacja HA select po hotplug |

Trzy warstwy wystarczą: **engine**, **host okien**, **przygotowanie contentu/efektu**. Przygotowanie obrazu i QR może działać poza GUI, ale utworzenie QPixmap/QWidget i zmiana okna pozostaje na GUI. Budżet pamięci musi obejmować rozkodowany raster, cache, przygotowaną klatkę i okna w animacji, a nie tylko wielkość JSON.

Sukces przyjęcia do silnika zwraca queued/shown wraz z notification_id. Gdy nie ma miejsca: rejected/queue_full. Osobne zdarzenia closed/dropped mają powód expired, user, replaced, locked, display_removed lub render_error. HA może dzięki temu monitorować dostarczenie. „Displayed” nadal nie znaczy „przeczytane”.

### Szkło i natywne efekty

Bieżący blur/liquid używa **DXGI + Pillow**, a nie aktywnie metod apply_acrylic/apply_blur pozostawionych w NativeBackdrop. Widać tu historyczne warstwy i nieaktualne opisy alpha. Capture uruchamia się dla odpowiednich kart, nie stale przez całą pracę w trayu — to ważna zaleta. Koszt istnieje jednak dla pinned glass.

Rekomenduję jednolite, dobrze zaprojektowane tło jako domyślne. Efekt natywny tylko dla sprawdzonego typu HWND i wersji Windows; jego brak nie zmienia layoutu ani działania. Capture glass jako opcja eksperymentalna, z limitem częstotliwości, kosztu, pamięci i czasu oczekiwania na pierwszą klatkę. Na baterii/RDP/po utracie urządzenia grafiki automatyczny prosty fallback. Bez wymogu przechwycenia pulpitu, aby zwykła wiadomość mogła się pojawić.

Wykluczanie własnych HWND z capture zapobiega pętli obrazu, ale może usuwać popup również ze zrzutów i nagrań. To cecha produktu wymagająca jasnej opcji. Nie proponuję przechwytywania pełnego ekranu ani zapisywania tła do diagnostyki.

### Jeden Motion System

Obecnie istnieją wejście/wyjście popupu, slide/fade/reveal, przesunięcia, przejście stron i animowany toggle. Dobre: snapshot całej karty przy części animacji, stały rozmiar mediów, przerywanie animacji, obsługa Windows Reduced Motion. Braki: token distance=12 nie jest faktycznym jedynym dystansem, kod używa również 24; exit dziedziczy skonfigurowany czas wejścia; scale nie jest konsekwentnie używane; hover/press to głównie natychmiastowe QSS.

| Ruch | Proponowany token | Easing / parametry | Koszt |
| --- | --- | --- | --- |
| Popup enter | 220 ms | OutCubic; opacity 0→1; translation 12 DIP | Stały layout, animacja przygotowanej warstwy |
| Popup exit | 160 ms | InCubic; opacity 1→0; translation 6 DIP | Bez przebudowy siatki |
| Reposition | 180 ms | OutCubic | Jedna docelowa geometria, przerwanie od bieżącej pozycji |
| Page transition | 120–180 ms | OutCubic, głównie fade | Bez screenshotów całego UI w pętli |
| Navigation selection | 120 ms | OutCubic, kolor/krótki wskaźnik | Nie przebudowywać strony |
| Hover | 100 ms | OutCubic, kolor | Tylko obszar kontrolki |
| Press | 80 ms | OutCubic | Kolor; opcjonalnie scale 0,985 przygotowanego elementu |
| Toggle | 120 ms | OutCubic | Pozycja wewnętrznego uchwytu |
| Reduced Motion | 0 ms dla przemieszczeń | Bez scale/reveal, natychmiastowe przejście | Zachować informację o zmianie stanu |

Scale jest dopuszczalnym parametrem, nie obowiązkowym efektem wszystkich kontrolek. Nie animować layout size ani renderować QR co klatkę. Reveal z maską natywnego okna jest bardziej kosztowny i trudniejszy w DWM niż fade; pozostawić jako opcję po pomiarze. Zmiana systemowej preferencji animacji powinna wpływać także na już trwający ruch.

## 9. UI/UX redesign

Ocena opiera się na kodzie i renderach Qt, nie na samym QSS. Obecne UI jest czytelne: spokojna ciemna paleta, Segoe UI, wyraźne nagłówki, sensowne odstępy, boczna nawigacja i duży przycisk zapisu. Natywna ramka QMainWindow jest właściwym wyborem dla resize, systemowego menu i Snap. Testy minimum 820×620 i obu motywów mają wartość.

Problem produktu: **„Przegląd” jest przede wszystkim formularzem połączeń**, a „Sensory i funkcje” długą listą dużych przełączników. Użytkownik nie dostaje szybkiej odpowiedzi: co udostępniam, co faktycznie działa, co ostatnio zawiodło i jak to naprawić.

### Nowa struktura informacji

| Ekran | Główne zadanie użytkownika | Projekt |
| --- | --- | --- |
| Pierwsze uruchomienie | Połączyć komputer i wysłać pierwszy test | 3 kroki: kanał → połączenie → funkcje/uprawnienia. MQTT pełny produkt, Direct same popupy opisane wprost |
| Przegląd | Ocenić działanie w kilka sekund | Połączenie per kanał, ostatni odbiór HA, aktywne capabilities, freshness, ostatni błąd z konkretną akcją |
| Komputer | Wybrać dane i zrozumieć ich stan | Grupy System/Obecność/Urządzenia/Audio; wartość, źródło, last update, privacy i przełącznik udostępniania |
| Aplikacje | Skonfigurować dozwolone aplikacje | Stan sesji, volume/mute, udostępnianie, osobne start/close i pewna ścieżka celu |
| Powiadomienia | Sprawdzić zachowanie popupów | Podgląd, monitor, polityka lock/fullscreen, kolejka i ostatnie wyniki; basic/advanced |
| Ustawienia | Konfiguracja i administracja | Połączenia, autostart, motyw, język, aktualizacje, import/export; nie dominują na dashboardzie |
| Diagnostyka | Naprawić konkretny problem | Health subsystemów, kolejki, próby reconnect, błędy z kodem, filtrowany log i eksport z preview |

Model ustawień: draft + widoczny stan „niezapisane zmiany”, Apply/Discard, wynik każdego etapu apply. Przejście strony zachowuje draft; zamknięcie informuje o realnych niezapisanych zmianach. Zmiana wyglądu może mieć lokalny preview bez restartu sieci. Zmiana serwera pokazuje wynik testu połączenia i skutki dla poświadczeń.

Sterowanie audio jest natychmiastową akcją, nie fragmentem konfiguracji oczekującej na globalny Save. Włączenie udostępniania HA pozostaje świadomą zmianą konfiguracji. Obecnie ukryte/wyłączone i nieosiągalne bywają wizualnie zbliżone; rozdzielić stany: wyłączone przez użytkownika, brak sesji, błąd źródła, oczekuje na zapis, wykonuje polecenie.

### Fluent bez dekoracyjnej przebudowy systemu okien

- Typografia: title 28–32 DIP, section 18–20, body 14; konsekwentna hierarchia zamiast pogrubionego tytułu każdej opcji.
- Spacing: siatka 4/8/12/16/24, kompaktowe wiersze dla prostych opcji; karty dla grup znaczeniowych, nie każdej wartości.
- Stany kontrolek: widoczny focus klawiatury, press, selected, hover i odrębne disabled/unavailable; klawiatura musi wykonywać tę samą akcję co mysz.
- Dark/light/system: jedna paleta semantyczna; overlay również zgodny z motywem albo jawnie osobny. Akcent systemu nie może obniżać kontrastu tekstu.
- Kontrast: media_palette sprawdza tekst podstawowy i pomocniczy, ale próg 3,6 dla małego tekstu jest zbyt niski jako przyjęty cel dostępności. Przyjąć 4,5 dla zwykłego tekstu i zweryfikować rzeczywisty render, nie tylko kolor jednolitej próbki.
- Dostępność: nazwy kontrolek, label buddy, tab order, Narrator i high contrast; no-activate popup z definicji utrudnia klawiaturę. Ważne akcje powinny być dostępne również z okna/trayu/centrum powiadomień.
- Mica/Acrylic: opcjonalna powierzchnia, nie warunek „nowoczesności”. Zachować natywny titlebar i działające Snap. Nie wracać do frameless głównego okna dla samych zaokrągleń.
- DPI: projektować w DIP, testować 100/125/150/200%, zmianę ekranu podczas animacji i długie teksty PL/EN. 820 DIP nie gwarantuje wygodnego półekranowego Snap na każdym ekranie; docelowo kompaktowy sidebar i sensowny tryb około 640–720 DIP.
- Tray: stan per kanał, ostatni błąd, pause sensors, quiet notifications, reconnect i exit. Otwórz powinno przywracać i aktywować okno; druga instancja ma aktywować pierwszą.

Nie dodawałbym teraz biblioteki Fluent Widgets, QtQuick ani WebView. Istniejący Qt wystarcza do tego UX; najważniejsze zmiany dotyczą modelu stanu i workflow.

## 10. Home Assistant integration redesign

Integrację oceniono według aktualnej dokumentacji HA oraz kodu tagów 2025.1.0 i 2026.9.1. Integration Quality Scale jest tu checklistą jakości, a nie nadaniem oficjalnego poziomu custom integration. [IQS](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/).

### Ocena obecnej zgodności

| Obszar | Obecny stan | Wymagana zmiana |
| --- | --- | --- |
| Config flow | Discovery MQTT, ręczny Direct, unique_id, walidacja payloadu | Pełne testy flow z real HA; związanie identyfikacji i prefiksu |
| Reconfigure | Direct zmienia nazwę, zachowuje ID | Rozdzielić nazwę/capabilities/transport; MQTT nadal zarządzany discovery |
| Reauth | Integracja nie przechowuje sekretu Windows ani tokenu zewnętrznego serwera | **Brak reauth w HA nie jest sam w sobie błędem**; LLAT odnawia się po stronie Windows |
| runtime_data | Używany poprawnie | Typowany ConfigEntry[BridgeRuntime], bez Any na głównych granicach |
| Unique IDs / device registry | Stabilne po zapisie profilu, wspólny device ID | Nie uzależniać od nazwy aplikacji/hostname; jeden wpis urządzenia z opcjami kanałów |
| Entity registry | Aggressive remove podczas setup | Zachować niedostępne encje; usuwać tylko jawnie |
| Entity lifecycle | Base korzysta z async_on_remove | Naprawić obie klasy media_player, test partial setup |
| Availability | Broker + bridge; lease Direct | Per źródło, freshness i transport zdolny wykonać daną akcję |
| Unload/reload | Forward/unload platform i runtime.close istnieją | Testy braku subskrypcji/timerów/futures po błędzie każdego etapu |
| Services/actions | Show/update/remove/clear, target/source ACL | Oddzielne services.py; PATCH, częściowe wyniki fan-out, tłumaczone wyjątki |
| Translations | strings, PL/EN, selectory akcji | Tłumaczenia nazw encji/wyjątków, jeden sens pól i domyślnych wartości |
| Diagnostics | Dobra allowlista; bez tożsamości i payloadów | Dodać kompatybilność, freshness, typowane health |
| Repairs | Brak | Niekompatybilny protokół, utracony source, wymagane ponowne sparowanie |
| Testy / minimum | API doubles, hassfest/HACS w CI; min2025.1 niespójne | Rzeczywisty HA runtime i wspierana macierz |
| Parallel updates | Brak jawnej polityki platform | Ustalić limity dla push encji i współbieżnych komend |

HA wymaga sprzątania subskrypcji/połączeń przy unload oraz właściwego oznaczania dostępności. Obecna baza częściowo to realizuje; H02/M19 pokazują, dlaczego test klasy bazowej nie wystarcza. [Unloading](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/config-entry-unloading/), [unavailable](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/entity-unavailable/). Dla reauth trzeba stosować wyjątki właściwe dla architektury uwierzytelniania, nie dodawać pustego flow dla samej checklisty. [Reauthentication](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/reauthentication-flow/).

### Docelowa integracja

Jeden BridgeRuntime na komputer przechowuje capabilities, snapshot, session, transport health i pending commands. Encje są cienką projekcją tych danych, bez osobnego pollingu. Wspólny update push powiadamia zainteresowane encje. DataUpdateCoordinator można zastosować, jeśli ułatwia rzeczywistą koordynację; nie jest obowiązkowym wrapperem wokół każdego callbacku.

Device UUID jest trwałą tożsamością instalacji, display name można zmieniać. Entity unique_id powstaje z UUID i capability ID. Zmiana monitorów/endpointów nie powinna tworzyć nowych „komputerów”. Obecne dwa wpisy MQTT i Direct migrować do jednego wpisu z wyborem kanału i jedną encją popupu, z zachowaniem rejestru tam, gdzie semantyka funkcji się nie zmieniła.

Zredukować przenoszone definicje platform i legacy route tables. Bridge ogłasza semantyczne capabilities, a HA wybiera platformę, device_class, state_class, jednostkę i tłumaczenie. Schemat allowlisty nie pozwala na dowolne tematy innych urządzeń. Dla diagnostycznych i dublujących encji używać disabled-by-default.

Akcje: proste show, patch, dismiss, clear; podstawowe pola widoczne, source/media/appearance rozwijane. Dzisiaj formularz show ma wiele required defaults nawet dla rozmiaru auto, a update jest inaczej ułożony. Zmniejszyć liczbę wymaganych decyzji. W przypadku wielu PC wynik powinien wskazywać, które przyjęły żądanie, zamiast samej liczby błędów.

Źródła camera/image pobiera HA po kontroli POLICY_READ. Bridge otrzymuje ograniczony raster i tekst, bez HA tokenów źródłowych. Obsługa URL i źródeł pozostaje oddzielona od protokołu wykonania. Repairs i diagnostics używają kodów problemów, nie pełnych treści okien czy notification payloadów.


## 11. Windows integration improvements

### Model integracji z systemem

Bridge powinien pozostać aplikacją użytkownika uruchamianą w jego interaktywnej sesji. Audio, GSMTC, aktywne okno, tray i nakładki należą do tej sesji. Przeniesienie całości do Windows Service skomplikowałoby dostęp do pulpitu i uprawnień. Nie ma obecnie potrzeby dodawania uprzywilejowanego serwisu pomocniczego.

| Obszar | Ocena obecnej implementacji | Docelowy sposób |
| --- | --- | --- |
| Core Audio | Wartościowe adaptery, lecz wielokrotna enumeracja i operacje z różnych wątków | Jeden właściciel COM dla audio; cache endpointów i sesji; callbacki zmiany urządzeń, master volume i session lifecycle |
| Mikrofon | Poziom sygnału jest interpretowany jako aktywność; pomiar chwilowy może zwrócić ciszę | Nazwać sensor „wykryty sygnał mikrofonu”; nie obiecywać wykrywania wszystkich aplikacji korzystających z mikrofonu |
| GSMTC / WinRT | Własny asyncio runner izoluje wywołania; polling i niepełna weryfikacja końca pracy | Jeden manager sesji, eventy playback/media/timeline, anulowalne pobranie artwork, jawne odpinanie event tokens |
| WMI | Użyteczne dane, ale brak COM w wątku pollingu i mieszanie wielu źródeł | Każdy wątek COM inicjalizuje własny apartment; provider izoluje błędy i opisuje pochodzenie/świeżość danych |
| Foreground / fullscreen | Win32 i geometria monitora; „fullscreen” to heurystyka | WinEvent hook dla foreground, mała kontrola geometrii jako fallback; nie utożsamiać z Focus Assist ani trybem gry |
| Sleep / resume | Native filter rozpoznaje suspend i resume | Quiesce providerów przed snem, po resume nowa generacja zasobów i pełny refresh; transporty uruchomić raz |
| Lock / unlock | Obsługa WTS; mechanizm czyszczenia nakładek | Lock jest również polityką przyjmowania nowych powiadomień, a nie tylko poleceniem usunięcia bieżących |
| Sieć | Reconnect wykrywa awarię po błędzie transportu; brak osobnych eventów sieci | Zmiana interfejsu wyzwala kontrolowany reconnect z jitterem; nie traktować jej jako dowodu dostępności HA |
| Monitory / DPI | QScreen, availableGeometry i eventy display; cache capture ma osobny lifecycle | Przeliczanie w DIP, odtwarzanie backing resources przy zmianie DPI/topologii, trwałe ID monitora i fallback |
| Explorer restart | Rozpoznawany komunikat TaskbarCreated | Sprawdzić odtworzenie ikony tray i interakcję menu na prawdziwym Explorerze |
| Zamknięcie sesji | Zwykłe zamknięcie aplikacji ma ścieżkę shutdown | Obsłużyć granice logoff/end-session, ograniczyć czas flush; nie polegać na długiej pracy w końcowym callbacku |
| ctypes | Kilka małych wrapperów bez pełnych sygnatur | Deklarować argtypes/restype, sprawdzać błędy, domykać HANDLE dokładnie raz |

COM wymaga inicjalizacji osobno w każdym używającym go wątku. To jest wymóg platformy, a nie preferencja projektowa; próba P07 potwierdziła jego znaczenie w tym środowisku. [Microsoft: inicjalizacja COM](https://learn.microsoft.com/en-us/windows/win32/learnwin32/initializing-the-com-library/).

Windows udostępnia powiadomienia o endpointach audio i zmianie głośności oraz eventy GSMTC. Można dzięki nim ograniczyć enumerację, zachowując rzadki polling naprawczy po utracie zdarzenia. [IMMNotificationClient](https://learn.microsoft.com/en-us/windows/win32/api/mmdeviceapi/nn-mmdeviceapi-immnotificationclient), [IAudioEndpointVolumeCallback](https://learn.microsoft.com/en-us/windows/win32/api/endpointvolume/nn-endpointvolume-iaudioendpointvolumecallback), [GSMTC timeline event](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssession.timelinepropertieschanged?view=winrt-26100).

Dla sieci, urządzeń i aktywnego okna istnieją konkretne API; ich callback ma tylko przekazać zdarzenie do właściciela stanu. Nie powinien wykonywać WMI, rekonfiguracji ani publikacji MQTT. [NotifyIpInterfaceChange](https://learn.microsoft.com/en-us/windows/win32/api/netioapi/nf-netioapi-notifyipinterfacechange), [RegisterDeviceNotificationW](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerdevicenotificationw), [SetWinEventHook](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwineventhook).

### Kruche miejsca i kompatybilność

- Odczyt prywatnych pól DXcam i wiązanie capture z nazwą monitora utrudniają odbudowę po odłączeniu ekranu. Zamknąć je w jednym opcjonalnym adapterze; awaria wyłącza efekt.
- Dostęp do Hardware Monitor przez WMI zależy od obecności zewnętrznego providera. Brak programu nie oznacza temperatury 0°C. Stosować negative cache i stan unsupported.
- Ustawianie domyślnego endpointu audio oraz wykrywanie aplikacji Store wymagają testów zachowania na wspieranych Windows. Nie budować publicznego kontraktu na nazwie urządzenia ani zgadywanym identyfikatorze aplikacji.
- Wywołania ctypes dotyczące desktopu/mutexu muszą mieć poprawne typy uchwytów na x64. Pomyślne działanie w jednym środowisku nie zastępuje sprawdzania wyniku API.
- GPU fan speed z nvidia-smi jest procentem, a nie RPM. Temperature nie jest właściwością MSFT_PhysicalDisk; stosować właściwe źródło danych albo zgłosić brak obsługi. [NVIDIA](https://docs.nvidia.com/deploy/nvidia-smi/index.html#fan-speed), [MSFT_PhysicalDisk](https://learn.microsoft.com/en-us/windows-hardware/drivers/storage/msft-physicaldisk).

Nie proponuję przepisywania GUI na WinUI wyłącznie dla wyglądu. Obecny Qt pozwala zachować natywną ramkę, Snap i skalowanie. Mica/system backdrop może być ulepszeniem na obsługiwanych buildach Windows 11, ze zwykłym tłem na Windows 10; dostępność konkretnego atrybutu trzeba sprawdzać w runtime. Obecny screenshot blur nie jest natywnym Acrylic.

Qt 6.11 wspiera Windows 10 od 1809 oraz Windows 11; dokumentacja wskazuje Qt 6.12 jako ostatnią linię ze wsparciem Windows 10. Oznacza to konieczność świadomej polityki wersji Qt i osobnej macierzy testów, a nie automatycznego aktualizowania dowolnej wersji spełniającej „<7”. Obecny instalator x64 nie oznacza obsługi ARM64. [Qt: Windows support](https://doc.qt.io/qt-6/windows.html).

## 12. Security improvements

### Granice zaufania

| Granica | Zasada i obecny stan | Zmiana |
| --- | --- | --- |
| Konto Windows → sekrety | Nowy profil używa DPAPI dla bieżącego użytkownika; dobry wybór | Zachować; atomowy zapis, kontrolowane odzyskiwanie i eksport bez sekretów |
| Bridge → broker | Hasło i opcjonalny TLS; prawo publikacji jest uprawnieniem do komend | TLS z weryfikacją, broker ACL na urządzenie, osobne konta; nie udawać, że walidacja JSON zastępuje ACL |
| Bridge → HA WebSocket | LLAT jest sekretem o uprawnieniach konta HA | Weryfikowany TLS, jasny komunikat auth_failed, odnowienie tokenu po stronie Windows |
| HA caller → device | POLICY_CONTROL przy WebSocket/actions; odczyt źródła obrazu kontrolowany osobno | Zachować kontrolę target/source; testować wszystkie ścieżki i wiele targetów |
| Payload → domena | Limity bajtów, TTL, identyfikatory, allowlist komend, dedup | Ograniczenia liczby elementów/głębokości, walidacja typów przed użyciem jako klucza; jedno wejście dla obu transportów |
| Domena → Windows | Komendy zarejestrowane, ścieżki aplikacji pochodzą z lokalnej konfiguracji | Uprawnienia funkcji per urządzenie; brak zdalnego arbitralnego executable/argumentów |
| Obraz → HA/Qt | Ograniczenia pobrania i pikseli, ale URL może kierować HA do wybranych hostów | Preferować encje camera/image, jawna polityka URL, ograniczenie redirectów/rozmiaru/formatu i całego czasu |
| Dane → diagnostyka | HA diagnostics ma dobrą allowlistę; Windows pokazuje więcej danych lokalnych | Eksport redagowany domyślnie; osobny świadomy eksport szczegółowy |
| Build → użytkownik | Hash ZIP, możliwość podpisywania; podpis nie jest wymagany | Podpis w release gate, weryfikacja artefaktów, jawne wersje i notices zależności |

**Model zagrożeń:** nieufne dane z brokera lub HA, przejęte konto MQTT, zwykły użytkownik HA o ograniczonych prawach, błędny/złośliwy obraz, niezamierzone ujawnienie lokalnych danych w zgłoszeniu oraz błędna konfiguracja. Proces działający już jako ten sam użytkownik Windows może zwykle korzystać z jego DPAPI; DPAPI chroni dane zapisane na dysku, nie stanowi sandboxu wobec takiego procesu. Nie ma podstaw, by przedstawiać obecną aplikację jako bezpieczną mimo przejęcia konta Windows.

### Co jest dobre

Nie znalazłem zdalnej ścieżki do arbitralnego shell execution, eval/exec ani deserializacji pickle. Produkcyjne uruchomienia programów i narzędzi korzystają z określonych argumentów lub lokalnie skonfigurowanych aplikacji; zwykłe wyszukanie słowa „exec” w testach AST nie świadczy o podatności produktu. Nie stwierdziłem również potwierdzonego path traversal pozwalającego zapisać dowolny plik przez MQTT. Są to wyniki przeglądu, nie dowód kompletnego braku podatności.

Walidacja retained command, TTL i dedup jest wartościowa. W Direct sprawdzanie powiązania odpowiedzi z autoryzowanym połączeniem oraz ograniczenie pending requests są dobrymi granicami. Nie należy ich usuwać w refaktorze.

### Najważniejsze zmiany

1. **Jednoznacznie opisać skutki power commands.** Obecne shutdown /t 30 implikuje /f; może zamknąć programy z niezapisanymi zmianami. Nie zwiększać uprawnień procesu, żeby wymusić sukces. Dodać osobne, jawne polityki łagodnego i wymuszonego wyłączenia oraz anulowanie odliczania. [Microsoft: shutdown](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/shutdown).
2. **Związać MQTT topic, device ID i dozwolony prefix.** Sama deklaracja prefixu w payloadzie discovery nie jest dowodem tożsamości. Przy prawie publikacji do wspólnego discovery inny klient może podszyć się pod urządzenie; to wymaga zarówno walidacji, jak i ACL.
3. **Zamknąć automatyczne obniżanie bezpieczeństwa importu.** Decyzja zaufania do importowanej konfiguracji musi obejmować verify_tls, nie tylko host i login. Pokazać różnicę przed przyjęciem słabszej polityki.
4. **Urealnić ochronę obrazów.** Odczyt aiohttp read(n) nie gwarantuje odczytu całego obrazu do n bajtów. Czytać do EOF z twardym limitem, ograniczyć dekodowanie i nie logować treści/data URI. SSRF-like ryzyko dotyczy wykonywania żądań z sieci HA, nie potwierdzonej eksfiltracji LLAT. [aiohttp StreamReader](https://docs.aiohttp.org/en/stable/streams.html#aiohttp.StreamReader.read).
5. **Domknąć backpressure.** Limit modelowej kolejki overlay nie ogranicza kolejki sygnałów Qt przed modelem. Limity trzeba egzekwować przed kosztownym decode i przed przekazaniem pracy.
6. **Zredagować diagnostykę Windows.** Nazwy hostów, pełne ścieżki, tytuł aktywnego okna, lista aplikacji i treść powiadomień mogą być prywatne. Logować identyfikatory/kody i liczniki; sekrety, nagłówki auth i całe payloady są wykluczone. [HA diagnostics](https://developers.home-assistant.io/docs/core/integration/diagnostics/).

Nie proponuję dodatkowego szyfrowania własnym kluczem zapisanym obok profilu ani własnego mechanizmu kryptograficznego nad MQTT. TLS, poprawne ACL, DPAPI, ograniczone polecenia i rygorystyczna walidacja rozwiązują konkretne granice przy mniejszym koszcie utrzymania.


## 13. Performance improvements

### Obecny polling i wake-up

Częstotliwości poniżej pochodzą z kodu, nie z pomiaru procesora. Interwał schedulera jest ograniczany do 0,2–10 s, domyślnie 0,5 s. Callbacki są wykonywane sekwencyjnie: ich czas wydłuża rzeczywisty cykl. Brak skonfigurowanego MQTT oznacza brak usługi telemetrii; rozłączony transport ogranicza odczyty, lecz scheduler nadal się budzi.

| Odczyt / timer | Obecnie | Event/callback lub ograniczenie | Docelowa polityka |
| --- | --- | --- | --- |
| Master volume, mute, balance | Każdy cykl, zwykle 0,5 s | Core Audio endpoint callback | Event + pełny odczyt na connect/resume i rzadki repair |
| Audio sesje, głośności aplikacji, liczba sesji | Każdy cykl; dodatkowe enumeracje dla poszczególnych operacji | Session notification / volume events | Jeden snapshot sesji; callbacki, rescan tylko przy zmianie lub awarii |
| Mikrofon: volume/mute/sygnał | Każdy cykl; pomiar peak obejmuje ok. 20 ms oczekiwania | Volume callback; amplituda wymaga próbkowania | Osobno konfiguracja i peak; peak tylko przy włączonej funkcji, adaptacyjnie |
| Procesy aplikacji | Około 2 s | Eventy możliwe, ale ETW/WMI watcher zwiększają koszt utrzymania | Jeden wspólny odczyt co 2–10 s zależnie od zapotrzebowania |
| Aktywna aplikacja/okno, fullscreen, idle, lock | Około 1 s | Foreground WinEvent i WTS; idle wymaga odczytu czasu | Eventy dla zmian; tani idle co 1–5 s zależnie od progu |
| CPU/RAM i pozostałe metrics | 5 s | Zużycie jest sygnałem ciągłym | Polling pozostawić; tylko włączone metryki, wolniej na baterii |
| NVIDIA GPU | Cache około 10 s, proces nvidia-smi | Brak potrzeby dodawania NVML tylko dla tych odczytów | Batch query, timeout i cache; nie wykonywać przy wyłączonych sensorach |
| Hardware Monitor WMI | Przy system_metrics, zwykle co 5 s, także przy discovery | Zależność od zewnętrznego providera | Negative cache 60–300 s po braku providera, osobny wolny worker |
| Windows health / power plan | 30 s, część przez subprocess | Power events; stan aktualizacji nie musi być bieżący co sekundę | Event dla AC/plan + rzadka weryfikacja |
| Windows Update COM | Nie częściej niż co 30 min; własny daemon | Operacja może być długotrwała | Osobny właściciel, stan „checking/unknown”, kontrola końca pracy |
| Dyski: użycie/transfer | 5 s | Transfer wymaga próbkowania | I/O 5–10 s; capacity 30–60 s, tylko wybrane woluminy |
| Disk health | Cache około 60 s | Rzadko zmienny stan | Naprawić źródło, następnie 60–300 s i backoff błędów |
| Urządzenia PnP | Około 10 s; historyczny katalog także ręcznie | Device notification | Zmiana urządzeń + debounce; rzadki pełny rescan |
| Wyjścia audio | Około 3 s | IMMNotificationClient | Event + repair, stabilne ID |
| Media snapshot w telemetrii | Około 1 s | GSMTC events | Wspólny snapshot; interpolacja position lokalnie |
| Inventory/discovery | Scheduler sprawdza flagę, odstęp około 5 s | Request/HA birth/zmiana capabilities | Publikacja tylko po zmianie revision lub żądaniu, z debounce |
| GUI: aplikacje/inventory | 6 s, podczas widocznej strony | Wspólny stan aplikacji | Subskrypcja snapshotu; brak oddzielnej enumeracji audio/procesów |
| GUI: diagnostics | 2 s, podczas widocznej strony | Bufor/log event | Batch update widocznego widoku; limit liczby renderowanych wierszy |
| Overlay housekeeping/progress | 50 ms przy smooth; inaczej 500 ms, podczas obsługi nakładek | Deadline queue, animation driver | Timer tylko gdy potrzebny; deadline dla expiry, animacja tylko aktywna |
| Overlay media | 500 ms dla widocznego media overlay | Ten sam manager GSMTC | Wspólne dane, bez kolejnego żądania snapshotu |
| Glass capture | 250 ms AC / 500 ms bateria; po wolnym kroku 750 ms | Efekt nie musi być stale aktualizowany | Domyślnie brak capture; snapshot przy wejściu lub eksperymentalny adaptive |
| MQTT loop / keepalive | Loop ok. 1 s; keepalive 10 s; backoff z jitter | Mechanizm transportu jest potrzebny | Jeden właściciel i deadline; mierzyć liczbę prób/wake-up, bez busy retry |
| Direct heartbeat | Około 30 s, lease HA 90 s, request timeout 10 s | Mechanizm wykrywania utraty sesji | Zachować sens, scentralizować deadline i anulować przy stop |
| Update check | Opóźniony jednorazowy start ok. 10 s i akcja użytkownika | Nie jest ciągłym pollingiem | Zachować mały koszt; timeout i cache rezultatu |

Źródła implementacji: [[ha_windows_bridge/application/telemetry.py:223]], [[ha_windows_bridge/ui/shell.py:325]], [[ha_windows_bridge/overlays/service.py:25]], [[ha_windows_bridge/overlays/glass.py:25]], [[ha_windows_bridge/system_monitor.py:185]], [[ha_windows_bridge/media.py:253]].

### Koszt, pamięć i publikacja

Największy zysk da współdzielenie danych i odseparowanie wolnego I/O. Zamiana kilku słowników na „szybszą” strukturę nie rozwiąże powtarzanej enumeracji sesji ani uruchamiania procesów. Obsługa zdarzeń powinna coalescować serię zmian i nigdy blokować callbacku Windows.

Obecny glass robi capture, konwersję/resize i blur CPU. Hash policzony po przetworzeniu może oszczędzić repaint, ale nie wcześniejszą pracę. Reakcja na wolne klatki jest jednostronna; tryb zasilania nie jest pełną dynamiczną polityką. Dla funkcji informacyjnej lepsze są nieruchome tło, pojedynczy snapshot lub natywny efekt dostępny na danym OS. Desktop capture pozostaje opcjonalną funkcją zaawansowaną.

Źródła potencjalnego wzrostu pamięci to oczekujące sygnały Qt, zaległe publikacje Paho, nieodpięte subskrypcje HA po częściowym błędzie i zasoby capture po zmianie topologii. **Nie stwierdzam zmierzonego wycieku pamięci całego procesu**; nie wykonano długiego soak. Obecne limity command queue, Direct pending i modelowej kolejki nakładek są zaletą, ale nie obejmują wszystkich etapów.

StateOutbox powinien zastępować starszy stan dla tego samego klucza i przechowywać najnowszą obserwację niezależnie od wyniku send. Publikować zmienione pola z deadbandem właściwym dla jednostki; po reconnect pełny snapshot. Progress/volume drag można ograniczyć do kilku–kilkunastu aktualizacji/s i zawsze wysłać wartość końcową. Nie stosować coalescing do rozkazów shutdown, launch lub przycisków media.

Paho ma domyślnie nieograniczoną kolejkę outgoing (0 oznacza brak limitu). Ustawić świadomy limit i obsłużyć wynik publish; przy wymaganym potwierdzeniu używać on_publish/PUBACK, nie samego kodu przyjęcia do lokalnej biblioteki. [Paho Client API](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html).

### Baseline i mierzalne cele

Przed optymalizacją zebrać 30-minutowy idle po rozgrzaniu, GUI otwarte/zamknięte, broker online/offline, audio idle/aktywne, media i nakładki z/bez efektu; następnie 24–72 h soak. Rejestrować CPU procesu, private bytes, working set, uchwyty, wątki, wake-up, czas providerów, publikacje/s, głębokości kolejek i opóźnienia GUI. Nazwać sprzęt, konfigurację, zasilanie, build OS i funkcje włączone.

Proponowane cele akceptacyjne, **nie wyniki tego audytu**: idle bez capture poniżej 0,5% całego CPU na ustalonej maszynie referencyjnej; brak rosnącego trendu private bytes/uchwytów po powtarzalnym cyklu; brak blokady GUI powyżej 100 ms w zwykłych operacjach; lokalny feedback sterowania p95 <100 ms; kontrolowany shutdown w 5 s z jasnym wynikiem timeout; odtworzenie aktualnego stanu do 10 s od przywrócenia sprawnej sieci. Pamięć i wake-up otrzymują limit po baseline, nie arbitralną wartość bez danych.

Historyczne pomiary alpha.8 w dokumentacji dotyczą konkretnego capture/efektu i wcześniejszego środowiska. Nie dowodzą niskiego idle CPU całej obecnej aplikacji.

### Zależności

Wersje w tabeli to constraints projektu, a daty to daty publikacji sprawdzone w PyPI podczas audytu. Data ostatniego wydania jest sygnałem aktywności, nie gwarancją jakości ani wsparcia. Nie ma powodu wymieniać stabilnego Paho tylko dlatego, że wydaje rzadziej.

| Zależność | Wersja / publikacja | Wartość i koszt | Decyzja |
| --- | --- | --- | --- |
| [PySide6](https://pypi.org/project/PySide6/) | 6.11.2 / 2026-08-18 | Główne GUI, sygnały, ekrany, animacje; największy składnik pakietu | KEEP; Qt Widgets, bez dokładania QML/Fluent frameworka; świadoma linia Windows 10 |
| [comtypes](https://pypi.org/project/comtypes/) | 1.4.16 / 2026-03-02 | COM dla audio; koszt apartment/lifecycle | KEEP za adapterem |
| [pycaw](https://pypi.org/project/pycaw/) | 20251023 / 2025-10-23 | Dużo gotowej obsługi audio; projekt niszowy | KEEP, testy adaptera i przypięta wersja; własny pełny COM wrapper byłby droższy |
| [pywin32](https://pypi.org/project/pywin32/) | 312 / 2026-06-04 | WMI, DPAPI i Win32; obszerny, potrzebny | KEEP; jawny thread ownership |
| [paho-mqtt](https://pypi.org/project/paho-mqtt/) | 2.1.0 / 2024-04-29 | Dojrzały MQTT; własny loop i callbacki | KEEP, uprościć adapter; brak powodu budować własny MQTT |
| [psutil](https://pypi.org/project/psutil/) | 7.2.2 / 2026-01-28 | Procesy, CPU/RAM, dyski; użyteczny wspólny interfejs | KEEP, batch i cache |
| [websocket-client](https://pypi.org/project/websocket-client/) | 1.9.2 / 2026-08-31 | Direct na dedykowanym wątku | KEEP; nie dodawać drugiego stosu async tylko dla jednego socketu |
| [winrt Windows.Media.Control](https://pypi.org/project/winrt-Windows.Media.Control/) + Foundation, Collections, Storage.Streams | 3.2.1 / 2025-06-06 | Projekcje GSMTC i strumieni; kilka spójnych pakietów plus winrt-runtime | KEEP jako komplet wersji; przypiąć/testować zależność runtime |
| [qrcode](https://pypi.org/project/qrcode/) | 8.2 / 2025-05-01 | Kod QR w overlay; wąski zakres | KEEP, jeśli QR pozostaje funkcją; nie pisać własnego generatora |
| [Pillow](https://pypi.org/project/Pillow/) | 12.3.0 / 2026-07-01 | QR i obróbka obrazów; istotna granica bezpieczeństwa | KEEP tam, gdzie potrzebne; deklarować bezpośrednio, skoro jest importowane |
| [QtAwesome](https://pypi.org/project/QtAwesome/) / [QtPy](https://pypi.org/project/QtPy/) | 1.4.2 / 2.4.3 | Ikony i przejściowa warstwa zgodności | KEEP obecnie; lokalny mały zestaw SVG może później usunąć oba, gdy styl będzie stabilny |
| [dxcam](https://pypi.org/project/dxcam/) | 0.3.0 / 2026-03-12 | Capture; prywatne szczegóły API i zasoby GPU zwiększają ryzyko | Wyodrębnić jako opcjonalne; usunąć z podstawowego runtime, jeśli capture przestaje być wymagany |
| [NumPy](https://pypi.org/project/numpy/) | 2.5.2 / 2026-08-09 | Bufory capture, duży składnik; obecne constraint wymaga Python >=3.12 | Usunąć wraz z capture lub zadeklarować w tym extra; naprawić deklarowane minimum Python |
| [PyInstaller](https://pypi.org/project/pyinstaller/) | 6.22.2 / 2026-08-17 | Potrzebny packaging, duże znaczenie hooks/DLL | KEEP tylko build; test gotowego artefaktu |
| [pytest](https://pypi.org/project/pytest/) | 9.1.1 / 2026-06-19 | Podstawa suite | KEEP; więcej integracyjnego zachowania, mniej asercji struktury źródła |
| [Ruff](https://pypi.org/project/ruff/) | 0.16.2; nowsze 0.16.6 dostępne | Lint/imports, niski koszt | KEEP; aktualizacja po walidacji, nie finding bezpieczeństwa |
| [Bandit](https://pypi.org/project/bandit/) | 1.9.4 / 2026-02-25 | Skan typowych wzorców; nie wykrył lock inversion i błędów kontraktu | KEEP jako pomoc, bez traktowania zielonego wyniku jako audytu |
| [pip-audit](https://pypi.org/project/pip-audit/) | 2.10.1 / 2026-06-10 | Znane podatności zależności | KEEP, uruchamiać dla czystego release env i finalnego lock |

Bezpośrednie importy Pillow/NumPy nie powinny zależeć przypadkowo od zależności przechodnich qrcode/dxcam. constraints nie są kompletnym lockfile z hashami i nie deklarują wymagania pakietu. Dla aplikacji dystrybuowanej jako EXE wybrać jedną wersję Pythona do budowania i jawne wspierane środowisko source; obecne minimum 3.11 nie jest spójne z całym przypiętym zestawem.

Nowe zależności rozważałbym tylko dwie: testowy pytest-homeassistant-custom-component do realnego HA harness (alternatywa: samodzielny harness HA w Linux; koszt: dopasowanie do wersji HA i cyklu wydawniczego), oraz bezpośrednio zadeklarowane packaging do semver/prerelease (alternatywa: własny parser z testami; koszt dodatkowy mały, ale nadal wymaga przypięcia). Nie trzeba dodawać obu natychmiast. Typowanie można wdrażać etapami wybranym jednym checkerem w dev; nie zwiększa to runtime. Hypothesis jest opcją późniejszą, gdy deterministyczne generatory i testy stanów okażą się niewystarczające. Nie rekomenduję brokera eventów, kontenera DI, ORM ani nowego frameworka aplikacyjnego.


## 14. Reliability improvements

### Failure-mode analysis

| Awaria / zdarzenie | Co wynika z obecnego kodu | Docelowa izolacja i odzyskanie |
| --- | --- | --- |
| Pojedynczy sensor rzuca wyjątek | PollScheduler przechwytuje wyjątek, ogranicza powtarzane logi i zachowuje cache | Zachować izolację; dodatkowo quality=error/stale i last_success |
| Windows API nie wraca | Przechwytywanie wyjątków nie pomaga; blokuje wspólny scheduler lub lifecycle worker | Wolne klasy źródeł osobno; deadline, health i kontrolowana reinitializacja; nie próbować zabijać dowolnego wątku Python |
| Audio aplikacja znika podczas komendy | Adapter może zwrócić brak sesji/błąd; nazwa procesu nie oznacza trwałej instancji | Wynik target_gone; nowy snapshot; żadnego niejawnego skierowania do innej aplikacji |
| Zmienia się domyślne urządzenie audio | Rescan i select; obecnie błąd nieistniejącej metody discovery | Unsubscribe stary endpoint, przełączenie właściciela, stable ID, pełny stan |
| Nieprawidłowy artwork | Limity i weryfikacja części formatów; błąd odczytu może usunąć okładkę | Tani placeholder, ograniczony decode poza krytycznym GUI, zachować playback state |
| MQTT urywa połączenie w trakcie publish | Source cache może wyprzedzić publisher; możliwe C01 przy reconnect | Najnowszy stan niezależny od transportu; brak callbacków pod lockiem; replay aktualnej revision |
| HA/MQTT startuje później | Retained inventory/state i birth event są dobrym fundamentem | SUBACK → announce → snapshot → online; sprawdzić kolejność realnym brokerem |
| Broker niedostępny 10 min | Backoff istnieje; nie ma dowodu utraty całej aplikacji, ale stan po reconnect bywa stary | GUI i providery działają lokalnie; stan coalescowany, komendy nieodkładane bez końca |
| Wi-Fi znika / nowe IP / zmiana sieci | Transport reaguje na błąd/timeout | Jedna próba reconnect na generację; event sieci przyspiesza reakcję, nie tworzy drugiego loop |
| Kilka reconnectów jednocześnie | Kolejka operacji ogranicza część współbieżności; callbacki transportu mają osobne locki | Jeden właściciel lifecycle i idempotentne desired_connected; test interleavings |
| HA wysyła błędny JSON / zły typ | Większość parserów odrzuca; konkretny typ platform=[] obchodzi bezpieczną ścieżkę przez TypeError | Total parser: kontrolowany reject dla każdego typu wejścia, limit kosztu, bez restartu transportu |
| Komenda wykonana, ACK zgubiony | Dedup chroni część ponowień; legacy generuje nowe ID | Idempotency cache z wynikiem, request ID zachowany end-to-end; brak automatycznego retry niebezpiecznej akcji po niepewnym wyniku |
| Overlay nie może utworzyć efektu | Są fallbacki render/capture | Dostarczyć czytelny panel bez efektu; engine i transport działają dalej |
| Kolejka overlay pełna / lock | ACK może poprzedzać decyzję engine | accepted/rejected dopiero po decyzji; displayed osobno; jawne queue_full/session_locked |
| Odłączenie ekranu | QScreen/display triggers, lecz capture ma własne zasoby/cache | Przenieść aktywne karty do dostępnego work area; zamknąć zasoby starego output; odrzucić stare callbacki |
| Sleep przez kilka godzin | Native events i suspend/resume istnieją | Unieważnić stare lease/deadlines, odtworzyć COM/WinRT/capture według potrzeby, nowy snapshot |
| Explorer restart | Istnieje TaskbarCreated handling | Tray wraca bez drugiego QApplication i bez restartu wszystkich usług |
| Zapis profilu się nie powiedzie | Atomic replace ogranicza częściowy plik; apply może już zatrzymać działające usługi | Walidacja i zapis kandydata przed commit stanu; rollback usług/config i jednoznaczny rezultat |
| Zapis profilu się uda, autostart zawiedzie | Odtworzono profil nowy/runtime stary i wyjątek | Autostart jako jawny efekt uboczny z własnym wynikiem; transaction/compensation przy wymaganym wspólnym apply |
| Uszkodzony profil / błąd DPAPI | Normalny start może zakończyć się błędem bez przyjaznego recovery | Bezpieczny ekran odzyskiwania, kopia poprzedniego profilu, brak cichego resetu sekretów |
| Shutdown podczas query/command/capture | Część usług raportuje stop, część ma timeout bez potwierdzenia zakończenia | Wspólny kontrakt stopped/timeout; odpiąć wejścia; żadnego nowego work po STOPPING |

### Zasady odporności

**Exception isolation nie oznacza time isolation.** Dzisiejszy PollScheduler dobrze radzi sobie z wyjątkiem, ale nie z wywołaniem WMI zawieszonym na kilka minut. Nie potrzeba procesu na każdy sensor: rozdzielenie audio, wolnego system I/O i media wystarczy jako pierwszy krok. Proces pomocniczy rozważyć tylko dla udokumentowanego, nieanulowalnego providera, którego awaria nadal blokuje zamknięcie.

**Stary wynik musi mieć wiek.** Użyteczna jest ostatnia znana temperatura, ale HA powinien rozróżniać aktualny odczyt od tego sprzed godziny. Pause oznacza świadome wstrzymanie aktualizacji, nie „wszystko jest zdrowe”. Brak hardware capability nie jest równy chwilowemu timeoutowi.

**Monotonic dla czasu lokalnego.** Po przyjęciu komendy TTL zamienić na lokalny deadline; UTC służy do sprawdzenia wejściowego okna i diagnostyki. Po zmianie zegara albo resume nie wydłużać życia starego rozkazu. Eventy i callbacki zawierają generation/session, aby odpowiedź starego workera nie nadpisała nowego stanu.

**Kontrolowane zatrzymanie i wynik.** Provider nie udaje, że jest zatrzymany, gdy join timeout upłynął. ServiceSupervisor już ma użyteczną obsługę zależności i zachowania niezatrzymanej usługi; rozciągnąć taki kontrakt na MediaController, capture i pomocnicze workery. W top-level desktop użyć jednoznacznego finally dla zasobów utworzonych przed wejściem do event loop.

**Degradacja jest stanem produktu.** Brak temperatury GPU nie wyłącza audio. Brak MQTT nie wyłącza lokalnego GUI. Brak artwork nie zatrzymuje media. Brak efektu nie usuwa powiadomienia. Nie naprawiać wszystkiego globalnym restartem „Application”.

## 15. Testing strategy

### Co faktycznie wykonano w tym audycie

Środowisko: Windows, lokalna .venv, Python 3.13.5, HEAD wskazany na początku raportu. Testy Qt uruchomiono przez offscreen. Nie uruchamiano komend zmieniających głośność, zamykających aplikacje ani wyłączających komputer.

| Weryfikacja | Wynik i zakres |
| --- | --- |
| Cały istniejący pytest suite | **274 passed w 17,37 s**, 34 pliki; cache pytest wyłączony, artefakty w katalogu tymczasowym |
| Ruff check --no-cache . | PASS |
| Bandit dla obu pakietów, medium/high | Brak medium/high; jeden low dotyczy random jitter; istnieje 11 nosec |
| pip check | PASS |
| pip-audit --local | Brak znanych podatności znalezionych przez narzędzie; lokalny projekt pominięty, editable metadata nadal 2.0.0a3 |
| AST całej produkcji | 85 modułów, 13 430 linii; 132 wewnętrzne krawędzie importów, brak cykli importów |
| Qt wizualnie | Obejrzano sześć renderów stron głównego shell z testu; nie jest to test natywnego DWM/Snap/DPI |
| DPAPI / WinRT / odczyty systemowe | Istniejące testy i odczyty bezpieczne; dodatkowe próby COM/WMI opisane niżej |

Uruchomienie suite: Python -B -m pytest -p no:cacheprovider z QT_QPA_PLATFORM=offscreen i osobnym --basetemp. Pełne testy nie oznaczają, że wszystkie obsługiwane scenariusze zostały przetestowane. Nie zmieniano testów po to, aby uzyskać wynik.

### Dodatkowe próby regresyjne bez zmiany plików źródłowych

Próby wykonano jako izolowane skrypty używające rzeczywistych klas i kontrolowanych doubles. Tam, gdzie potrzebny był HA, wykorzystano pomocniczy harness testów projektu, a nie zainstalowany Home Assistant.

| ID | Układ próby | Zaobserwowany wynik |
| --- | --- | --- |
| P01 | TelemetryService + StatePublisher; głośność 20 → 80, send kończy się niepowodzeniem, reconnect | Replay wysyła 20; kolejny odczyt 80 nie publikuje, bo source cache już ma 80 |
| P02 | Rzeczywista metoda monitorowania audio output i lista testowego urządzenia | AttributeError dla _publish_discovery |
| P03 | HA update_overlay z notification_id i samym progress=65 → rzeczywisty engine | Tytuł i wiadomość wcześniej istniejącej karty zostają wyczyszczone/zastąpione domyślnymi |
| P04 | Rzeczywista klasa HAWindowsAppVolumePlayer z bazą i double HA Entity | async_added_to_hass zgłasza brak _unsubscribers |
| P05 | Aktualna 2.0.0-alpha.8, GitHub release v2.0.0 | Updater nie uznaje stabilnego wydania za nowsze |
| P06 | Gateway + transport + publisher + connection machine; dwa wątki i bariery w istniejących punktach wywołań | Oba wątki zablokowane w przeciwnym porządku locków; deadlock potwierdzony bez brokera |
| P07 | To samo zapytanie WMI z nowego wątku bez COM, następnie z CoInitialize | Bez COM com_error; po inicjalizacji poprawny odczyt CPU |
| P08 | MSFT_PhysicalDisk: samo HealthStatus i następnie HealthStatus,Temperature | Pierwsze zapytanie działa; drugie Invalid query |
| P09 | Announcement dla 63/64/128 włączonych aplikacji | 255 encji przechodzi; 259 i 515 odrzucane przez limit 256 |
| P10 | Announcement z platform=[] | TypeError: unhashable type: list |
| P11 | Apply: zapis profilu działa, StartupManager.set_enabled rzuca wyjątek | Nowy zapisany host, stary runtime/config; błąd apply, brak odbudowy usług w badanej ścieżce |
| P12 | Prawdziwy AppCard/Qt: klawisz Right na sliderze 50 | UI pokazuje 51, brak sygnału volume_requested |

Dla P06: publikacja trzyma lock publishera i odczytuje ConnectionMachine.state; callback connected trzyma lock stanu i wchodzi przez EventBus/Gateway do replay publishera. Bariera jedynie deterministycznie wymusza możliwy porządek, nie dodaje nowego locka do produktu. Potwierdzenie dotyczy deadlocku wewnątrz procesu, nie konkretnego czasu jego wystąpienia w produkcji.

Sprawdzono również głęboko zagnieżdżone JSON-y; badane przykłady zostały odrzucone. Nie wpisano nieodtworzonego RecursionError jako potwierdzonej podatności.

### Jakość obecnych testów

**Wartościowe:** czysta kolejka nakładek, pozycjonowanie/work area, formaty i walidacja poleceń, dedup, części lifecycle i cleanup, uprawnienia HA, DPAPI, bezpieczne komendy Windows, layout bez Qt warnings. Te testy zachować jako ochronę migracji.

**Luki:** liczne testy integracji HA wyciągają fragmenty AST i tworzą moduły zastępcze. Sprawdzają wybrany fragment, lecz pomijają kontrakty faktycznej klasy Entity, właściwy runtime_data i importy wspieranej wersji HA. To pozwala na 274 PASS przy H02 i H05. Część testów sprawdza obecność pól/napisów w źródle; test GPU utrwala nieprawidłowy sens wartości „RPM”. Test starego SettingsStore nie dowodzi poprawności transakcji nowego profilu. Brakuje realnego transportu, długiego biegu i pomiaru całego procesu.

### Docelowe warstwy testów

| Warstwa | Konkretne scenariusze | Warunek zaliczenia |
| --- | --- | --- |
| Pure domain | Command envelope, TTL, dedup, capability/state revision, queue/pinned/expiry/PATCH, placement | Bez Qt/Windows/HA; deterministyczny zegar i małe przypadki graniczne |
| Core/lifecycle | Start twice, stop during start, stop timeout, config rollback, stale callback po generation change | Brak nowej pracy po STOPPING; zachowany jeden właściciel |
| Concurrency | P06, publish-fail-reconnect, simultaneous reconnect, shutdown during callback | Deterministyczne bariery; brak sleep-based flaky race tests |
| Protocol contract | Windows encoder ↔ HA decoder, limity 63/64/128 apps, nowe/nieznane pola, wszystkie zarejestrowane komendy | Wspólne fixtures; obie strony zgadzają się na wynik i błąd |
| MQTT integration | Realny lokalny broker, birth/LWT/SUBACK, restart brokera/HA, 10 min outage, utrata ACK | Aktualny stan po recovery; brak retained execution i powielenia efektów |
| Direct integration | Auth failure, lease expiry, invalid result, disconnect z pending, uprawnienia target/source | Futures kończą się raz; ograniczone kolejki; brak dostępu do cudzej encji |
| HA real runtime | Config flow min/latest, setup/unload/reload, wszystkie platformy, partial subscribe fail, registry migration, services/translations | Test na Linux z prawdziwym HA; brak opierania wyniku wyłącznie na AST |
| Windows adapter | COM init/cleanup, znikająca sesja, endpoint change, brak WMI provider, disk query, NVIDIA units, błędy API | Część z doubles; oznaczony smoke na prawdziwym Windows |
| Qt interaction | Keyboard/wheel/drag final value, focus, tab order, disabled/busy, dirty Apply, zamknięcie widoku podczas callbacku | Sygnał i efekt zgodne z UI; zero QObject/thread warnings |
| Overlay rendering | Long text/Unicode, null art, oversize/decompression, low work area, mixed DPI, retiring cards | Czytelny fallback, limit zasobów, brak wyjścia poza ekran |
| Release smoke | Czysta maszyna bez source/.venv, install/upgrade/uninstall/autostart, podpis i dependencies | Uruchomienie faktycznie dystrybuowanego EXE |
| Soak/fault | 24–72 h, sleep/resume, lock, Explorer restart, ekran hotplug, reconnect storm | Stabilne liczniki pamięci/uchwytów, brak zablokowanych usług, mierzalny recovery |

Oddzielić od Qt/Windows: modele stanu i health, reguły coalescing, command routing policy, konfigurację i migracje, lifecycle policy, notification queue/update/placement, parsery i capability mapping. Adaptery pozostają małe i testowane kontraktem; nie trzeba udawać całego Windows przez setki mocków.

Kolejność dodawania testów: C01 i H01 → HA entity setup/import minimum → COM/WMI i config apply → overlay ACK/PATCH → reconnect/lifecycle → reszta macierzy. Coverage pomaga znaleźć ślepe miejsca, ale nie zastąpi scenariusza. Wymóg >95% pokrycia z wyższych poziomów HA IQS nie jest automatycznym dowodem jakości ani deklaracją, że ten projekt ma taki wynik.

### Granice tej weryfikacji

Nie wykonano pełnego HA runtime, nowego builda ani instalacji/uninstall. Nie sprawdzono rzeczywistego brokera, RDP/HDR, natywnego Mica/Snap, mixed DPI, fizycznego sleep/resume, odłączania monitorów ani 24/7 soak. Przegląd statyczny i offscreen nie potwierdzają tych zachowań. Dokumentacja wcześniejszych alpha zawiera odrębne, historyczne wyniki. Audyt nie przypisuje ich sobie.


## 16. New feature ideas

Nowe funkcje mają korzystać z uporządkowanego stanu, uprawnień i lifecycle. Rozbudowa katalogu sensorów przed usunięciem H01/H03 zwiększy liczbę pozornie działających encji.

| Kategoria | Pomysł | Wartość dla Windows + HA | Warunek / koszt |
| --- | --- | --- | --- |
| QUICK WINS | „Dlaczego encja jest niedostępna?” | Rozróżnia brak urządzenia, disabled, błąd Windows i sieci | Health/reason codes; największy zysk po StateStore |
| QUICK WINS | Lokalny test połączenia krok po kroku | DNS/TCP/TLS/auth/subscription/HA integration pokazane osobno | Wykorzystać istniejące transporty, nie osobny drugi klient |
| QUICK WINS | Podgląd danych przy przełączniku funkcji | Użytkownik widzi, co faktycznie udostępnia do HA | Wspólny snapshot i privacy preview |
| QUICK WINS | Kopiowanie gotowej akcji HA dla wybranej nakładki | Krótsza droga od preview do automatyzacji | Generować z tego samego schematu co service |
| QUICK WINS | Dismiss wszystkich nakładek i chwilowe wyciszenie z tray | Szybka kontrola lokalna podczas pracy | Jawny status w GUI/HA i automatyczny powrót |
| QUICK WINS | Eksport diagnostyki z podglądem redakcji | Mniej przypadkowych ujawnień w zgłoszeniach | Allowlista i widoczna zawartość eksportu |
| MEDIUM | Reguły obecności komputera | Aktywny użytkownik, locked, idle, fullscreen i media tworzą użyteczny kontekst automatyzacji | Rozdzielić fakty od heurystyk; polityka prywatności |
| MEDIUM | Profile pracy: spotkanie / gra / noc | Zestaw ustawień lokalnych, audio i nakładek aktywowany z HA lub tray | Deklaratywne preset actions, bez dowolnego skryptu |
| MEDIUM | Stabilny wybór sesji/aplikacji media | Sterowanie wskazaną aplikacją zamiast zawsze „obecną” | Trwała tożsamość targetu i target_gone |
| MEDIUM | Polityka ciszy zależna od lock/fullscreen/pory dnia | Powiadomienia domu nie zakłócają prezentacji lub gry | Jedno miejsce rozstrzygające show/queue/drop; jawny rezultat |
| MEDIUM | Overlay z odliczaniem do zadania i aktualizowanym postępem | Pranie, ładowanie auta, backup, drukowanie | PATCH, stable notification_id, expiry i powrót po reconnect według polityki |
| MEDIUM | Per-monitor presets i „pokaż na aktywnym monitorze” | Lepsza ergonomia na kilku ekranach | Stabilne ID, fallback i respektowanie work area |
| MEDIUM | Historia zdarzeń technicznych, bez treści prywatnych | Wyjaśnia „o której przestało działać” | Mały rotowany log, kody błędów, retencja i redakcja |
| MAJOR | Kontrolowane akcje zwrotne nakładki do HA | „Potwierdź”, „odłóż”, „otwórz widok” bez przełączania aplikacji | Nie wykonywać arbitralnych usług z payloadu; ograniczone identyfikatory akcji, ACL i dedup |
| MAJOR | Polityki lokalne działające offline | Komputer sam zachowuje się poprawnie po utracie HA | Mały, ograniczony zestaw reguł; nie tworzyć drugiego Home Assistant |
| MAJOR | Pełniejszy Direct dla wybranych capability | Użytkownik bez MQTT może korzystać z większej części produktu | Dopiero gdy istnieje wspólny protokół; policzyć koszt parity i utrzymania |
| FUTURE / EXPERIMENTAL | Energy Saver / battery-aware automation | Mniej polling/capture na baterii, stan dla automatyzacji domu | Najpierw niezawodna informacja o źródle zasilania |
| FUTURE / EXPERIMENTAL | Natywne Windows notification history / toasts | Powiadomienie dostępne po zniknięciu overlay | Osobny adapter i zgody; nie utożsamiać z obecnym tray balloon |
| FUTURE / EXPERIMENTAL | Kontrolowane scenariusze wybudzenia | HA budzi PC, Bridge raportuje osiągnięcie gotowości | Wake-on-LAN po stronie HA/firmware; uśpiony proces sam nie odbierze rozkazu |
| FUTURE / EXPERIMENTAL | Profile RDP / wielu sesji użytkowników | Poprawne audio/powiadomienia przy zmianie sesji | Duży koszt semantyki tożsamości i uprawnień; wymaga osobnego projektu |
| FUTURE / EXPERIMENTAL | Natywny backdrop lub capture wysokiej jakości | Lepszy efekt wizualny | Wyłącznie po spełnieniu budżetów idle i macierzy Win10/11/HDR |

Najwyższą wartość na teraz mają wiarygodny health, prosty onboarding, podgląd publikowanych danych i przewidywalne notifications. Nie rekomenduję dodawania dowolnego zdalnego PowerShell, globalnego keyloggera, stałego streamingu pulpitu ani rozbudowanego edytora automatyzacji. Nie wynikają z podstawowej potrzeby mostka i znacząco zwiększają powierzchnię utrzymania.

## 17. Breaking changes, które warto zaakceptować

| Zmiana | Dlaczego warto | Jak ograniczyć szkodę migracji |
| --- | --- | --- |
| Nowy kontrakt protocol v3 | State revision/session, wyniki komend, capability semantics i jeden PATCH | Negocjacja wersji; przejściowy adapter v2 z datą wycofania, bez rozbudowy starego formatu |
| Trwały device UUID i capability IDs | Hostname/process display name nie są tożsamością | Migrować istniejące identyfikatory; nowe UUID tylko gdy poprzedniego nie można zachować/odtworzyć |
| Jeden config entry HA dla MQTT + Direct | Jedno urządzenie, jeden popup i jasna dostępność | Migracja encji/rejestru, zachowanie entity_id i automatyzacji tam, gdzie znaczenie jest to samo |
| Mniej domyślnych encji dublujących media/number/switch | Mniej clutter i prostsze discovery | Zachować istniejące włączone encje; nowe instalacje dostają rozsądne defaults |
| Usunięcie dynamicznego kasowania sensorów | Chwilowy błąd nie usuwa tożsamości/history | Capability może być unavailable; jawne usuwanie wycofanej funkcji |
| Korekta fan RPM → % i semantyki mikrofonu | Dane muszą oznaczać to, co opisuje nazwa i jednostka | Nie mieszać historycznych RPM z procentami; migracja jednostki/nowa poprawna encja według reguł HA |
| Przebudowany model notification/PATCH/ACK | Zapobiega utracie treści i fałszywemu potwierdzeniu | Konwerter starych show/update; opisane defaults, rozdzielenie notification_id i command_id |
| Capture glass przestaje być domyślnym wymaganiem | Mniejszy koszt i ryzyko dla procesu 24/7 | Zachować opt-in przez adapter, gdy wspierany; zawsze poprawny fallback |
| Zmiana konfiguracji i Apply | Public config, sekrety i runtime mają spójny commit | Migrator, kopia przed zmianą, dry-run walidacji, możliwość odzyskania profilu |
| Wyższe jawne minimum Python/HA | Obecne deklaracje nie odpowiadają API/pinom | Wybrać minimum potwierdzone CI, komunikat kompatybilności przed upgrade |
| Węższe legacy command routes | Pełne TTL/dedup i jednoznaczny target | Mapowanie przez adapter tylko przez okres przejściowy; nie zmieniać po cichu skutków power commands |

Nie trzeba chronić nieprawidłowego kontraktu tylko dlatego, że jest obecny. Jednocześnie utrata entity_id i automatyzacji użytkownika jest realnym kosztem produktu; migracja to część implementacji, nie zadanie pozostawione odbiorcy.

## 18. Migration/rewrite strategy

Wdrożyć strategię **B w istniejącym repozytorium**, w małych przekrojach od źródła Windows do encji i komendy zwrotnej. Wersja kodu już jest 2.0.0-alpha.8. Kolejne repozytorium i etykieta „2.0 od nowa” nie rozwiążą problemów ownership.

1. **Zamrozić punkt odniesienia.** Zachować fixtures aktualnych payloadów/profili, inventory funkcji, wyniki testów i artefakt alpha.8. Ustalić, które zachowania są intencjonalne, a które są błędami i nie mogą zostać golden master.
2. **Usunąć blokery niezawodności w obecnym przepływie.** Reprodukcje C01/H01/H02/H03/H05/H09 stają się testami. Naprawy są ograniczone; nie czekają na nowy shell.
3. **Wprowadzić StateStore/StateOutbox na jednym pionowym przekroju: master audio.** Lokalny odczyt, GUI, MQTT snapshot i komenda HA korzystają z jednego modelu. Dopiero gdy reconnect i stop są poprawne, przenosić kolejne capability.
4. **Wprowadzić protokół i HA równocześnie.** Windows encoder oraz HA parser mają wspólne fixtures; wersja jest negocjowana przed tworzeniem encji. Przejściowy adapter starego formatu jest na brzegu, nigdy wewnątrz nowej domeny.
5. **Przenosić ownership providerów.** Audio → media → kontekst → wolne WMI/system. Adapter OS może początkowo wywoływać istniejący kod, lecz publikuje nowy typ wyniku i ma jeden lifecycle.
6. **Przebudować overlay host i model aktualizacji.** Zachować czysty engine/placement po rozszerzeniu kontraktu. Jeden kanał przyjęcia decyduje o kolejce, lock policy i ACK. Zamienić presentation/glass bez dwóch jednoczesnych właścicieli tych samych okien.
7. **Przebudować GUI na nowym stanie.** Nowe strony nie odczytują Windows bezpośrednio. Draft konfiguracji i runtime są widoczne osobno. Usunąć stare komponenty dopiero po przełączeniu odpowiednich ekranów.
8. **Ukończyć migrację HA/release.** Ćwiczyć upgrade/downgrade/recovery w czystym profilu. Zakończyć okres zgodności, usunąć adaptery i instrukcje nieaktualnej konfiguracji.

Nie uruchamiać starych i nowych writerów równolegle na tym samym komputerze/broker prefixie. Weryfikacja shadow może porównywać odczyty bez publikacji i bez wykonywania komend; nie powinna podwajać kosztownych providerów w zwykłym runtime. Flagi migracyjne służą rozwojowi i mają termin usunięcia, nie stają się trwałą macierzą ustawień użytkownika.

**Rollback:** poprzedni podpisany artefakt, kopia profilu sprzed migracji, opis granic downgrade protokołu i rejestru HA. Sekretów nie eksportować do jawnego pliku „na wszelki wypadek”. Usuwanie starych retained topics wymaga znanego poprzedniego inventory i własnego prefixu; nie wykonywać szerokiego wildcard cleanup obcych danych.

**Warunek zmiany strategii:** gdy rzeczywisty vertical slice wykaże, że zachowane adaptery nie dają się izolować bez przeniesienia większości odpowiedzialności, wymienić konkretny adapter. Nie jest to powód, żeby z góry wyrzucić całą aplikację, GUI toolkit i silnik kolejki.

## 19. Implementation roadmap

Roadmapa jest projektem prac, nie opisem wykonanych zmian. Kolejność zachowuje priorytet reliability → architecture → security → performance → maintainability → HA/Windows → UX/polish → nowe funkcje. HA uczestniczy od fazy 0/2; faza 6 nie oznacza odłożenia błędów HA na koniec.

### Phase 0 — baseline, reprodukcje i blokery

| Pole | Ustalenie |
| --- | --- |
| Zakres | Dodać deterministyczne regresje P01–P12 według priorytetu; naprawić deadlock, stan po send failure, HA entity setup/minimum, COM i apply failure; zebrać baseline |
| Zależności | Brak; korzysta z obecnego repo i fixture danych |
| Ryzyko | Pozorne naprawienie pojedynczej ścieżki bez testu drugiego transportu/lifecycle |
| Usunięcie starego | Tylko oczywiste artefakty terminala; nie usuwać zachowania potrzebnego do porównania |
| Definition of done | Regresje C/H przechodzą; istniejące 274 testy bez utraty zakresu; min/latest HA setup sprawdzony; raport metryk procesu z konfiguracją referencyjną |

### Phase 1 — application core i ownership

| Pole | Ustalenie |
| --- | --- |
| Zakres | ComputerState/health, StateOutbox, generacje, lifecycle owner, wspólny kontrakt stop, atomowy apply/rollback; pionowy master audio |
| Zależności | Phase 0 i ustalone fixtures/semantyka stanu |
| Ryzyko | Dwa cache uznane za źródło prawdy, callbacki starej generacji |
| Usunięcie starego | Source _last_* dla przeniesionych capability, bezpośrednie publikacje z ich providerów, zbędne wildcard events |
| Definition of done | Master audio GUI↔Windows↔HA działa przez nowy stan; publish failure nie gubi zmiany; start/stop/reconfigure wielokrotnie bez nadmiarowych workerów i callbacków |

### Phase 2 — communication i wspólny kontrakt HA

| Pole | Ustalenie |
| --- | --- |
| Zakres | Protocol v3, capabilities/snapshot, command/results, SUBACK/PUBACK policy, bounded outbox, MQTT i Direct adapters, HA parser/runtime |
| Zależności | Phase 1; nie wymaga nowego GUI |
| Ryzyko | Niekompatybilny upgrade jednego końca, błędne retry nieidempotentnych akcji |
| Usunięcie starego | Dublowane parsowanie/routery; stare formaty zostają wyłącznie w tymczasowym compatibility adapter |
| Definition of done | Wspólne contract tests; real broker/Direct reconnect; najnowszy snapshot po awarii; brak podwójnego efektu przy utracie ACK; jasny komunikat niekompatybilności |

### Phase 3 — Windows providers i energia

| Pole | Ustalenie |
| --- | --- |
| Zakres | Jeden właściciel audio COM, eventy audio/GSMTC/WTS/display/network; wolny system I/O osobno; poprawne źródła/jednostki; adaptacyjny polling |
| Zależności | Phase 1–2; przenoszenie capability stopniowo |
| Ryzyko | Callback lifetime, znikające urządzenia, specyfika różnych sterowników |
| Usunięcie starego | Monolityczne fragmenty SystemMonitor po przeniesieniu, osobne UI enumeracje, powtarzane polling paths |
| Definition of done | Audio/media/system nie blokują wzajemnie pracy; hotplug i API failures mają health; testy Win10/11 oraz udokumentowany spadek zbędnych odczytów |

### Phase 4 — overlay jako osobny subsystem

| Pole | Ustalenie |
| --- | --- |
| Zakres | Typed notification/PATCH, kolejka przed Qt, accepted/displayed/rejected, lock/fullscreen policy, monitor IDs, host/presentation, wspólny motion |
| Zależności | Protocol/results z Phase 2; media/context z Phase 3 |
| Ryzyko | Regresja lifetime/pinned/replacement i koszt renderowania |
| Usunięcie starego | Rozproszone coercions/defaults, stary ingress, dublujące timery, stały capture z podstawowej ścieżki |
| Definition of done | Wszystkie typy overlay, update/pinned/hover/expiry, przeciążenie i odłączenie ekranu sprawdzone; zero fałszywych sukcesów; poprawny fallback i reduced motion |

### Phase 5 — GUI i lokalne doświadczenie użytkownika

| Pole | Ustalenie |
| --- | --- |
| Zakres | Onboarding, overview health, computer/application views, overlay editor, draft/apply, diagnostics i tray; jedna paleta/tokeny |
| Zależności | StateStore i docelowe komendy; Phase 4 dla pełnego preview |
| Ryzyko | Ładne makiety bez spójności runtime, utrata klawiatury/focus i lokalnych funkcji offline |
| Usunięcie starego | Nieużywane ui_components, stare strony shell, zbędne theme/helpers po przełączeniu |
| Definition of done | Główne zadania wykonane myszą i klawiaturą; dark/light/system accent, mała wysokość, mixed DPI; wszystkie pokazane statusy pochodzą z rzeczywistego stanu |

### Phase 6 — HA jakość, rejestr i migracje

| Pole | Ustalenie |
| --- | --- |
| Zakres | Jeden entry, stabilne IDs, entity migration, services UX, tłumaczenia, Repairs, diagnostics, obsługiwane minimum i aktualny HA |
| Zależności | Runtime/protokół już istnieje od Phase 2; wszystkie przeniesione capability |
| Ryzyko | Utrata entity_id/historii lub automatyzacji, częściowy setup/unload |
| Usunięcie starego | Dynamiczne kasowanie registry, dublujące entry i legacy discovery po zakończeniu okresu przejściowego |
| Definition of done | Upgrade z reprezentatywnych profili; min/latest HA suite; unload bez subskrypcji/futures; encje zachowują tożsamość; błędy i limity czytelne |

### Phase 7 — release, soak i polish

| Pole | Ustalenie |
| --- | --- |
| Zakres | Soak 24–72 h, fault matrix, finalne motion/accessibility, podpisany build, installer upgrade/uninstall, dokumentacja i release gates |
| Zależności | Wszystkie poprzednie fazy oraz zakończony plan migracji |
| Ryzyko | Zachowania niewidoczne w .venv/offscreen, regresje sterowników i pakowania |
| Usunięcie starego | Temporary adapters/flags, martwe moduły, stare instrukcje „current”; zachować wyraźnie oznaczone archiwum historyczne |
| Definition of done | Brak Critical/High z audytu; spełnione budżety referencyjne; stabilny soak; czysty install/upgrade/uninstall; sprawdzony finalny artefakt i kompletny recovery guide |

Nie podaję pozornie precyzyjnej liczby dni bez znajomości dostępności wykonawcy, sprzętu testowego i kosztu real HA/Windows CI. Każda faza ma jednak mierzalny wynik i można ją oszacować osobno po pionowym przekroju Phase 1. Nowe funkcje z sekcji 16 wchodzą dopiero po odpowiednich bramkach jakości.

## 20. Final recommendation

**Gdybym przejmował ten projekt dzisiaj, zrobiłbym bardzo głęboki refaktor według strategii B: wymieniłbym model stanu i publikacji, uporządkował właścicieli usług i wątków, zaprojektował wspólny protokół z HA, przebudował host nakładek oraz główne przepływy GUI, zachowując wartościowe adaptery Windows i czyste algorytmy.**

Pierwsza decyzja implementacyjna dotyczyłaby niezawodności: żadnych callbacków pod lockiem stanu, żadnego utożsamiania „ostatnio odczytane” z „dostarczone”, żadnego sukcesu powiadomienia przed decyzją engine. Zaraz potem naprawiłbym realny setup encji HA, COM w workerach i transakcję konfiguracji.

Zachowałbym Python, PySide6/Qt Widgets, Paho, DPAPI, bezpieczne ograniczone komendy, dedup, NotificationEngine i placement po wymaganych rozszerzeniach. Wymieniłbym granice odpowiedzialności, które dzisiaj pozwalają lokalnemu błędowi zamienić się w nieaktualny stan całego urządzenia.

Strategia A jest zbyt mała, bo problem nie sprowadza się do kosmetyki plików. Strategia C w sensie równoległej nowej aplikacji i strategia D zwiększyłyby ryzyko ponownego odkrywania trudnych zachowań Windows bez proporcjonalnego zysku. Selektywna wymiana subsystemów daje najlepszy stosunek jakości do złożoności, ryzyka i kosztu przyszłego utrzymania.

Docelowy produkt ma przede wszystkim mówić prawdę o swoim stanie i kończyć pracę przewidywalnie. Nowoczesny Windows UX, płynny motion i nowe możliwości Windows + HA powinny powstać na tym fundamencie.

---

Raport jest niezależną oceną bieżącego kodu i projektem dalszych prac. W ramach tego etapu nie wdrożono zmian w aplikacji, integracji HA ani testach.

