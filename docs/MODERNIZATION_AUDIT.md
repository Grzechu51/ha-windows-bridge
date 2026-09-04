# Modernizacja HA Windows Bridge — audyt

Stan bazowy: `320c1ec` (`0.10.0-beta.5`), 2026-09-03. Gałąź robocza: `codex/fluent-rebuild`.
Test bazowy: **177 passed**, 10,87 s, Windows / Python 3.13 / Qt offscreen.

Status po wdrożonych partiach i wyniki testów: [raport końcowy etapu lokalnego](MODERNIZATION_FINAL_AUDIT.md).
Poniższa lista opisuje stan bazowy, nie listę nadal otwartych usterek.

## Zakres i ograniczenia

Przegląd obejmuje strukturę całej aplikacji, konfigurację, transporty i protokoły,
GUI, nakładki, adaptery Windows, integrację HA, testy, build i publikację.
Najważniejsze ścieżki sprawdzono w kodzie; hipotezy wymagające rzeczywistego
Windows/HA zaznaczono osobno. To nie jest certyfikacja bezpieczeństwa ani pomiar
CPU/GPU na sprzęcie użytkownika. Offscreen nie potwierdza DWM, Snap ani sleep/resume.

## Źródła i decyzje

Nie skopiowano kodu z projektów referencyjnych. Nie dodajemy zależności.
Identyfikatory licencji poniżej pochodzą z repozytoriów; nie stanowią opinii prawnej.

| Repozytorium / rewizja | Przejrzane obszary | Wniosek |
| --- | --- | --- |
| [Home Assistant Core](https://github.com/home-assistant/core), `357c6f56162a0269e86a36aa1ad66d6af222c282`, Apache-2.0 | REST / Shelly: koordynatory, setup, lifecycle; dokumentacja config flow, diagnostics, unload | Push i wspólne dane zamiast pollingu każdej encji; oficjalne callbacki cleanup i diagnostyka. Nie wprowadzać koordynatora tylko dla nazwy. |
| [Deskmate](https://github.com/JakubWawrzola/deskmate), `917f2116477915ee3a3bdda13af01ed0cbde9a17`, MIT | Struktura Rust/Tauri, StatusPage, opis transportów i granic uprawnień | Rozdzielić stan połączenia od prezentacji. Zachować opt-in i jawny zakres bezpośredniego połączenia. Nie migrować do Tauri ani kopiować własnej kryptografii Link. |
| [WinUI Gallery](https://github.com/microsoft/WinUI-Gallery), `7a8a6aa6f432bee71b89aeb24c3e69a5b854dc4f`, MIT | NavigationView, motywy Acrylic, InfoBar, Settings | Główna referencja wizualna: hierarchia typografii, responsywna nawigacja, spójne karty i statusy. Qt pozostaje silnikiem. |
| [PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets), `356665d9db87090db43305b98ac6cde2071d8f4d`, GPL-3.0 | SettingCard, NavigationInterface, organizacja motywów | Własne niewielkie komponenty PySide6 i stabilne klucze nawigacji. Bez importowania biblioteki i bez kopiowania implementacji. |
| [CustomWindow](https://github.com/re7gog/CustomWindow), `8c430ccd4119d0e1fac49ef4234d0615867418eb`, MIT, archiwum | custom_window.py, window_effects.py: DPI, taskbar, DWM | Referencja pułapek frameless, nie gotowa zależność. Preferować udokumentowane API; Snap wymaga osobnych testów na Windows. |
| [pyqttoast](https://github.com/niklashenning/pyqttoast), `bdc7e600273bea7f51595958ebe294a6ab0b1ae2`, MIT | toast.py: limit równoczesnych kart, kolejka, hover, duration bar, animacje | Rozdzielić kolejkę i geometrię od Qt; zachować nasze update/remove i zatrzymanie pozostałego czasu na hover zamiast resetowania timeoutu. |

## Critical

Nie potwierdzono problemu kategorii Critical. Nie oznacza to wykluczenia wszystkich
podatności. Zdalne akcje są opt-in; retained commands są odrzucane, payloady mają
limity, uruchamianie programów nie korzysta z dowolnego zdalnego polecenia shell.

## High

| ID / gdzie | Problem i skutek | Rozwiązanie | Ryzyko zmiany | Referencja | Nowa zależność |
| --- | --- | --- | --- | --- | --- |
| H1 `data_exchange._redact`, logging | Redakcja tekstu nie usuwa dokładnych wartości sekretów; np. `Authorization: Bearer ...` może pozostawić token. `extra` nie jest filtrowane rekurencyjnie. | Wspólny redaktor sekretów dla formatterów i całej diagnostyki, testy nagłówków/JSON/traceback. | Niskie; możliwe nadmierne ukrywanie diagnostyki. | HA diagnostics / Deskmate privacy | Nie |
| H2 `direct_bridge._connect/stop` | Błąd recv/send w handshake omija close; stop zapomina żywy wątek po join(timeout). Start może współdzielić wyzerowany stop_event ze starym wątkiem. | Wyjątkowo bezpieczny handshake, jawny właściciel socketu, nie porzucać referencji do żywego workera. | Średnie; transport bez zmiany formatu. | HA lifecycle / Deskmate transports | Nie |
| H3 `direct_bridge._read_events` | Timeout wysyła ping bez granicy czekania na odpowiedź. Martwe połączenie może pozostawać logicznie online. | Heartbeat aplikacyjny HA ping/pong, deadline i reconnect, backoff z jitter. | Średnie; wymaga testów połączeń bez ruchu. | HA WebSocket API | Nie |
| H4 `mqtt_bridge._monitor_loop` | Jeden wspólny try/except pozwala błędowi wczesnego sensora pomijać wszystkie późniejsze sensory w cyklu. | Izolacja pojedynczych zadań odczytu i limitowanie powtarzanych błędów. | Średnie; utrzymać częstotliwości i wartości publikacji. | HA coordinators | Nie |
| H5 `mqtt_bridge._on_message` | Komendy Windows/WinRT wykonywane na wątku sieci Paho mogą opóźniać keepalive i następne wiadomości. | Ograniczona, szeregowa kolejka wykonawcza; jawne odrzucenie po przepełnieniu, bez cichego wykonania po stop. | Wysokie; kolejność i timing komend muszą zostać zachowane. | Deskmate / HA async | Nie |
| H6 `media._AsyncRunner` | Stop pętli bez anulowania/oczekiwania na pending tasks; możliwe race przy starcie/close. | Właściciel pętli sprząta własne zadania w finally; zamknięty runner odrzuca nowe coroutine. | Średnie; testy z blokującą coroutine. | HA asyncio lifecycle | Nie |

## Medium

| ID / gdzie | Problem i skutek | Rozwiązanie | Ryzyko zmiany | Referencja | Nowa zależność |
| --- | --- | --- | --- | --- | --- |
| M1 `gui.py` | Formularze, tray, logi, worker management i bridge w jednym module ~2500 linii. | Wydzielać widoki i lifecycle wokół istniejących kontraktów, pozostawić kompatybilny import MainWindow. | Średnie | Fluent Widgets / Deskmate | Nie |
| M2 `overlay.py` | Model, kolejka, grafika, media i animacje w jednym module ~2500 linii. | Najpierw czysty model/kolejka/geometria i osobna karta; fasada publiczna pozostaje. | Średnie | pyqttoast | Nie |
| M3 `overlay._show_with_animation/hide` | 760/620 ms i zmiana rozmiaru okna w każdej klatce; zbędne reflow rodzeństwa i koszt DWM. | MotionSystem, 220/160 ms, stały layout podczas entrance/exit, translation + opacity. | Średnie; wymaga testu Acrylic/GPU | WinUI / pyqttoast | Nie |
| M4 `overlay._queue` | deque(maxlen=20) przy sortowaniu priorytetowym może wyrzucić najważniejszą kartę po napływie następnej. | Jawna stabilna polityka limitu: zachować wyższy priorytet, obsłużyć update/remove. | Niskie | pyqttoast (nasza semantyka priorytetów) | Nie |
| M5 `gui` workers | Drobne komendy uruchamiają kolejne niezarządzane wątki; wyniki mogą wrócić po zamknięciu GUI. | Kontrolowany wykonawca; ograniczenie prac, anulowanie oczekujących i odłączenie log handlera/timerów. | Średnie | HA lifecycle / Deskmate | Nie |
| M6 `app.STYLE` + `theme.py` | Duży bazowy QSS oraz kolejne nadpisania dark/light; kolory i stany rozproszone. | Jeden zestaw tokenów i generowany stylesheet, wspólne focus/disabled/hover. | Średnie; testy obu motywów | WinUI / Fluent Widgets | Nie |
| M7 `TitleBar`, `ToggleSwitch` | Brak wspólnego reduced motion; switch bez widocznego focus i nazwy dostępności. | Wspólne motion tokens; focus keyboard, accessibleName powiązany z ustawieniem. | Niskie | WinUI | Nie |
| M8 frameless GUI | System move jest, lecz brak obsługi natywnego hit-test krawędzi/Snap. Minimum 980 DIP ogranicza układy Snap. | Najpierw responsywność; oddzielny adapter Win32 i testy sprzętowe, nie obiecywać Snap bez weryfikacji. | Wysokie | CustomWindow / Microsoft Snap docs | Nie |
| M9 HA config flow | Brak reconfigure i diagnostyki; prywatne `_set_confirm_only`. | Oficjalne last_step i diagnostics; reconfigure tylko danych direct, bez zmiany device_id. | Średnie | HA Core / config flow docs | Nie |
| M10 HA entity cleanup | Ręczna lista unsubscribe nie gwarantuje sprzątania subskrypcji przy częściowym niepowodzeniu setup. | Rejestrować cleanup od razu przez async_on_remove. | Niskie | HA entity lifecycle | Nie |
| M11 direct notify availability | Brak potwierdzenia odebrania; encja direct nie dowodzi, że PC jest online. | Uczciwe rozróżnienie „wysłano”/„odebrano”; ewentualny ACK jako osobne wersjonowane rozszerzenie protokołu. | Wysokie; NIE zmieniać po cichu protokołu | HA / Deskmate | Nie |
| M12 `config.from_dict` | Złe typy kontenerów mogą generować AttributeError, niekontrolowany przez SettingsStore.load. | Walidacja root/nested/list przed migracją, czytelny ValueError; odrzucenie przyszłego schematu zamiast cichej degradacji. | Niskie/średnie | HA config validation | Nie |
| M13 ekrany / GPU capture | Obsługa sygnałów ekranu już istnieje, ale cache capture nie jest unieważniany po zmianie topologii/DPI. Indeksy wyjść mogą się zmienić po hotplug. | Zachować pozycjonowanie/fallback, dodać reset capture i kontrolowany cleanup subskrypcji. | Średnie; test sprzętowy | CustomWindow / pyqttoast | Nie |

## Low

| ID / gdzie | Problem i skutek | Rozwiązanie | Ryzyko zmiany | Referencja | Nowa zależność |
| --- | --- | --- | --- | --- | --- |
| L1 tray | Brak bezpośrednich skrótów do ustawień oraz pokazania/zamknięcia przykładu nakładki. Ponowne połączenie już istnieje. | Dodać krótkie akcje, zachować reconnect i spójny status; nie udawać pełnego HA przy samym MQTT. | Niskie | Deskmate | Nie |
| L2 diagnostics | Log większy niż 512 KB pomijany w całości. | Czytać ograniczony ogon pliku, nie cały plik; wszystkie sekrety filtrować. | Niskie | HA diagnostics | Nie |
| L3 GUI polling | Odczyty audio na każdej widocznej stronie, choć używa ich tylko strona aplikacji. | Odświeżać aktywny widok i natychmiast po wejściu na stronę. | Niskie | Deskmate snapshots | Nie |
| L4 komunikaty / testy | Test smoke sprawdza importy, nie tworzy pełnego okna; część testów GUI wiąże się z czasami animacji. | Osobny izolowany test uruchomienia okna, testy kontraktów motion zamiast starych magic numbers. | Niskie | WinUI tests / HA quality | Nie |

## Zachować

DPAPI, atomowy zapis JSON, eksport bez sekretów, limity payloadów, odrzucanie retained
commands, opt-in czujników prywatności/akcji zasilania, blokadę chronionych procesów,
QoS/LWT MQTT, brak pollingu encji HA, monitoring o różnych interwałach, istniejące
cache sensorów, ograniczone odświeżanie Liquid Glass, automatyczną siatkę tekstu,
identyfikatory urządzeń/encji, tematy MQTT, nazwy akcji HA, import starszych konfiguracji.

## Macierz weryfikacji na sprzęcie (niepotwierdzona przez offscreen)

Windows 10/11; dark/light; 100/125/150/200% DPI; monitory o różnym DPI i ujemnych
współrzędnych; hotplug; sleep/hibernate; lock/unlock; restart Explorer; restart HA/brokera;
zmiana Wi-Fi; brak sieci; Acrylic i GPU; 60/120/144 Hz. Wydajność oceniać pomiarem,
nie deklaracją. HACS icon zależny również od wersji frontendu HACS — nie traktować
obecności lokalnych PNG jako dowodu poprawnego wyświetlania w HACS.
